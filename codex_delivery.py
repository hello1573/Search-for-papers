"""Validate Codex-authored notes and publish them without an AI API key."""
import argparse
import copy
import ipaddress
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import requests

from delivery_schedule import BEIJING, seconds_until_delivery
from paper_digest import (
    NOTE_FIELDS, hashed_keys, load_catalog_index, load_known, load_seen, paper_keys,
    render_markdown, request_with_retry, save_seen, summary_complete, work_from_record,
)


ISSUE_TITLE = "[论文日报] 稀疏地形重建文章日报"
FIELDS = (
    "id", "title", "title_zh", "authors", "publication_date", "journal", "source_type",
    "doi", "categories", "direction", "relevance", "relevance_reason", "reading_scope",
    "discovery_type", "open_access_pdf_urls", "summary",
)
METRIC_FIELDS = (
    "journal", "issn", "checked_at", "indexing", "jcr", "jcr_subject", "jcr_subjects",
    "jcr_year", "jcr_year_label", "jcr_basis", "jcr_failure", "cas", "cas_year",
    "if_value", "if_year", "if_release_year", "if_year_basis", "not_applicable", "failure",
)


def public_url(value):
    parsed = urlparse(str(value))
    host = parsed.hostname or ""
    try:
        if not ipaddress.ip_address(host).is_global:
            return False
    except ValueError:
        pass
    private_parameter = any(
        re.search(r"token|secret|password|credential|signature|api.?key|^key$", key, re.I)
        for key, _ in parse_qsl(parsed.query)
    )
    return parsed.scheme == "https" and "." in host and not parsed.username and not parsed.password and not private_parameter and not host.endswith((".local", ".internal", ".localhost"))


def validate_report(report, expected_date):
    if report.get("schema_version") != 1 or report.get("producer") != "codex":
        raise ValueError("Expected a schema-version-1 Codex-authored report")
    if report.get("date") != expected_date:
        raise ValueError("Prepared report is not for the current Beijing date")
    papers = report.get("papers")
    if not isinstance(papers, list) or len(papers) > 8:
        raise ValueError("Expected at most eight verified papers, without padding")
    seen = set()
    for paper in papers:
        for field in ("title", "authors", "publication_date", "journal", "reading_scope", "discovery_type"):
            if not isinstance(paper.get(field), str) or not paper[field].strip():
                raise ValueError(f"Missing paper field: {field}")
        if paper.get("format_version") != 2 or not summary_complete(paper.get("summary") or {}):
            raise ValueError("Chinese notes are incomplete, untranslated or damaged")
        if paper.get("title_zh") != paper["summary"]["title_zh"]:
            raise ValueError("Chinese titles must agree in the record and reading notes")
        if not isinstance(paper.get("categories"), list) or not paper["categories"]:
            raise ValueError("Direction categories are required")
        if not all(isinstance(category, str) and category.strip() for category in paper["categories"]):
            raise ValueError("Categories must be names, not nested private metadata")
        if paper.get("source_verification_count", 0) < 2:
            raise ValueError("Two independently checked source types are required")
        for field, text in paper["summary"].items():
            if isinstance(text, str) and re.search(r"https?://|\bdoi\b", text, re.I):
                raise ValueError("Visible note sections must not contain web links or DOI")
        keys = paper_keys(work_from_record(paper))
        if keys & seen:
            raise ValueError("Duplicate paper in one report")
        seen.update(keys)
    markdown = render_markdown([work_from_record(paper) for paper in papers], expected_date)
    if len(markdown) > 60000:
        raise ValueError("Reading notes exceed the GitHub comment size budget")
    return markdown


def public_report(draft, expected_date):
    if draft.get("schema_version") != 1 or draft.get("date") != expected_date:
        raise ValueError("Local draft schema/date mismatch")
    records = draft.get("papers")
    if not isinstance(records, list):
        raise ValueError("Local draft must contain papers")
    papers = []
    for record in records:
        sources = record.get("verified_sources") or []
        kinds = {
            item.get("kind") for item in sources
            if isinstance(item, dict) and item.get("kind") in {"publisher", "crossref", "openalex", "preprint", "repository"}
            and public_url(item.get("url")) and item.get("checked_at") == expected_date
        }
        if len(kinds) < 2:
            raise ValueError("Keep at least two checked source types in the private local draft")
        paper = {field: copy.deepcopy(record[field]) for field in FIELDS if field in record}
        note = record.get("summary") or {}
        if not isinstance(note.get("innovations", []), list):
            raise ValueError("Innovations must be an array")
        paper["summary"] = {field: copy.deepcopy(note[field]) for field in NOTE_FIELDS if field in note}
        paper["summary"]["innovations"] = [
            {field: copy.deepcopy(entry[field]) for field in ("claim", "analysis") if field in entry}
            for entry in note.get("innovations", []) if isinstance(entry, dict)
        ]
        paper["title_zh"] = (paper.get("summary") or {}).get("title_zh")
        paper["journal_metrics"] = {
            field: copy.deepcopy(record.get("journal_metrics", {})[field])
            for field in METRIC_FIELDS if field in record.get("journal_metrics", {})
        }
        paper["source_verification_count"] = len(kinds)
        if "jcr_subjects" in paper["journal_metrics"]:
            paper["journal_metrics"]["jcr_subjects"] = [
                {field: copy.deepcopy(entry[field]) for field in ("quartile", "subject") if field in entry}
                for entry in paper["journal_metrics"]["jcr_subjects"] if isinstance(entry, dict)
            ]
        paper["format_version"] = 2
        paper["open_access_pdf_urls"] = [url for url in paper.get("open_access_pdf_urls", []) if public_url(url)]
        for field in ("id", "doi"):
            if paper.get(field) and not public_url(paper[field]):
                raise ValueError("Identifiers must be public HTTPS URLs without credentials")
        papers.append(paper)
    report = {"schema_version": 1, "producer": "codex", "date": expected_date, "papers": papers}
    validate_report(report, expected_date)
    return report


