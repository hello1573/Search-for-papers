"""Evidence-backed journal metrics. Never infer a quartile from CiteScore."""

import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from lxml import html as html_tree


REGISTRY = Path(__file__).with_name("journal_metrics.json")
SEARCH_URL = "https://www.letpub.com.cn/index.php"


def normalize(value):
    return re.sub(r"[^\w]+", "", (value or "").casefold())


MDPI_JOURNALS = {
    normalize(name): slug for name, slug in (
        ("Remote Sensing", "remotesensing"), ("Electronics", "electronics"),
        ("Sensors", "sensors"), ("Forests", "forests"), ("Drones", "drones"),
        ("Sustainability", "sustainability"), ("Aerospace", "aerospace"),
        ("Journal of Imaging", "jimaging"),
        ("ISPRS International Journal of Geo-Information", "ijgi"),
    )
}


def fetch_page(session, url):
    response = session.get(url, timeout=25)
    response.raise_for_status()
    response.encoding = "utf-8"
    return visible_page(response.text)


def publisher_metrics(name, session=None):
    slug = MDPI_JOURNALS.get(normalize(name))
    if not slug:
        return {}
    url = "https://www.mdpi.com/journal/" + slug
    page = fetch_page(session or requests.Session(), url)
    text = re.sub(r"\s+", " ", page.text_content())
    result = {"sources": [url], "publisher_checked_at": date.today().isoformat()}
    factor = re.search(r"(?<!Year )Impact Factor:\s*(\d+(?:\.\d+)?)\s*\((20\d{2})\)", text)
    if factor:
        result.update(if_value=float(factor.group(1)), if_year=int(factor.group(2)),
                      if_release_year=int(factor.group(2)) + 1, if_year_basis="出版方明确标注指标年度")
    rank = re.search(r"Journal Rank:\s*JCR\s*[-–]\s*(Q[1-4])\s*\(([^)]+)\)", text)
    if rank:
        result.update(jcr=rank.group(1), jcr_subject=rank.group(2),
                      jcr_year_label="出版方当前显示", jcr_basis="出版方所列学科；不声称覆盖全部学科")
    if "SCIE (Web of Science)" in text:
        result["indexing"] = "SCIE"
    elif "ESCI (Web of Science)" in text:
        result["indexing"] = "ESCI"
    stats_url = url + "/stats"
    try:
        stats = fetch_page(session or requests.Session(), stats_url).text_content()
        section = stats.split("JCR category rank", 1)[-1].split("CiteScore category rank", 1)[0]
        subjects = re.findall(r"(Q[1-4]):\s*([^\n]+)", section)
        if subjects:
            result.update(jcr_subjects=[{"quartile": q, "subject": s.strip()} for q, s in subjects],
                          jcr_year_label="出版方当前显示；页面未单列分区年度",
                          jcr_basis="出版方统计页全部JCR学科；不使用CiteScore分区")
            result["sources"].append(stats_url)
    except requests.RequestException:
        pass
    return result


def discover_journal(name, session=None):
    """Read public search/detail cells, not gated metrics or scripts."""
    session = session or requests.Session()
    params = {"page": "journalapp", "view": "search", "searchname": name}
    search_url = SEARCH_URL + "?" + urlencode(params)
    page = fetch_page(session, search_url)
    target = None
    visited = set()
    for _ in range(20):
        for row in page.xpath("//tr"):
            cells = row.xpath("./td | ./th")
            if len(cells) < 7:
                continue
            for link in cells[1].xpath(".//a"):
                if normalize(link.text_content()) == normalize(name):
                    target = (cells, urljoin(SEARCH_URL, link.get("href", "")))
                    break
            if target:
                break
        if target:
            break
        following = [a for a in page.xpath("//a[@href]") if a.text_content().strip() == "下一页"]
        if not following:
            break
        next_url = urljoin(SEARCH_URL, following[0].get("href"))
        if next_url in visited:
            break
        visited.add(next_url)
        page = fetch_page(session, next_url)
    if not target:
        result = {"journal": name, "checked_at": date.today().isoformat(), "failure": "公开期刊查询未返回同名记录", "sources": [search_url]}
        try:
            result = merge_metrics(result, publisher_metrics(name, session))
        except requests.RequestException:
            pass
        return result
    cells, detail_url = target
    result = {"journal": name, "issn": cells[0].text_content().strip(), "checked_at": date.today().isoformat(),
              "sources": [search_url, detail_url], "provenance": "LetPub公开汇总；非JCR或中科院官方直接查询"}
    index = " ".join(re.findall(r"\b(?:SCI|SCIE|ESCI|SSCI|AHCI)\b", " ".join(c.text_content() for c in cells[2:])))
    if "SCIE" in index:
        result["indexing"] = "SCIE"
    elif "ESCI" in index:
        result["indexing"] = "ESCI"
    elif "SSCI" in index:
        result["indexing"] = "SSCI"
    elif "SCI" in index:
        result["indexing"] = "SCI"
    # Search-page IF is visible. Do not read gated hidden script values.
    found = re.search(r"\bIF:\s*(\d+(?:\.\d+)?)", " ".join(c.text_content() for c in cells))
    released = re.search(r"(20\d{2})年6月最新影响因子数据已更新", page.text_content())
    if found and released:
        result.update(if_value=float(found.group(1)), if_year=int(released.group(1)) - 1,
                      if_release_year=int(released.group(1)), if_year_basis="页面6月更新年份及本站上一年度IF口径")
    detail = fetch_page(session, detail_url)
    for row in detail.xpath("//tr"):
        direct = row.xpath("./td | ./th")
        if len(direct) != 2:
            continue
        label, value = direct[0].text_content(), direct[1].text_content()
        if "2025年3月升级版" in label:
            for nested in direct[1].xpath("./table/tr | ./table/tbody/tr"):
                subcells = nested.xpath("./td")
                if not subcells:
                    continue
                major = re.search(r"^\s*([^\d]+?)\s*([1-4])区\s*$", subcells[0].text_content())
                if major:
                    result.update(cas=f"{major.group(1).strip()}大类{major.group(2)}区", cas_year=2025)
                    break
        if "WOS期刊JCR分区" in label:
            if "注册" in value or "登录" in value:
                result["jcr_failure"] = "公开查询页的JCR字段要求登录；未读取受限数据"
            else:
                quartiles = re.findall(r"\bQ[1-4]\b", value)
                if quartiles:
                    result["jcr"] = " / ".join(dict.fromkeys(quartiles))
                    result["jcr_scope"] = value
                    edition = re.search(r"(20\d{2})-(20\d{2})", label)
                    if edition:
                        result["jcr_year"] = int(edition.group(1))
    try:
        official = publisher_metrics(name, session)
        result = merge_metrics(result, official)
    except requests.RequestException:
        pass
    return result


