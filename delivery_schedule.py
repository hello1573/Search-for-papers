"""Keep early preparation from publishing before 10:00 Beijing time."""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING = timezone(timedelta(hours=8))


def seconds_until_delivery(report_date: str, now: datetime) -> float:
    local = now.astimezone(BEIJING)
    if report_date != local.date().isoformat():
        raise ValueError("Report date is not today in Beijing; refusing a stale notification.")
    delivery = local.replace(hour=10, minute=0, second=0, microsecond=0)
    return max(0.0, (delivery - local).total_seconds())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    delay = seconds_until_delivery(report["date"], datetime.now(BEIJING))
    if delay > 3600:
        raise RuntimeError("Preparation began too early; refusing to occupy a runner for more than an hour.")
    if delay:
        print(f"Prepared. Waiting {delay:.0f}s until 10:00 Beijing time.", flush=True)
        time.sleep(delay)
    seconds_until_delivery(report["date"], datetime.now(BEIJING))


if __name__ == "__main__":
    main()
