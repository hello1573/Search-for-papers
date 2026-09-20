import argparse
import html
import json
import os
import time
from datetime import datetime, timezone
from datetime import timedelta
from typing import Any

import requests


OPENALEX_URL = "https://api.openalex.org/works"
QUERIES = (
    "sparse terrain reconstruction",
    "sparse DEM reconstruction",
    "digital elevation model completion",
    "terrain surface reconstruction sparse sampling",
    "point cloud elevation completion",
    "remote sensing DEM inpainting",
)

KEYWORDS = {
    "sparse": 4,
    "terrain": 4,
    "reconstruction": 5,
    "elevation": 4,
    "digital elevation model": 6,
    "dem": 2,
    "completion": 4,
    "inpainting": 4,
    "interpolation": 3,
    "point cloud": 3,
    "lidar": 2,
    "topographic": 2,
    "remote sensing": 2,
    "missing data": 2,
}

CORE_TERRAIN_TERMS = (
    "terrain",
    "topograph",
    "digital elevation model",
    "dem",
    "landform",
    "contour line",
    "elevation",
    "point cloud",
    "lidar",
    "surface model",
)

RECONSTRUCTION_TERMS = (
    "reconstruct",
    "completion",
    "inpaint",
    "interpolat",
    "recovery",
    "gap filling",
    "missing data",
    "super-resolution",
)


def abstract_text(work: dict[str, Any]) -> str:
    inverted = work.get("abstract_inverted_index") or {}
    words: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        words.extend((position, word) for position in positions)
    return " ".join(word for _, word in sorted(words))


def work_text(work: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            work.get("title", ""),
            work.get("display_name", ""),
            abstract_text(work),
        )
        if part
    ).lower()


def relevance_score(work: dict[str, Any]) -> int:
    title = (work.get("title") or "").lower()
    text = work_text(work)
    score = 0
    for keyword, weight in KEYWORDS.items():
        if keyword in text:
            score += weight
        if keyword in title:
            score += weight
    return score


def is_terrain_relevant(work: dict[str, Any]) -> bool:
    text = work_text(work)
    has_core_object = any(term in text for term in CORE_TERRAIN_TERMS)
    has_reconstruction_task = any(term in text for term in RECONSTRUCTION_TERMS)
    return has_core_object and has_reconstruction_task


def search_openalex(
    session: requests.Session, query: str, from_date: str
) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{from_date}",
        "sort": "publication_date:desc",
        "per-page": 30,
    }
    mailto = session.headers.get("mailto")
    if mailto:
        params["mailto"] = mailto
    for attempt in range(4):
        response = session.get(OPENALEX_URL, params=params, timeout=30)
        if response.status_code != 429:
            response.raise_for_status()
            return response.json().get("results", [])
        if attempt < 3:
            retry_after = response.headers.get("Retry-After")
            delay = int(retry_after) if retry_after and retry_after.isdigit() else 3 * (attempt + 1)
            time.sleep(min(delay, 30))
    return []


def paper_keys(work: dict[str, Any]) -> set[str]:
    primary_location = work.get("primary_location") or {}
    values = {
        work.get("id"),
        work.get("doi"),
        primary_location.get("landing_page_url"),
    }
    keys = set()
    for value in values:
        if not value:
            continue
        key = str(value).strip().lower().rstrip("/")
        if key.startswith("https://doi.org/"):
            key = key.removeprefix("https://doi.org/")
        elif key.startswith("http://doi.org/"):
            key = key.removeprefix("http://doi.org/")
        keys.add(key)
    return keys


def load_seen(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as source:
            values = source.read()
        data = json.loads(values)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    return {str(value).strip().lower().rstrip("/") for value in data}


def save_seen(path: str, seen: set[str]) -> None:
    with open(path, "w", encoding="utf-8") as target:
        json.dump(sorted(seen), target, ensure_ascii=False, indent=2)
        target.write("\n")


def collect_papers(seen: set[str]) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "sparse-terrain-daily/1.0",
            "Accept": "application/json",
        }
    )
    mailto = os.getenv("OPENALEX_MAILTO")
    if mailto:
        session.headers["mailto"] = mailto

    from_date = (datetime.now(timezone.utc).date() - timedelta(days=730)).isoformat()
    papers: dict[str, dict[str, Any]] = {}
    for query in QUERIES:
        for rank, work in enumerate(search_openalex(session, query, from_date)):
            work_id = work.get("id")
            if not work_id or not work.get("title"):
                continue
            if not is_terrain_relevant(work):
                continue
            score = relevance_score(work) + max(0, 10 - rank // 5)
            current = papers.get(work_id)
            if current is None or score > current["_score"]:
                work["_score"] = score
                papers[work_id] = work

    ranked = sorted(
        papers.values(),
        key=lambda item: (item.get("publication_date") or "", item["_score"]),
        reverse=True,
    )
    return [
        paper
        for paper in ranked
        if paper["_score"] >= 8 and not paper_keys(paper).intersection(seen)
    ][:8]


def authors_text(work: dict[str, Any]) -> str:
    authors = [
        (authorship.get("author") or {}).get("display_name")
        for authorship in work.get("authorships", [])
    ]
    names = [name for name in authors if name]
    if not names:
        return "作者信息未提供"
    if len(names) > 4:
        return ", ".join(names[:4]) + " 等"
    return ", ".join(names)


def abstract_excerpt(work: dict[str, Any]) -> str:
    abstract = abstract_text(work).strip()
    if not abstract:
        return "暂无可用摘要，请打开来源页面查看详情。"
    if len(abstract) > 520:
        return abstract[:520].rstrip() + "..."
    return abstract


def render_markdown(papers: list[dict[str, Any]]) -> str:
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    mention = os.getenv("DIGEST_MENTION", "@hello1573")
    lines = [
        mention,
        "",
        f"# 稀疏地形重建文章日报｜{today}",
        "",
        "以下结果来自 OpenAlex，按与稀疏采样、DEM 修复、地形重建和高程补全的相关性筛选。",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        title = html.escape(paper.get("title") or "未命名文章")
        primary_location = paper.get("primary_location") or {}
        url = (
            paper.get("doi")
            or primary_location.get("landing_page_url")
            or paper.get("id")
            or "#"
        )
        date = html.escape(paper.get("publication_date") or "日期未知")
        authors = html.escape(authors_text(paper))
        abstract = html.escape(abstract_excerpt(paper))
        lines.extend(
            [
                f"### {index}. [{title}](<{url}>)",
                f"- **作者：** {authors}",
                f"- **发布日期：** {date}",
                "",
                abstract,
                "",
            ]
        )
    if not papers:
        lines.extend(["今天没有找到达到相关性阈值的文章。", ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="digest.md")
    parser.add_argument("--state", default="seen_papers.json")
    parser.add_argument("--count-output", default="digest_count.txt")
    args = parser.parse_args()
    seen = load_seen(args.state)
    papers = collect_papers(seen)
    content = render_markdown(papers)
    with open(args.output, "w", encoding="utf-8") as output:
        output.write(content)
    if papers:
        for paper in papers:
            seen.update(paper_keys(paper))
        save_seen(args.state, seen)
    with open(args.count_output, "w", encoding="ascii") as count_output:
        count_output.write(str(len(papers)))
    print(f"已生成 {len(papers)} 篇文章的日报：{args.output}")


if __name__ == "__main__":
    main()
