import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
import journal_metrics
from paper_paths import safe_filename


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
    "bare earth",
    "bathymetr",
)

TITLE_TERRAIN_TERMS = (
    "terrain", "topograph", "digital elevation model", "digital terrain model",
    "dem", "dtm", "bathymetr", "seabed", "subglacial", "ground point",
)

EXCLUDED_TITLE_TERMS = (
    "robot", "humanoid", "locomotion", "foothold", "walking", "traversability",
    "rf propagation", "radio propagation",
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
    "void filling",
    "terrain generation",
    "dem generation",
    "dtm generation",
    "ground filtering",
    "ground classification",
)

DATA_LABELS = (
    ("digital elevation model", "DEM"),
    ("dem", "DEM"),
    ("digital surface model", "DSM"),
    ("dsm", "DSM"),
    ("digital terrain model", "DTM"),
    ("dtm", "DTM"),
    ("point cloud", "点云"),
    ("lidar", "LiDAR 点云"),
    ("remote sensing", "遥感数据"),
    ("satellite imagery", "卫星影像"),
    ("aerial imagery", "航空影像"),
    ("uav", "无人机数据"),
    ("insar", "InSAR 数据"),
    ("bathymetr", "海底地形数据"),
    ("contour line", "等高线"),
)

METHOD_LABELS = (
    ("diffusion", "扩散模型"),
    ("generative adversarial", "生成对抗网络"),
    ("gan", "生成对抗网络"),
    ("transformer", "Transformer"),
    ("u-net", "U-Net"),
    ("unet", "U-Net"),
    ("convolution", "卷积网络"),
    ("self-supervised", "自监督学习"),
    ("implicit neural", "隐式神经表示"),
    ("interpolat", "插值"),
    ("patch matching", "块匹配"),
    ("data fusion", "多源数据融合"),
    ("physics-informed", "物理约束学习"),
    ("attention", "注意力机制"),
)

PROBLEM_TERMS = (
    "challenge",
    "problem",
    "difficulty",
    "difficult",
    "limited",
    "lack",
    "suffer",
    "however",
    "remain",
    "address",
    "missing",
    "incomplete",
    "sparse",
    "occlusion",
)

METHOD_TERMS = (
    "propose",
    "present",
    "develop",
    "introduce",
    "framework",
    "method",
    "model",
    "network",
    "approach",
    "employ",
    "using",
    "consist",
    "trained",
)

CONTRIBUTION_TERMS = (
    "result",
    "outperform",
    "improve",
    "achieve",
    "demonstrate",
    "effective",
    "accuracy",
    "rmse",
    "mae",
    "superior",
    "significant",
    "reduce",
    "increase",
)

INNOVATION_TERMS = (
    "novel",
    "new",
    "first",
    "propose",
    "introduce",
    "develop",
    "unlike",
    "different",
    "integrat",
    "combine",
    "joint",
    "terrain-aware",
    "topology",
    "topological",
)

CONCLUSION_TERMS = (
    "conclude",
    "conclusion",
    "findings suggest",
    "results suggest",
    "results indicate",
    "our findings",
)

# These labels mirror the paper folders; a paper can match several categories.
CATEGORY_TERMS = (
    ("01_地面分类与滤波", ("ground classification", "ground filtering", "ground point", "bare earth")),
    ("02_DTM生成_分类后与联合重建", ("digital terrain model", "dtm", "dsm-to-dtm", "bare-earth model")),
    ("03_缺失地形恢复_空洞填补", ("void", "gap filling", "missing", "inpaint", "hole filling")),
    ("04_DEM超分辨率与稠密化", ("super-resolution", "super resolution", "densification", "upsampling")),
    ("05_曲面建模_插值与隐式表示", ("interpolat", "implicit", "surface fitting", "surface reconstruction")),
    ("06_多源数据与摄影测量重建", ("data fusion", "multi-source", "multisource", "photogrammetry", "uav", "satellite imagery")),
    ("07_拓扑结构与地形特征", ("topology", "topological", "ridge", "valley", "breakline", "terrain feature")),
    ("08_评价_综述与数据集", ("benchmark", "review", "survey", "uncertainty", "new dataset")),
    ("09_跨领域与通用点云补全", ("point cloud completion", "general point cloud", "shape completion")),
)

