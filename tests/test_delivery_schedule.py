import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import delivery_schedule
import dispatch_daily


class DeliveryScheduleTests(unittest.TestCase):
    def test_early_preparation_waits_until_beijing_10(self):
        now = datetime(2026, 9, 27, 1, 30, tzinfo=timezone.utc)
        self.assertEqual(delivery_schedule.seconds_until_delivery("2026-09-27", now), 1800)

    def test_late_run_does_not_wait_another_day(self):
        now = datetime(2026, 9, 27, 7, 21, tzinfo=timezone.utc)
        self.assertEqual(delivery_schedule.seconds_until_delivery("2026-09-27", now), 0)

    def test_stale_report_cannot_be_sent(self):
        with self.assertRaises(ValueError):
            delivery_schedule.seconds_until_delivery("2026-09-26", datetime(2026, 9, 27, 2, tzinfo=timezone.utc))

    def test_trigger_does_not_change_working_tree_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            calls = []
            def mock_git(repo, *args, **kwargs):
                calls.append(args)
                if "commit-tree" in args:
                    return "c" * 40
                if args[0] == "rev-parse" and "--verify" in args:
                    return None
                return "a" * 40
            with patch.object(dispatch_daily, "git", side_effect=mock_git):
                now = datetime(2026, 9, 27, 1, 30, tzinfo=timezone.utc)
                dispatch_daily.dispatch(root, root / "state", now)
                first_count = len(calls)
                self.assertIn("Already", dispatch_daily.dispatch(root, root / "state", now))
            self.assertEqual(len(calls), first_count)
            self.assertTrue(any("commit-tree" in call for call in calls))
            self.assertFalse(any(call[0] in ("checkout", "reset", "add", "commit", "switch") for call in calls))

    def test_dry_run_never_commits_pushes_or_records_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(dispatch_daily, "git", side_effect=[None, "a" * 40, None]) as git:
                dispatch_daily.dispatch(root, root / "state", datetime.now(timezone.utc), dry_run=True)
            self.assertEqual(git.call_count, 3)
            self.assertFalse((root / "state").exists())


if __name__ == "__main__":
    unittest.main()
