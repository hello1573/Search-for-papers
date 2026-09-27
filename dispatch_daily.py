"""Trigger GitHub using Git Credential Manager without handling API tokens."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING = timezone(timedelta(hours=8))
SIGNAL_BRANCH = "codex/daily-digest-dispatch"


def git(repo, *args, input_text=None, optional=False):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    tls_options = ["-c", "http.sslBackend=schannel"] if os.name == "nt" else []
    result = subprocess.run(
        ["git", *tls_options, "-c", "http.connectTimeout=15", "-c", "http.lowSpeedLimit=100", "-c", "http.lowSpeedTime=30", *args],
        cwd=repo, env=env, input=input_text, text=True, encoding="utf-8", capture_output=True, timeout=90,
    )
    if result.returncode and not optional:
        raise RuntimeError(f"Git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip() if not result.returncode else None


def dispatch(repo: Path, state_root: Path, now: datetime, dry_run=False) -> str:
    today = now.astimezone(BEIJING).date().isoformat()
    state_file = state_root / "daily_dispatch.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if state.get("date") == today:
            return "Already triggered today; no duplicate request."
    git(repo, "fetch", "origin")
    main = git(repo, "rev-parse", "refs/remotes/origin/main")
    parent = git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{SIGNAL_BRANCH}", optional=True)
    message = f"Request paper digest {today}"
    if parent and git(repo, "show", "-s", "--format=%s", parent) == message:
        return "Remote already contains today's request; no duplicate push."
    if dry_run:
        return f"Dry run: main {main[:12]} is available; no commit, push or delivery."
    tree = git(repo, "rev-parse", f"{main}^{{tree}}")
    commit = git(
        repo, "-c", "user.name=paper-digest-scheduler", "-c", "user.email=paper-digest-scheduler@users.noreply.github.com",
        "commit-tree", tree, "-p", parent or main, input_text=message + "\n",
    )
    git(repo, "push", "origin", f"{commit}:refs/heads/{SIGNAL_BRANCH}")
    state_root.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps({"date": today, "commit": commit, "requested_at": now.isoformat()}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(state_file)
    return "Trigger pushed to GitHub. Workflow execution and phone delivery still need verification."


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    args = parser.parse_args()
    now = datetime.now(BEIJING)
    if args.scheduled and (now.hour, now.minute) < (9, 30):
        print("Before 09:30 Beijing; leaving today's dispatch for the daily trigger.")
        return
    print(dispatch(args.repo, args.repo / "local-state", now, args.dry_run))


if __name__ == "__main__":
    main()