class IssuePublisher:
    def __init__(self, session, repository, issue_number=1):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository identifier")
        self.session = session
        self.url = f"https://api.github.com/repos/{repository}/issues/{issue_number}"

    def get(self, url, **kwargs):
        return request_with_retry(lambda: self.session.get(url, timeout=30, **kwargs)).json()

    def existing(self, content, day):
        heading = f"# 稀疏地形重建文章日报｜{day}"
        for page in range(1, 101):
            comments = self.get(self.url + "/comments", params={"per_page": 100, "page": page})
            for comment in comments:
                body = comment.get("body") or ""
                if heading not in body.splitlines():
                    continue
                if body.replace("\r\n", "\n").strip() != content.strip():
                    raise ValueError("A different report was already published for this day; refusing another notification")
                return comment
            if len(comments) < 100:
                return None
        raise RuntimeError("Comment history exceeded the safe pagination limit")

    def publish(self, content, day):
        issue = self.get(self.url)
        if issue.get("title") != ISSUE_TITLE or issue.get("state") != "open":
            raise ValueError("Expected the user's open literature-digest issue")
        existing = self.existing(content, day)
        if existing:
            return existing
        # Never blindly retry POST: a timeout may occur after the notification was sent.
        try:
            response = self.session.post(self.url + "/comments", json={"body": content}, timeout=30)
            response.raise_for_status()
            publication = response.json()
            if not isinstance(publication.get("id"), int) or publication.get("body", "").strip() != content.strip():
                raise ValueError("GitHub did not confirm the expected comment")
            return publication
        except requests.RequestException:
            existing = self.existing(content, day)
            if existing:
                return existing
            raise


def validate_exclusions(report, root):
    excluded = load_seen(str(root / "seen_papers.json"))
    excluded |= load_known(str(root / "known_papers.json"))
    excluded |= load_catalog_index(str(root / "local_catalog_keys.json"))
    for paper in report["papers"]:
        keys = paper_keys(work_from_record(paper))
        if (keys | hashed_keys(keys)) & excluded:
            raise ValueError("Prepared notes include a previously collected or delivered paper")


def run(root, repository, dry_run=False, now=None):
    now = now or datetime.now(BEIJING)
    day = now.astimezone(BEIJING).date().isoformat()
    prepared = root / "reports" / "prepared" / f"{day}.json"
    archive = root / "reports" / "daily" / f"{day}.json"
    if archive.exists() and not dry_run:
        return "Today's report is already archived; no duplicate notification."
    if not prepared.exists():
        return "No Codex-authored report for today; no AI API call and no placeholder notification."
    report = json.loads(prepared.read_text(encoding="utf-8"))
    content = validate_report(report, day)
    validate_exclusions(report, root)
    if dry_run:
        summary_file = os.getenv("GITHUB_STEP_SUMMARY")
        if summary_file:
            with open(summary_file, "a", encoding="utf-8") as output:
                output.write(content)
        return f"Dry run: {len(report['papers'])} Chinese notes validated; no network publication or history update."
    delay = seconds_until_delivery(day, now)
    if delay > 3600:
        raise ValueError("Preparation started more than an hour before the publish window")
    if delay:
        print(f"Notes ready; waiting {delay:.0f}s until 10:00 Beijing.", flush=True)
        time.sleep(delay)
    seconds_until_delivery(day, datetime.now(BEIJING))
    papers = report["papers"]
    if papers:
        token = os.getenv("GH_TOKEN")
        if not token:
            raise RuntimeError("Missing temporary GitHub Actions token, not an AI API key")
        with requests.Session() as session:
            session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
            publication = IssuePublisher(session, repository).publish(content, day)
        report["github_publication"] = {key: publication[key] for key in ("id", "created_at") if key in publication}
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive.with_suffix(".md").write_text(content, encoding="utf-8")
    seen = load_seen(str(root / "seen_papers.json"))
    for paper in papers:
        seen.update(paper_keys(work_from_record(paper)))
    save_seen(str(root / "seen_papers.json"), seen)
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=root, check=True)
    subprocess.run(["git", "add", "--", "seen_papers.json", str(archive.relative_to(root)), str(archive.with_suffix(".md").relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", f"Archive Codex paper digest for {day}"], cwd=root, check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=root, check=True)
    return f"Archived {len(papers)} Codex notes; GitHub publication confirmed, downstream WeChat receipt is not confirmed."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", "hello1573/Search-for-papers"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(run(args.root, args.repository, args.dry_run))


if __name__ == "__main__":
    main()