CATEGORY_NAMES = {
    "01": "地面分类与滤波", "02": "DTM生成与联合重建",
    "03": "缺失地形恢复与空洞填补", "04": "DEM超分辨率与稠密化",
    "05": "曲面建模、插值与隐式表示", "06": "多源数据与摄影测量重建",
    "07": "拓扑结构与地形特征", "08": "评价、综述与数据集",
    "09": "跨领域与通用点云补全",
}

NOTE_FIELDS = ("title_zh", "background", "background_plain", "method", "method_plain", "innovation_overview", "innovation_plain", "results", "conclusion", "plain")
SUMMARY_API_BASE_URL = "https://www.lwjcode.xyz/v1"
SUMMARY_MODEL = "gpt-5.6-terra"


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
        if contains_term(text, keyword):
            score += weight
        if contains_term(title, keyword):
            score += weight
    return score


def contains_term(text: str, term: str) -> bool:
    suffix = (
        r"\w*"
        if term
        in {
            "topograph",
            "reconstruct",
            "inpaint",
            "interpolat",
            "bathymetr",
            "integrat",
            "ridge",
            "valley",
            "breakline",
        }
        else ""
    )
    return bool(re.search(r"\b" + re.escape(term) + suffix + r"\b", text))


def is_terrain_relevant(work: dict[str, Any]) -> bool:
    text = work_text(work)
    title = (work.get("title") or "").lower()
    if re.search(r"\b(reply|response|comment|corrigendum|erratum)\s+(to|on)\b", title):
        return False
    if any(contains_term(title, term) for term in EXCLUDED_TITLE_TERMS):
        return False
    # A terrain term in the abstract alone is often only a study-area covariate.
    has_core_object = any(contains_term(title, term) for term in TITLE_TERRAIN_TERMS)
    has_reconstruction_task = any(contains_term(text, term) for term in RECONSTRUCTION_TERMS)
    return has_core_object and has_reconstruction_task


def search_openalex(
    session: requests.Session, query: str, from_date: str, to_date: str | None = None
) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "filter": f"from_publication_date:{from_date}" + (f",to_publication_date:{to_date}" if to_date else ""),
        "sort": "publication_date:desc",
        "per-page": 100,
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


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", html.unescape(title)).casefold()
    return "".join(char for char in text if char.isalnum())


def normalize_identifier(value: str) -> str:
    key = unquote(str(value)).strip().casefold().rstrip("/")
    key = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", key)
    if key.startswith("http://openalex.org/"):
        key = "https://" + key.removeprefix("http://")
    return key


def paper_keys(work: dict[str, Any]) -> set[str]:
    primary_location = work.get("primary_location") or {}
    values = {
        work.get("id"),
        work.get("doi"),
        primary_location.get("landing_page_url"),
    }
    keys = {normalize_identifier(value) for value in values if value}
    for field in ("title", "display_name"):
        title = normalize_title(work.get(field) or "")
        if title:
            keys.add("title:" + title)
    return keys


def load_seen(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as source:
            values = source.read()
        data = json.loads(values)
    except FileNotFoundError:
        return set()
    if not isinstance(data, list) or not all(isinstance(value, str) for value in data):
        raise ValueError("Invalid sent-paper history; refusing to reset deduplication.")
    return {normalize_identifier(value) for value in data}


def load_known(path: str) -> set[str]:
    with open(path, encoding="utf-8") as source:
        data = json.load(source)
    keys = set()
    for paper in data["papers"]:
        keys.update(paper_keys(paper))
        for alias in paper.get("aliases", []):
            title = normalize_title(alias)
            if title:
                keys.add("title:" + title)
    return keys


def load_catalog_index(path: str) -> set[str]:
    with open(path, encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, list) or not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in data):
        raise ValueError("Invalid local catalog exclusion index")
    return {"sha256:" + value for value in data}


def hashed_keys(keys: set[str]) -> set[str]:
    return {"sha256:" + hashlib.sha256(key.encode("utf-8")).hexdigest() for key in keys}


def save_seen(path: str, seen: set[str]) -> None:
    with open(path, "w", encoding="utf-8") as target:
        json.dump(sorted(seen), target, ensure_ascii=False, indent=2)
        target.write("\n")


