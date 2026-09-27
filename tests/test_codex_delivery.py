import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import codex_delivery as delivery
import submit_codex_report as submitter
from paper_digest import NOTE_FIELDS


DAY = "2026-09-27"


def draft():
    return {"schema_version": 1, "date": DAY, "private_note": "PRIVATE-DRAFT", "papers": [{
        "id": "https://openalex.org/W123456789", "title": "Sparse DEM terrain reconstruction study",
        "authors": "Test Author", "publication_date": "2025-01-01", "journal": "Test Repository",
        "source_type": "repository", "categories": ["曲面建模、插值与隐式表示"], "direction": "稀疏高程插值",
        "relevance": "高", "reading_scope": "已读摘要，未核读全文", "discovery_type": "历史未收录补充",
        "summary": {**{field: "根据已核实摘要整理的中文内容。" for field in NOTE_FIELDS}, "innovations": []},
        "journal_metrics": {"not_applicable": True, "sources": ["PRIVATE-METRIC-EVIDENCE"]},
        "abstract": "PRIVATE-ABSTRACT", "summary_evidence": {"proof": "PRIVATE-EVIDENCE"},
        "verified_sources": [
            {"kind": "publisher", "url": "https://publisher.example/paper", "checked_at": DAY},
            {"kind": "openalex", "url": "https://openalex.org/W123456789", "checked_at": DAY},
        ],
        "open_access_pdf_urls": ["https://publisher.example/paper.pdf", "https://publisher.example/file?token=PRIVATE-TOKEN"],
    }]}


def seed_exclusions(root):
    for name, value in (("known_papers.json", {"papers": []}), ("seen_papers.json", []), ("local_catalog_keys.json", [])):
        (root / name).write_text(json.dumps(value), encoding="utf-8")


def response(value):
    result = Mock(status_code=200, headers={})
    result.json.return_value = value
    return result


