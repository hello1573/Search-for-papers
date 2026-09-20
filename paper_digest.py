import argparse
import html
import os
import time
from datetime import datetime, timezone
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


def search_openalex(session: requests.Session, query: str) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "filter": "from_publication_date:2023-01-01",
        "sort": "publication_date:desc",
        "per-page": 30,
    }
    for attempt in range(4):
        response = session.get(OPENALEX_URL, params=params, timeout=30)
        if response.status_code != 429:
            response.raise_for_status()
            return response.json().get("results", [])
        time.sleep(3 * (attempt + 1))
    response.raise_for_status()
    return response.json().get("results", [])


def collect_papers() -> list[dict[str, Any]]:
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

    papers: dict[str, dict[str, Any]] = {}
    for query in QUERIES:
        for rank, work in enumerate(search_openalex(session, query)):
            work_id = work.get("id")
            if not work_id or not work.get("title"):
                continue
            score = relevance_score(work) + max(0, 10 - rank // 5)
            current = papers.get(work_id)
            if current is None or score > current["_score"]:
                work["_score"] = score
                papers[work_id] = work

    ranked = sorted(
        papers.values(),
        key=lambda item: (item["_score"], item.get("publication_date") or ""),
        reverse=True,
    )
    return [paper for paper in ranked if paper["_score"] >= 8][:8]


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
    args = parser.parse_args()
    papers = collect_papers()
    content = render_markdown(papers)
    with open(args.output, "w", encoding="utf-8") as output:
        output.write(content)
    print(f"已生成 {len(papers)} 篇文章的日报：{args.output}")


if __name__ == "__main__":
    main()