def select_papers(papers: list[dict[str, Any]], excluded: set[str]) -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    from_date = "2018-01-01"
    ranked = sorted(
        papers,
        key=lambda item: (item.get("publication_date") or "", item["_score"]),
        reverse=True,
    )
    selected = []
    selected_keys = set(excluded)
    for paper in ranked:
        date = paper.get("publication_date") or ""
        keys = paper_keys(paper)
        if (
            paper["_score"] < 14
            or not from_date <= date <= today.isoformat()
            or (keys | hashed_keys(keys)).intersection(selected_keys)
        ):
            continue
        selected.append(paper)
        selected_keys.update(keys)
        if len(selected) == 8:
            break
    return selected


def collect_papers(excluded: set[str]) -> list[dict[str, Any]]:
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

    recent = (datetime.now(timezone.utc).date() - timedelta(days=730)).isoformat()
    papers: dict[str, dict[str, Any]] = {}
    for query in QUERIES:
        results = search_openalex(session, query, recent)
        # Search older work separately so unseen papers are not hidden by the newest page.
        results += search_openalex(session, query, "2018-01-01", (datetime.fromisoformat(recent).date() - timedelta(days=1)).isoformat())
        for rank, work in enumerate(results):
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

    return select_papers(list(papers.values()), excluded)


def authors_text(work: dict[str, Any]) -> str:
    if work.get("_authors"):
        return str(work["_authors"])
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


def abstract_sentences(work: dict[str, Any]) -> list[str]:
    abstract = re.sub(r"\s+", " ", abstract_text(work)).strip()
    if not abstract:
        return []
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])", abstract)
        if sentence.strip()
    ]


