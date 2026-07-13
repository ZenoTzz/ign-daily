#!/usr/bin/env python3
"""Publish a compact, immutable weekly learning snapshot."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio
from learning_weekly import (
    apply_lifecycle,
    build_active_rules,
    build_observation_pool,
    build_report,
    report_summary,
    write_json,
)


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
LEARNING_DIR = DATA_DIR / "learning"
WEEKLY_DIR = LEARNING_DIR / "weekly"
EVIDENCE_PATH = LEARNING_DIR / "style-evidence.json"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def previous_full_week_anchor() -> str:
    today = datetime.now(CST).date()
    previous_sunday = today - timedelta(days=today.weekday() + 1)
    return previous_sunday.isoformat()


def current_week_id() -> str:
    year, week, _ = datetime.now(CST).date().isocalendar()
    return f"{year}-W{week:02d}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Any date inside the week to publish, YYYY-MM-DD.")
    parser.add_argument("--force", action="store_true", help="Explicitly rebuild an existing historical snapshot.")
    args = parser.parse_args()
    anchor_date = args.date or previous_full_week_anchor()
    evidence = load_json(EVIDENCE_PATH, {"version": 1, "rules": {}}) or {"version": 1, "rules": {}}
    archived = apply_lifecycle(evidence, anchor_date)
    report = build_report(evidence, anchor_date, archived)
    report_path = WEEKLY_DIR / f"{report['week_id']}.json"

    # A closed week is an audit snapshot. Normal automation may update only the
    # current week; rebuilding history requires an explicit maintenance flag.
    if report_path.exists() and report["week_id"] != current_week_id() and not args.force:
        existing = load_json(report_path, {}) or {}
        print(f"WEEKLY_LEARNING_REPORT_IMMUTABLE: {existing.get('week_id', report['week_id'])}")
        return 0

    write_json(EVIDENCE_PATH, evidence)
    write_json(report_path, report)
    write_json(WEEKLY_DIR / "latest.json", report)
    write_json(LEARNING_DIR / "active-rules.json", build_active_rules(evidence))
    write_json(LEARNING_DIR / "observations.json", build_observation_pool(evidence))

    index = load_json(WEEKLY_DIR / "_index.json", {"weeks": []}) or {"weeks": []}
    weeks = sorted(set(str(item) for item in index.get("weeks", [])) | {report["week_id"]})
    summaries = index.get("summaries") if isinstance(index.get("summaries"), dict) else {}
    summaries[report["week_id"]] = report_summary(report)
    index.update({
        "schema_version": 3,
        "weeks": weeks,
        "latest": report["week_id"],
        "latest_published_at": report["generated_at"],
        "summaries": summaries,
    })
    write_json(WEEKLY_DIR / "_index.json", index)
    print(
        "WEEKLY_LEARNING_REPORT_PUBLISHED: "
        f"{report['week_id']} decisions={report['summary']['ready_for_review']} "
        f"conflicts={report['summary']['conflicts']} archived={report['summary']['archived_this_week']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
