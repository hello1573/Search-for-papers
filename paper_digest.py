import html
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests


OPENALEX_URL = "https://api.openalex.org/works"
PUSHPLUS_URL = "https://www.pushplus.plus/send"
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


def render_html(papers: list[dict[str, Any]]) -> str:
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    items = []
    for index, paper in enumerate(papers, start=1):
        title = html.escape(paper.get("title") or "未命名文章")
        primary_location = paper.get("primary_location") or {}
        url = html.escape(
            paper.get("doi")
            or primary_location.get("landing_page_url")
            or paper.get("id")
            or "#",
            quote=True,
        )
        date = html.escape(paper.get("publication_date") or "日期未知")
        authors = html.escape(authors_text(paper))
        abstract = html.escape(abstract_excerpt(paper))
        items.append(
            f"<h3>{index}. <a href=\"{url}\">{title}</a></h3>"
            f"<p><b>作者：</b>{authors}<br><b>发布日期：</b>{date}</p>"
            f"<p>{abstract}</p>"
        )
    body = "".join(items) or "今天没有找到达到相关性阈值的文章。"
    return (
        "<div style='font-family:Arial,sans-serif;line-height:1.6'>"
        f"<h2>稀疏地形重建文章日报｜{today}</h2>"
        "<p>以下结果来自 OpenAlex，按与稀疏采样、DEM 修复、地形重建和高程补全的相关性筛选。</p>"
        f"{body}</div>"
    )


def send_pushplus(content: str, count: int) -> None:
    token = os.getenv("PUSHPLUS_TOKEN")
    if not token:
        raise RuntimeError("缺少 PUSHPLUS_TOKEN。请在 GitHub Secrets 中配置它。")
    title = f"稀疏地形重建日报（{count}篇）"
    response = requests.post(
        PUSHPLUS_URL,
        json={"token": token, "title": title, "content": content, "template": "html"},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") not in (200, "200"):
        raise RuntimeError(f"PushPlus 推送失败：{result}")


def main() -> None:
    papers = collect_papers()
    content = render_html(papers)
    send_pushplus(content, len(papers))
    print(f"已推送 {len(papers)} 篇文章。")


if __name__ == "__main__":
    main()