def clip_text(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."


def sentence_with_terms(
    sentences: list[str], terms: tuple[str, ...], limit: int = 320
) -> str | None:
    for sentence in sentences:
        lowered = sentence.casefold()
        if any(contains_term(lowered, term) for term in terms):
            return clip_text(sentence, limit)
    return None


def detected_labels(text: str, definitions: tuple[tuple[str, str], ...]) -> list[str]:
    labels = []
    for term, label in definitions:
        if contains_term(text, term) and label not in labels:
            labels.append(label)
    if "LiDAR 点云" in labels and "点云" in labels:
        labels.remove("点云")
    return labels


def task_label(work: dict[str, Any]) -> str:
    if work.get("_direction"):
        return work["_direction"]
    text = work_text(work)
    if any(
        contains_term(text, term)
        for term in ("void", "gap filling", "missing data", "inpaint")
    ):
        return "地形或 DEM 缺失区域修复"
    if contains_term(text, "super-resolution"):
        return "DEM 超分辨率与稠密化"
    if contains_term(text, "point cloud") and contains_term(text, "completion"):
        return "地形点云补全"
    if "dsm-to-dtm" in text or (
        contains_term(text, "dsm") and contains_term(text, "dtm")
    ):
        return "DSM 到 DTM 重建"
    if contains_term(text, "interpolat"):
        return "稀疏高程插值与连续曲面构建"
    if contains_term(text, "dem") and contains_term(text, "reconstruct"):
        return "DEM 重建与高程恢复"
    if contains_term(text, "terrain") and contains_term(text, "reconstruct"):
        return "地形表面重建"
    return "地形表面重建或高程恢复"


def input_data_summary(work: dict[str, Any], sentences: list[str]) -> str:
    text = work_text(work)
    labels = detected_labels(text, DATA_LABELS)
    evidence = sentence_with_terms(
        sentences,
        (
            "dataset",
            "data",
            "input",
            "imagery",
            "image",
            "lidar",
            "point cloud",
            "dem",
            "dsm",
            "observation",
            "sample",
        ),
        240,
    )
    if labels and evidence:
        return f"涉及{'、'.join(labels)}。摘要依据：{evidence}"
    if labels:
        return f"涉及{'、'.join(labels)}；具体数据集、分辨率和样本规模需阅读全文核实。"
    return "摘要未明确说明具体输入数据、分辨率或样本规模，需阅读全文核实。"


def technical_route_summary(work: dict[str, Any], sentences: list[str]) -> str:
    text = work_text(work)
    data = detected_labels(text, DATA_LABELS)
    methods = detected_labels(text, METHOD_LABELS)
    route = " → ".join(
        [
            "、".join(data[:3]) if data else "输入数据",
            " + ".join(methods[:3]) if methods else "论文方法",
            task_label(work),
        ]
    )
    evidence = sentence_with_terms(sentences, METHOD_TERMS, 280)
    return f"{route}。" + (
        f"摘要依据：{evidence}" if evidence else "具体模块和训练流程需阅读全文核实。"
    )


def research_problem_summary(work: dict[str, Any], sentences: list[str]) -> str:
    evidence = sentence_with_terms(sentences, PROBLEM_TERMS, 300)
    if evidence:
        return evidence
    if sentences:
        return clip_text(sentences[0], 300)
    return f"从题名看，研究聚焦于{task_label(work)}；摘要缺失，具体问题定义需阅读全文核实。"


def contribution_summary(work: dict[str, Any], sentences: list[str]) -> str:
    evidence = sentence_with_terms(sentences, CONTRIBUTION_TERMS, 340)
    methods = detected_labels(work_text(work), METHOD_LABELS)
    if evidence:
        return evidence
    if methods:
        return f"摘要显示采用{'、'.join(methods[:3])}处理{task_label(work)}；定量提升和消融结果需阅读全文核实。"
    return "摘要未明确给出可核验的主要贡献或定量结果，需阅读全文核实。"


def innovation_summary(work: dict[str, Any], sentences: list[str]) -> str:
    evidence = sentence_with_terms(sentences, INNOVATION_TERMS, 340)
    methods = detected_labels(work_text(work), METHOD_LABELS)
    if evidence:
        return evidence
    if methods:
        return f"摘要显示将{'、'.join(methods[:3])}用于{task_label(work)}；相对现有方法的具体差异需阅读全文核实。"
    return "摘要未明确说明相对现有工作的创新差异，需阅读全文核实。"


def relevance_summary(work: dict[str, Any]) -> tuple[str, str]:
    if work.get("_relevance"):
        return work["_relevance"], work.get("_relevance_reason") or "根据已核验内容判断"
    text = work_text(work)
    data = detected_labels(text, DATA_LABELS)
    methods = detected_labels(text, METHOD_LABELS)
    score = work.get("_score", relevance_score(work))
    level = "高" if score >= 24 else "中" if score >= 14 else "较低"
    details = [task_label(work)]
    if data:
        details.append("对象包含" + "、".join(data[:3]))
    if methods:
        details.append("方法涉及" + "、".join(methods[:3]))
    return level, "；".join(details)


def category_names(labels) -> list[str]:
    result = []
    for label in labels:
        code = re.match(r"^(\d{2})(?:_|$)", str(label))
        name = CATEGORY_NAMES.get(code.group(1)) if code else str(label)
        name = (name or str(label)).replace("_", "与")
        if name not in result:
            result.append(name)
    return result


def categories(work: dict[str, Any]) -> list[str]:
    if work.get("_categories"):
        return category_names(work["_categories"])
    text = work_text(work)
    matched = [
        name for name, terms in CATEGORY_TERMS
        if any(contains_term(text, term) for term in terms)
    ]
    return category_names(matched) or ["待人工分类"]


def journal_name(work: dict[str, Any]) -> str:
    source = ((work.get("primary_location") or {}).get("source") or {})
    name = source.get("display_name")
    if source.get("type") == "journal" and name:
        return str(name)
    if name:
        return f"{name}（来源类型：{source.get('type') or '未提供'}；不确认为期刊）"
    return "来源未提供，期刊名称待核实"


def source_url(work: dict[str, Any]) -> str:
    location = work.get("primary_location") or {}
    for candidate in (work.get("doi"), location.get("landing_page_url"), work.get("id")):
        if candidate and urlparse(str(candidate)).scheme in ("https", "http"):
            return str(candidate)
    return ""


def markdown_text(value: str) -> str:
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", html.escape(str(value), quote=False))


def abstract_result(sentences: list[str]) -> str:
    evidence = sentence_with_terms(sentences, CONTRIBUTION_TERMS, 340)
    if evidence:
        return f"摘要报告：{evidence} 具体数值、对比基线和实验设置仅在摘要明确写出时才可据此判断，仍需阅读全文核实。"
    return "摘要未给出可核实的实验结果；数据、对比方法和指标需阅读全文核实。"


def abstract_conclusion(sentences: list[str]) -> str:
    evidence = sentence_with_terms(sentences, CONCLUSION_TERMS, 300)
    if evidence:
        return f"摘要中的结论性表述：{evidence} 作者承认的局限与未来方向需阅读全文核实。"
    return "摘要未明确给出可单独归纳的结论；作者承认的局限和未来方向需阅读全文核实。"


def summarize_from_abstract(work: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("SUMMARY_API_KEY")
    abstract = abstract_text(work).strip()
    if not key or not abstract:
        return {}
    base = (os.getenv("SUMMARY_API_BASE_URL") or SUMMARY_API_BASE_URL).rstrip("/")
    if urlparse(base).scheme != "https":
        print("Summary API requires HTTPS; using metadata-only fallback.", file=sys.stderr)
        return {}
    metadata = {
        "title": work.get("title"),
        "date": work.get("publication_date"),
        "journal": journal_name(work),
        "abstract": abstract,
    }
    instructions = Path(__file__).with_name("summary_schema_prompt.txt").read_text(encoding="utf-8")
    try:
        response = requests.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.getenv("SUMMARY_MODEL") or SUMMARY_MODEL,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps(metadata, ensure_ascii=False)},
                ],
                "temperature": 0.1,
                "max_tokens": 6500,
            },
            timeout=150,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
        sections = json.loads(content)
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        print(f"Summary API failed ({type(exc).__name__}); using metadata-only fallback.", file=sys.stderr)
        return {}

    if not isinstance(sections, dict):
        return {}
    verified = {}
    normalized_abstract = re.sub(r"\s+", " ", abstract).casefold()
    evidence_store = {}
    for field in NOTE_FIELDS:
        entry = sections.get(field)
        if not isinstance(entry, dict):
            continue
        text, evidence = entry.get("text"), entry.get("evidence")
        if not isinstance(text, str) or not isinstance(evidence, str):
            continue
        text = text.strip()
        evidence = re.sub(r"\s+", " ", evidence).strip()
        if not text or len(text) > (2200 if field in ("background", "method") else 1000) or len(evidence) > len(abstract) + len(work.get("title") or "") + 50:
            continue
        if any(claim in text for claim in ("世界首次", "首次提出", "首创")):
            continue
        if not evidence:
            if text.startswith("摘要未说明"):
                verified[field] = text
            continue
        basis = re.sub(r"\s+", " ", work.get("title") or "").casefold() if field == "title_zh" else normalized_abstract
        if evidence.casefold() not in basis:
            continue
        if any(number not in evidence for number in re.findall(r"\d+(?:\.\d+)?%?", text)):
            continue
        if re.search(r"https?://|\bdoi\b", text, re.I):
            continue
        verified[field] = text
        evidence_store[field] = evidence
    innovations = []
    entries = sections.get("innovations")
    for entry in (entries if isinstance(entries, list) else [])[:4]:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("claim", "analysis", "evidence")):
            continue
        claim, analysis, evidence = (entry[k].strip() for k in ("claim", "analysis", "evidence"))
        text = claim + analysis
        evidence = re.sub(r"\s+", " ", evidence)
        if not claim or len(claim) > 160 or len(analysis) > 1200 or not evidence or evidence.casefold() not in normalized_abstract:
            continue
        if any(word in text for word in ("世界首次", "首次提出", "首创")) or re.search(r"https?://|\bdoi\b", text, re.I):
            continue
        if any(number not in evidence for number in re.findall(r"\d+(?:\.\d+)?%?", text)):
            continue
        innovations.append({"claim": claim, "analysis": analysis})
        evidence_store[f"innovation_{len(innovations)}"] = evidence
    verified["innovations"] = innovations
    work["_summary_evidence"] = evidence_store
    return verified


