"""Mirror archived GitHub digests into the user's local research library."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
import journal_metrics
from paper_paths import safe_filename
from paper_digest import category_names, render_markdown, work_from_record


DEFAULT_ROOT = Path(r"E:\论文\知识点概述\日常文献查询记录")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_PDF_BYTES = 40 * 1024 * 1024


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=True,
    )
    return result.stdout


def report_paths(repo: Path) -> list[str]:
    git(repo, "fetch", "origin", "main")
    paths = git(repo, "ls-tree", "-r", "--name-only", "origin/main", "reports/daily")
    return sorted(path for path in paths.splitlines() if re.fullmatch(r"reports/daily/\d{4}-\d{2}-\d{2}\.json", path))


def fetch_open_pdf(paper: dict, folder: Path) -> Path | None:
    if paper.get("relevance") != "高":
        return None
    name = safe_filename(paper.get("title") or "", paper.get("doi") or paper.get("id") or "")
    target = folder / name
    if target.is_file() and target.stat().st_size > 1024:
        return target
    for url in paper.get("open_access_pdf_urls") or []:
        if urlparse(url).scheme != "https":
            continue
        temp_path = None
        try:
            request = Request(url, headers={"User-Agent": "sparse-terrain-digest/1.0"})
            with urlopen(request, timeout=45) as response:
                if urlparse(response.geturl()).scheme != "https":
                    continue
                with tempfile.NamedTemporaryFile(dir=folder, prefix=".pdf_", suffix=".tmp", delete=False) as output:
                    temp_path = Path(output.name)
                    count = 0
                    while chunk := response.read(128 * 1024):
                        count += len(chunk)
                        if count > MAX_PDF_BYTES:
                            raise ValueError("PDF exceeds 40 MiB limit")
                        output.write(chunk)
            with temp_path.open("rb") as source:
                header = source.read(5)
                source.seek(max(0, temp_path.stat().st_size - 2048))
                trailer = source.read()
                if header != b"%PDF-" or b"%%EOF" not in trailer or temp_path.stat().st_size < 1024:
                    raise ValueError("Response is not a complete PDF")
            os.replace(temp_path, target)
            return target
        except (OSError, ValueError) as exc:
            print(f"PDF unavailable for {paper.get('title')}: {type(exc).__name__}", file=sys.stderr)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
    return None


def plain_markdown(text: str) -> str:
    text = re.sub(r"\*\*|(?<!\\)`", "", text)
    return re.sub(r"\\([\\`*_\[\]<>])", r"\1", text)


INLINE = re.compile(r"(\*\*[^*]+\*\*|\[[^]]+\]\(<https://[^>]+>\)|\[[^]]+\]\(https://[^)]+\))")
LINK = re.compile(r"^\[([^]]+)\]\(<?(https://[^)>]+)>?\)$")


def add_rich(paragraph, text: str) -> None:
    last = 0
    for match in INLINE.finditer(text):
        if match.start() > last:
            paragraph.add_run(plain_markdown(text[last:match.start()]))
        token = match.group()
        link = LINK.fullmatch(token)
        if link:
            hyperlink = OxmlElement("w:hyperlink")
            hyperlink.set(qn("r:id"), paragraph.part.relate_to(link.group(2), RT.HYPERLINK, is_external=True))
            run = OxmlElement("w:r")
            properties = OxmlElement("w:rPr")
            color = OxmlElement("w:color")
            color.set(qn("w:val"), "175A77")
            properties.append(color)
            run.append(properties)
            value = OxmlElement("w:t")
            value.text = plain_markdown(link.group(1))
            run.append(value)
            hyperlink.append(run)
            paragraph._p.append(hyperlink)
        else:
            paragraph.add_run(plain_markdown(token[2:-2])).bold = True
        last = match.end()
    if last < len(text):
        paragraph.add_run(plain_markdown(text[last:]))


def heading_has_number(doc, style_name: str) -> bool:
    style = doc.styles[style_name]
    visited = set()
    while style is not None and style.style_id not in visited:
        visited.add(style.style_id)
        ppr = style.element.pPr
        numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if numpr is not None:
            numid = numpr.find(qn("w:numId"))
            if numid is not None:
                if numid.get(qn("w:val")) == "0":
                    return False
                level = numpr.find(qn("w:ilvl"))
                level = level.get(qn("w:val")) if level is not None else "0"
                numbering = doc.part.numbering_part.element
                nums = numbering.xpath(f'./w:num[@w:numId="{numid.get(qn("w:val"))}"]')
                if not nums:
                    return False
                abstract = nums[0].find(qn("w:abstractNumId"))
                if abstract is None:
                    return False
                overrides = nums[0].xpath(f'./w:lvlOverride[@w:ilvl="{level}"]/w:lvl/w:numFmt')
                formats = overrides or numbering.xpath(
                    f'./w:abstractNum[@w:abstractNumId="{abstract.get(qn("w:val"))}"]'
                    f'/w:lvl[@w:ilvl="{level}"]/w:numFmt'
                )
                return bool(formats and formats[0].get(qn("w:val")) not in {"bullet", "none"})
        style = style.base_style
    return False


def build_docx(markdown: str, output: Path, template: Path | None = None) -> None:
    template = template or Path(r"E:\论文\单篇论文梳理模板.docx")
    doc = Document(template) if template.is_file() else Document()
    for element in list(doc.element.body):
        if element.tag != qn("w:sectPr"):
            doc.element.body.remove(element)
    section = doc.sections[0]
    if not template.is_file():
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Cm(2.54)
    styles = doc.styles
    for name, size in (() if template.is_file() else (("Normal", 12), ("Title", 18), ("Heading 1", 16), ("Heading 2", 14))):
        style = styles[name]
        style.font.name = "Times New Roman"
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.space_after = Pt(4 if name == "Normal" else 7)
    if not template.is_file():
        styles["Normal"].paragraph_format.line_spacing = 1.22
    for name in ("Title", "Heading 1", "Heading 2"):
        if template.is_file():
            continue
        styles[name].paragraph_format.keep_with_next = True
        ppr = styles[name].element.pPr
        if ppr is not None:
            border = ppr.find(qn("w:pBdr"))
            if border is not None:
                ppr.remove(border)

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith("@hello1573"):
            continue
        if line.startswith("# "):
            paragraph = doc.add_paragraph(style="Title")
            add_rich(paragraph, line[2:])
        elif line.startswith("## "):
            text = line[3:]
            if heading_has_number(doc, "Heading 1"):
                text = re.sub(r"^\d+\.\s+", "", text)
            add_rich(doc.add_paragraph(style="Heading 1"), text)
        elif line.startswith("### "):
            add_rich(doc.add_paragraph(style="Heading 2"), line[4:])
        else:
            paragraph = doc.add_paragraph()
            if line.startswith("**本地路径：**"):
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                paragraph.paragraph_format.first_line_indent = Pt(0)
            add_rich(paragraph, line)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name("." + output.name)
    doc.save(temp)
    if template.is_file():
        with zipfile.ZipFile(temp) as authored:
            body = authored.read("word/document.xml")
            relationships = authored.read("word/_rels/document.xml.rels")
        # Preserve the template's styles, fields, footer and opaque package parts.
        with zipfile.ZipFile(template) as reference, zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as final:
            for part in reference.infolist():
                content = body if part.filename == "word/document.xml" else relationships if part.filename == "word/_rels/document.xml.rels" else reference.read(part.filename)
                final.writestr(part, content)
    os.replace(temp, output)


def metric_columns(name: str, source_type: str | None, reported: dict | None = None) -> dict:
    registry = journal_metrics.lookup(name, source_type)
    reported = reported or {}
    if reported.get("checked_at", "") > registry.get("checked_at", ""):
        metrics = journal_metrics.merge_metrics(registry, reported)
    else:
        metrics = journal_metrics.merge_metrics(reported, registry)
    if metrics.get("not_applicable"):
        return {"indexing": "非期刊成果", "jcr": "不适用", "cas": "不适用"}
    return {
        "indexing": metrics.get("indexing") or "公开记录未确认收录类型",
        "jcr": journal_metrics.jcr_display(metrics),
        "cas": f"{metrics['cas']}（{metrics['cas_year']}版）" if metrics.get("cas") else "公开查询未取得2025版分区值",
        "if_value": metrics.get("if_value"), "if_year": metrics.get("if_year"),
        "metrics_verified": [k for k in ("indexing", "jcr", "cas", "if_value", "if_year") if metrics.get(k) is not None or (k == "jcr" and metrics.get("jcr_subjects"))],
    }


def normalized_key(paper: dict) -> str:
    doi = (paper.get("doi") or "").lower().removeprefix("https://doi.org/")
    title = re.sub(r"\W+", "", (paper.get("title") or "").casefold())
    return doi or title


def rows_from_ledger(root: Path) -> list[dict]:
    path = root / "文献收录与阅读台账.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for record in data.get("records", []):
        files = record.get("local_files") or []
        rows.append({
            "date": record.get("publication_date") or record.get("publication_year") or "",
            "title": record.get("title"),
            "title_zh": record.get("title_zh") or "",
            "journal": record.get("journal"),
            **metric_columns(record.get("journal"), "journal" if record.get("publication_type") == "journal-article" else "other"),
            "direction": record.get("main_direction") or "",
            "categories": "、".join(category_names(record.get("categories") or [])),
            "doi": record.get("doi"),
            "relevance": record.get("relevance") or "",
            "pdf": files[0].get("path") if files else "",
            "url": next((s for s in record.get("sources") or [] if str(s).startswith("https://")), ""),
            "collected": (record.get("pushed_dates") or [record.get("collected_at", "")[:10]])[0],
            "reading_status": record.get("reading_status") or "未确认用户已读",
            "notes": "；".join(record.get("notes") or []),
        })
    return rows


def rows_from_reports(reports: list[tuple[dict, dict[str, str]]]) -> list[dict]:
    rows = []
    for report, downloads in reports:
        for paper in report["papers"]:
            rows.append({
                "date": paper.get("publication_date"), "title": paper.get("title"),
                "title_zh": paper.get("title_zh"),
                "journal": paper.get("journal"), **metric_columns(paper.get("journal"), paper.get("source_type"), paper.get("journal_metrics")),
                "direction": paper.get("direction"),
                "categories": "、".join(category_names(paper.get("categories") or [])),
                "doi": paper.get("doi"), "relevance": paper.get("relevance"),
                "pdf": downloads.get(normalized_key(paper), ""), "url": paper.get("url"),
                "collected": report["date"],
            })
    return rows


def run(repo: Path, root: Path, node: Path, builder: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / ".paper_sync_state.json"
    attempts = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    today = datetime.now().date().isoformat()
    reports = []
    for path in report_paths(repo):
        report = json.loads(git(repo, "show", f"origin/main:{path}"))
        day = report.get("date", "")
        if not DAY_RE.fullmatch(day) or report.get("schema_version") != 1:
            raise ValueError(f"Unrecognized report manifest: {path}")
        if path != f"reports/daily/{day}.json":
            raise ValueError(f"Report date does not match filename: {path}")
        markdown = git(repo, "show", f"origin/main:reports/daily/{day}.md")
        markdown_path = root / f"{day}_稀疏地形重建文献简报.md"
        docx_path = root / f"{day}_稀疏地形重建文献简报.docx"
        pdf_folder = root / "论文" / day
        pdf_folder.mkdir(parents=True, exist_ok=True)
        downloads = {}
        for paper in report["papers"]:
            key = normalized_key(paper)
            expected = pdf_folder / safe_filename(paper.get("title") or "", paper.get("doi") or paper.get("id") or "")
            if attempts.get(day + ":" + key) == today and not expected.exists():
                continue
            result = fetch_open_pdf(paper, pdf_folder)
            if result:
                downloads[key] = str(result)
            elif paper.get("relevance") == "高" and paper.get("open_access_pdf_urls"):
                attempts[day + ":" + key] = today
        if all(p.get("format_version") == 2 for p in report["papers"]) and report["papers"]:
            markdown = render_markdown([work_from_record(p, downloads.get(normalized_key(p))) for p in report["papers"]], day)
        previous = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else None
        if previous != markdown or not docx_path.exists():
            if docx_path.exists() and previous is not None:
                backup = root / "备份"
                backup.mkdir(exist_ok=True)
                import shutil
                shutil.copy2(docx_path, backup / (docx_path.stem + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".docx"))
            markdown_path.write_text(markdown, encoding="utf-8")
            build_docx(markdown, docx_path)
        reports.append((report, downloads))

    rows = rows_from_ledger(root) + rows_from_reports(reports)
    # The workbook builder appends missing records, preserving existing user edits.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as source:
        json.dump(rows, source, ensure_ascii=False)
        input_path = Path(source.name)
    try:
        workbook_path = root / "稀疏地形重建文献总表.xlsx"
        subprocess.run([str(node), str(builder), str(input_path), str(workbook_path)], check=True, timeout=180)
    finally:
        input_path.unlink(missing_ok=True)
    temp_state = state_path.with_suffix(".tmp")
    temp_state.write_text(json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_state, state_path)
    print(f"已同步 {len(reports)} 期日报，文献目录 {len(rows)} 条候选记录。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--builder", type=Path, default=Path(__file__).with_name("build_catalog.mjs"))
    args = parser.parse_args()
    run(args.repo, args.root, args.node, args.builder)


if __name__ == "__main__":
    main()
