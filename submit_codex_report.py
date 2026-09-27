"""Submit only a sanitized daily report; never commit the user's working files."""
import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path

from codex_delivery import public_report, validate_exclusions
from delivery_schedule import BEIJING
from dispatch_daily import git


def submit(repo, draft_path, dry_run=False, now=None):
    day = (now or datetime.now(BEIJING)).astimezone(BEIJING).date().isoformat()
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    report = public_report(draft, day)
    validate_exclusions(report, repo)
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if dry_run:
        return f"Validated {len(report['papers'])} Codex notes; private sources and evidence stripped. No push."
    git(repo, "fetch", "origin", "main")
    base = git(repo, "rev-parse", "refs/remotes/origin/main")
    relative = f"reports/prepared/{day}.json"
    archived = git(repo, "show", f"{base}:reports/daily/{day}.json", optional=True)
    if archived is not None:
        return "Today's digest is already archived; no new submission."
    previous = git(repo, "show", f"{base}:{relative}", optional=True)
    if previous is not None:
        if json.loads(previous) == report:
            return "The same Codex report is already submitted; no duplicate push."
        raise ValueError("A different draft for today is already submitted; explicit revision is required")
    internal = repo / "local-state"
    internal.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="submit-", dir=internal) as folder:
        index_env = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
        git(repo, "read-tree", base, extra_env=index_env)
        blob = git(repo, "hash-object", "-w", "--stdin", input_text=content)
        git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{relative}", extra_env=index_env)
        tree = git(repo, "write-tree", extra_env=index_env)
    commit = git(repo, "-c", "user.name=paper-digest-scheduler", "-c", "user.email=paper-digest-scheduler@users.noreply.github.com", "commit-tree", tree, "-p", base, input_text=f"Submit Codex paper digest {day}\n")
    git(repo, "push", "origin", f"{commit}:refs/heads/main")
    return "Codex notes submitted. GitHub workflow execution and phone receipt still need verification."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(submit(args.repo, args.draft, args.dry_run))


if __name__ == "__main__":
    main()