def summary_complete(summary: dict) -> bool:
    return all(summary.get(field) for field in NOTE_FIELDS) and not summary["background"].startswith("摘要未说明") and not summary["title_zh"].startswith("摘要未说明")


def note_section(work: dict[str, Any], field: str, fallback: str) -> str:
    note = (work.get("_summary") or {}).get(field)
    return markdown_text(note if note else fallback)


def metrics_for(work):
    source = ((work.get("primary_location") or {}).get("source") or {})
    return work.get("_metrics") or journal_metrics.lookup(source.get("display_name"), source.get("type"))


def report_record(work: dict[str, Any]) -> dict[str, Any]:
    oa_locations = [work.get("best_oa_location") or {}]
    oa_locations.extend(location for location in work.get("locations") or [] if location.get("is_oa"))
    pdf_urls = []
    for location in oa_locations:
        url = location.get("pdf_url")
        if url and urlparse(str(url)).scheme == "https" and url not in pdf_urls:
            pdf_urls.append(url)
    source = ((work.get("primary_location") or {}).get("source") or {})
    relevance, reason = relevance_summary(work)
    return {
        "id": work.get("id"),
        "title": work.get("title"),
        "title_zh": (work.get("_summary") or {}).get("title_zh"),
        "authors": authors_text(work),
        "publication_date": work.get("publication_date"),
        "journal": journal_name(work),
        "source_type": source.get("type"),
        "doi": work.get("doi"),
        "url": source_url(work),
        "categories": categories(work),
        "direction": task_label(work),
        "relevance": relevance,
        "relevance_reason": reason,
        "abstract": abstract_text(work),
        "open_access_pdf_urls": pdf_urls,
        "reading_scope": work.get("_reading_scope") or "OpenAlex 摘要和元数据；未核读全文",
        "discovery_type": discovery_type(work),
        "journal_metrics": metrics_for(work),
        "jcr": metrics_for(work).get("jcr"),
        "cas": metrics_for(work).get("cas"),
        "summary": work.get("_summary") or {},
        "summary_evidence": work.get("_summary_evidence") or {},
        "format_version": 2,
    }