def merge_metrics(old, fresh):
    result = {**old, **{k: v for k, v in fresh.items() if v is not None}}
    result["sources"] = list(dict.fromkeys((old.get("sources") or []) + (fresh.get("sources") or [])))
    if fresh.get("failure") and old.get("if_value") is not None:
        result["refresh_failure"] = fresh["failure"]
        result.pop("failure", None)
    elif not fresh.get("failure") and any(fresh.get(k) is not None for k in ("if_value", "cas", "jcr", "jcr_subjects")):
        result.pop("failure", None)
        result.pop("refresh_failure", None)
    if result.get("jcr") or result.get("jcr_subjects"):
        result.pop("jcr_failure", None)
    return result


def visible_page(text):
    page = html_tree.fromstring(text)
    for node in page.xpath("//script | //style | //*[@hidden] | //*[@style]"):
        hidden = re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", node.get("style", ""), re.I)
        if node.tag in {"script", "style"} or node.get("hidden") is not None or hidden:
            node.drop_tree()
    return page


def load_registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}


def lookup(name, source_type=None):
    if source_type and source_type != "journal":
        return {"not_applicable": True}
    for entry in load_registry().values():
        if normalize(entry.get("journal")) == normalize(name):
            return entry
    return {}


def needs_refresh(entry, today=None):
    checked = entry.get("checked_at")
    today = today or date.today().isoformat()
    complete = all(entry.get(k) is not None for k in ("indexing", "if_value", "if_year", "cas"))
    return checked != today or not complete or not (entry.get("jcr") or entry.get("jcr_subjects"))


def jcr_display(entry):
    if entry.get("jcr_subjects"):
        values = "；".join(f"{s['quartile']}（{s['subject']}）" for s in entry['jcr_subjects'])
        return values + "；" + str(entry.get("jcr_year") or entry.get("jcr_year_label") or "来源未标年份")
    if entry.get("jcr"):
        scope = entry.get("jcr_subject") or entry.get("jcr_scope") or ""
        edition = entry.get('jcr_year') or entry.get('jcr_year_label') or '来源未标年份'
        return f"{entry['jcr']}（{edition}；{scope}）"
    return entry.get("jcr_failure", "尚无可验证分区来源")


def display(entry, source_type=None):
    if entry.get("not_applicable") or (source_type and source_type != "journal"):
        return "非期刊成果；JCR、中科院期刊分区和期刊IF不适用"
    values = [entry.get("indexing") or "收录状态：未取得可验证记录"]
    values.append("JCR " + jcr_display(entry))
    if entry.get("cas"):
        values.append(f"中科院{entry['cas']}（{entry['cas_year']}版）")
    else:
        values.append("中科院2025版：公开记录未提供该版本的分区值")
    if entry.get("if_value") is not None:
        values.append(f"IF={entry['if_value']:g}（{entry['if_year']}年度；{entry['if_release_year']}发布）")
    else:
        values.append("IF：未取得有明确指标年份的数值")
    return "；".join(values)


def enrich(names, registry_path=REGISTRY):
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    for name in dict.fromkeys(names):
        if not name:
            continue
        try:
            # Search cookies can retain a previous query; isolate each journal.
            fresh = discover_journal(name)
            if fresh.get("failure"):
                time.sleep(2)
                fresh = discover_journal(name)
            old = registry.get(normalize(name), {})
            # A public-source refresh must not remove already verified official values.
            registry[normalize(name)] = merge_metrics(old, fresh)
            print(json.dumps(registry[normalize(name)], ensure_ascii=False), flush=True)
        except (requests.RequestException, ValueError) as exc:
            print(f"Journal lookup failed: {name}: {type(exc).__name__}", flush=True)
        time.sleep(5)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    enrich([p.get("journal") for p in ledger["records"] if p.get("publication_type") == "journal-article"])