class CodexDeliveryTests(unittest.TestCase):
    def test_public_url_rejects_internal_addresses_and_access_tokens(self):
        for url in ("https://127.0.0.1/private", "https://192.168.1.1/file.pdf", "https://test.local/file", "https://user:password@publisher.example/file", "https://publisher.example/file?api_key=test"):
            self.assertFalse(delivery.public_url(url), url)
        self.assertTrue(delivery.public_url("https://publisher.example/paper.pdf"))

    def test_private_sources_and_evidence_never_enter_public_report(self):
        data = draft()
        data["papers"][0]["summary"]["debug"] = "PRIVATE-DEBUG"
        data["papers"][0]["summary"]["innovations"] = [{"claim": "根据摘要说明中文贡献。", "analysis": "依据摘要解释中文方法改变。", "evidence": "PRIVATE-NESTED-EVIDENCE"}]
        data["papers"][0]["journal_metrics"]["jcr_subjects"] = [{"quartile": "Q1", "subject": "Test", "sources": ["PRIVATE-SUBJECT-SOURCE"]}]
        report = delivery.public_report(data, DAY)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("PRIVATE", serialized)
        self.assertNotIn("verified_sources", serialized)
        self.assertNotIn("abstract", serialized)
        self.assertEqual(report["papers"][0]["source_verification_count"], 2)
        self.assertEqual(report["papers"][0]["open_access_pdf_urls"], ["https://publisher.example/paper.pdf"])
        self.assertIn("中文内容", delivery.validate_report(report, DAY))

    def test_two_different_source_types_and_current_checks_are_required(self):
        data = draft()
        data["papers"][0]["verified_sources"][1]["kind"] = "publisher"
        with self.assertRaisesRegex(ValueError, "two checked"):
            delivery.public_report(data, DAY)
        data = draft()
        data["papers"][0]["verified_sources"][1]["checked_at"] = "2026-09-26"
        with self.assertRaises(ValueError):
            delivery.public_report(data, DAY)

    def test_duplicate_stale_and_untranslated_notes_are_rejected(self):
        report = delivery.public_report(draft(), DAY)
        with self.assertRaises(ValueError):
            delivery.validate_report(report, "2026-09-28")
        report["papers"].append(copy.deepcopy(report["papers"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            delivery.validate_report(report, DAY)
        data = draft()
        data["papers"][0]["summary"]["background"] = "This English abstract was not translated."
        with self.assertRaisesRegex(ValueError, "Chinese"):
            delivery.public_report(data, DAY)

    def test_no_prepared_report_does_not_call_api_or_touch_history(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(delivery.requests, "Session") as session:
            result = delivery.run(Path(folder), "hello1573/Search-for-papers")
            self.assertIn("No Codex-authored report", result)
            session.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_dry_run_works_without_any_ai_or_github_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed_exclusions(root)
            prepared = root / "reports" / "prepared"
            prepared.mkdir(parents=True)
            (prepared / f"{DAY}.json").write_text(json.dumps(delivery.public_report(draft(), DAY)), encoding="utf-8")
            with patch.dict(os.environ, {"SUMMARY_API_KEY": "", "GH_TOKEN": "", "GITHUB_STEP_SUMMARY": ""}):
                with patch.object(delivery.requests, "Session") as session, patch.object(delivery.subprocess, "run") as git:
                    result = delivery.run(root, "hello1573/Search-for-papers", True, datetime(2026, 9, 27, 1, 30, tzinfo=timezone.utc))
            self.assertIn("1 Chinese notes validated", result)
            session.assert_not_called()
            git.assert_not_called()
            self.assertEqual(json.loads((root / "seen_papers.json").read_text()), [])
            self.assertFalse((root / "reports" / "daily").exists())

    def test_sent_paper_is_rejected_before_publication(self):
        report = delivery.public_report(draft(), DAY)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed_exclusions(root)
            (root / "seen_papers.json").write_text(json.dumps([report["papers"][0]["id"]]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "previously"):
                delivery.validate_exclusions(report, root)

    def test_existing_comment_prevents_a_second_notification(self):
        content = delivery.validate_report(delivery.public_report(draft(), DAY), DAY)
        comment = {"id": 123, "body": content}
        session = Mock()
        session.get.side_effect = [response({"title": delivery.ISSUE_TITLE, "state": "open"}), response([comment])]
        self.assertEqual(delivery.IssuePublisher(session, "hello1573/Search-for-papers").publish(content, DAY), comment)
        session.post.assert_not_called()

    def test_timeout_after_post_is_reconciled_without_blind_retry(self):
        content = delivery.validate_report(delivery.public_report(draft(), DAY), DAY)
        comment = {"id": 123, "body": content}
        session = Mock()
        session.get.side_effect = [response({"title": delivery.ISSUE_TITLE, "state": "open"}), response([]), response([comment])]
        session.post.side_effect = requests.Timeout()
        self.assertEqual(delivery.IssuePublisher(session, "hello1573/Search-for-papers").publish(content, DAY), comment)
        self.assertEqual(session.post.call_count, 1)

    def test_new_comment_keeps_chinese_as_json_and_no_second_ai_call(self):
        content = delivery.validate_report(delivery.public_report(draft(), DAY), DAY)
        session = Mock()
        session.get.side_effect = [response({"title": delivery.ISSUE_TITLE, "state": "open"}), response([])]
        session.post.return_value = response({"id": 123, "body": content})
        delivery.IssuePublisher(session, "hello1573/Search-for-papers").publish(content, DAY)
        self.assertEqual(session.post.call_args.kwargs["json"]["body"], content)
        self.assertIn("稀疏地形", content)
        self.assertNotIn("lwjcode", session.post.call_args.args[0])

    def test_workflow_never_requests_an_ai_api_secret(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-paper-digest.yml").read_text(encoding="utf-8")
        self.assertNotIn("SUMMARY_API_KEY", workflow)
        self.assertNotIn("python paper_digest.py", workflow)
        self.assertIn("python codex_delivery.py", workflow)

    @unittest.skipUnless(shutil.which("git"), "Git is required for isolated-index integration test")
    def test_submission_preserves_user_files_head_and_staged_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            remote = root / "origin.git"
            repo = root / "repo"
            repo.mkdir()
            def git(*args, cwd=repo):
                return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()
            git("init", "--bare", str(remote), cwd=root)
            git("init", "-b", "main")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            seed_exclusions(repo)
            (repo / "work.txt").write_text("Original user work", encoding="utf-8")
            git("add", ".")
            git("commit", "-m", "Initial main")
            git("remote", "add", "origin", str(remote))
            git("push", "origin", "main")
            head = git("rev-parse", "HEAD")
            (repo / "work.txt").write_text("User staged edit", encoding="utf-8")
            git("add", "work.txt")
            index_before = (repo / ".git" / "index").read_bytes()
            internal = repo / "local-state"
            internal.mkdir()
            draft_file = internal / "draft.json"
            draft_file.write_text(json.dumps(draft(), ensure_ascii=False), encoding="utf-8")
            result = submitter.submit(repo, draft_file, now=datetime(2026, 9, 27, 2, tzinfo=timezone.utc))
            self.assertIn("submitted", result)
            self.assertEqual(git("rev-parse", "HEAD"), head)
            self.assertEqual((repo / ".git" / "index").read_bytes(), index_before)
            self.assertEqual((repo / "work.txt").read_text(), "User staged edit")
            git("fetch", "origin", "main")
            payload = git("show", f"origin/main:reports/prepared/{DAY}.json")
            self.assertNotIn("PRIVATE", payload)
            self.assertEqual(git("show", "origin/main:work.txt"), "Original user work")
            self.assertEqual(git("diff", "--name-only", head, "origin/main"), f"reports/prepared/{DAY}.json")
            self.assertIn("already submitted", submitter.submit(repo, draft_file, now=datetime(2026, 9, 27, 2, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