def discovery_type(work: dict[str, Any]) -> str:
    if work.get("_discovery_type"):
        return work["_discovery_type"]
    date = work.get("publication_date") or ""
    today = datetime.now(timezone(timedelta(hours=8))).date()
    return "近30天发表" if (today - timedelta(days=30)).isoformat() <= date <= today.isoformat() else "历史未收录补充"


def work_from_record(paper: dict, local_path: str | None = None) -> dict:
    inverted = {}
    for position, word in enumerate((paper.get("abstract") or "").split()):
        inverted.setdefault(word, []).append(position)
    return {
        "title": paper.get("title"), "id": paper.get("id"), "doi": paper.get("doi"),
        "publication_date": paper.get("publication_date"), "abstract_inverted_index": inverted,
        "primary_location": {"source": {"display_name": paper.get("journal"), "type": paper.get("source_type") or "journal"}},
        "_authors": paper.get("authors"), "_summary": paper.get("summary") or {},
        "_metrics": paper.get("journal_metrics") or {}, "_reading_scope": paper.get("reading_scope"),
        "_categories": paper.get("categories"), "_direction": paper.get("direction"),
        "_relevance": paper.get("relevance"), "_relevance_reason": paper.get("relevance_reason"),
        "_local_pdf_path": local_path, "_discovery_type": paper.get("discovery_type"),
    }


def render_markdown(papers: list[dict[str, Any]], report_date: str | None = None) -> str:
    today = report_date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    mention = os.getenv("DIGEST_MENTION", "@hello1573")
    lines = [
        mention,
        "",
        f"# 稀疏地形重建文章日报｜{today}",
        "",
        "本期按中英文题名、研究问题、核心思路、创新点、实验结果和结论整理；研究问题尽量完整翻译摘要，各关键部分另附通俗解释。阅读范围逐篇标注。期刊指标注明数据年份及分区版本；来源证据保留在内部记录。",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        title = markdown_text(paper.get("title") or "未命名文章")
        date = markdown_text(paper.get("publication_date") or "日期未知")
        authors = markdown_text(authors_text(paper))
        journal = markdown_text(journal_name(paper))
        sentences = abstract_sentences(paper)
        relevance, relevance_reason = relevance_summary(paper)
        scope = paper.get("_reading_scope") or ("OpenAlex 摘要经模型辅助整理，未核读全文" if paper.get("_summary") else "OpenAlex 摘要与元数据，未核读全文")
        lines.extend(
            [
                f"## {index}. {title}",
                "",
                "**中文译名：** " + note_section(paper, "title_zh", "自动翻译不可用；保留英文原题，不填未经核验译名。"),
                "",
                "### 期刊与论文基本信息",
                f"**作者：** {authors}；**发表日期：** {date}；**期刊/来源：** {journal}。",
                "",
                f"**期刊等级：** {markdown_text(journal_metrics.display(metrics_for(paper), ((paper.get('primary_location') or {}).get('source') or {}).get('type')))}。**阅读范围：** {scope}。",
                "",
                f"**收录说明：** {discovery_type(paper)}。**方向与交叉分类：** {markdown_text(task_label(paper))}；{'、'.join(markdown_text(label) for label in categories(paper))}。**相关性：** {relevance}；{markdown_text(relevance_reason)}。",
                "",
                "### 研究问题",
                note_section(paper, "background", ("当前中文整理接口不可用，以下保留完整原摘要，不冒充中文翻译：\n\n" + abstract_text(paper)) if abstract_text(paper) else "摘要缺失，不能据题名补造研究背景和目标。"),
                "",
                "**大白话理解：** " + note_section(paper, "background_plain", "中文解释暂未生成，需先取得摘要翻译或可阅读全文。"),
                "",
                "### 核心思路",
                note_section(paper, "method", "中文方法梳理暂未生成；不把关键词匹配当作作者的完整技术路线。需阅读全文核实摘要未说明的模块和训练流程。"),
                "",
                "**大白话理解：** " + note_section(paper, "method_plain", "目前没有足够已整理证据来解释完整步骤。"),
                "",
                "### 创新点",
            ]
        )
        innovations = (paper.get("_summary") or {}).get("innovations") or []
        if innovations:
            lines.extend(["**核心创新概括：" + note_section(paper, "innovation_overview", innovations[0]["claim"]) + "**", ""])
            for number, entry in enumerate(innovations, 1):
                lines.extend([f"{number}. **{markdown_text(entry['claim'])}**", "", markdown_text(entry['analysis']), ""])
        else:
            lines.extend(["摘要未明确说明相对现有工作的创新差异，或中文创新提炼未通过证据校验；不凑条目、不认定首创。", ""])
        lines.extend([
                "**大白话概括：** " + note_section(paper, "innovation_plain", "现有信息不能支持完整创新分析。"),
                "",
                "### 实验结果",
                note_section(paper, "results", abstract_result(sentences)),
                "",
                "### 结论",
                note_section(paper, "conclusion", abstract_conclusion(sentences)),
                "",
                "**一句话理解（选题定位）：** " + note_section(paper, "plain", f"这篇论文围绕{task_label(paper)}展开；具体效果以原文数据为准。"),
                "",
                "### 本地全文",
                "**本地路径：** " + (f"`{paper['_local_pdf_path']}`" if paper.get("_local_pdf_path") else "未下载。计划保存位置：`" + "E:\\论文\\知识点概述\\日常文献查询记录\\论文\\" + today + "\\" + safe_filename(paper.get("title") or "", paper.get("id") or "") + "`（由本机任务尝试获取，云端不确认文件存在）。"),
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
    parser.add_argument("--known", default=str(Path(__file__).with_name("known_papers.json")))
    parser.add_argument("--catalog-index", default=str(Path(__file__).with_name("local_catalog_keys.json")))
    parser.add_argument("--count-output", default="digest_count.txt")
    parser.add_argument("--report-json", help="Write the same selected papers as a local-sync manifest")
    parser.add_argument("--allow-metadata-only", action="store_true", help="Explicit diagnostic mode; do not publish as a completed Chinese digest")
    args = parser.parse_args()
    if not os.getenv("SUMMARY_API_KEY") and not args.allow_metadata_only:
        raise RuntimeError("Missing SUMMARY_API_KEY. Configure a dedicated repository Secret before publishing Chinese reading notes.")
    seen = load_seen(args.state)
    known = load_known(args.known)
    known.update(load_catalog_index(args.catalog_index))
    papers = collect_papers(seen | known)
    for paper in papers:
        paper["_summary"] = summarize_from_abstract(paper)
        if not summary_complete(paper["_summary"]) and not args.allow_metadata_only:
            raise RuntimeError("Chinese summary missing or failed evidence checks; no digest or sent-history update was published.")
        source = ((paper.get("primary_location") or {}).get("source") or {})
        paper["_metrics"] = journal_metrics.lookup(source.get("display_name"), source.get("type"))
        if source.get("type") == "journal" and journal_metrics.needs_refresh(paper["_metrics"]):
            try:
                paper["_metrics"] = journal_metrics.merge_metrics(
                    paper["_metrics"], journal_metrics.discover_journal(source.get("display_name"))
                )
            except requests.RequestException:
                paper["_metrics"]["failure"] = "本次期刊查询网络失败；未补造指标"
    content = render_markdown(papers)
    if args.report_json:
        report = {
            "schema_version": 1,
            "date": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"),
            "papers": [report_record(paper) for paper in papers],
        }
        with open(args.report_json, "w", encoding="utf-8") as target:
            json.dump(report, target, ensure_ascii=False, indent=2)
            target.write("\n")
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
