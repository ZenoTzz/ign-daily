#!/usr/bin/env python3
"""Publish the previous full week's learning report.

This script does not call an API. It only reads accumulated style evidence and
writes data/learning/weekly/{week}.json plus latest.json for the site.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
LEARNING_DIR = DATA_DIR / "learning"
WEEKLY_DIR = LEARNING_DIR / "weekly"
EVIDENCE_PATH = LEARNING_DIR / "style-evidence.json"


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def week_id_for_date(date_text: str) -> str:
    d = datetime.strptime(date_text, "%Y-%m-%d").date()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def previous_full_week_anchor() -> str:
    today = datetime.now(CST).date()
    previous_sunday = today - timedelta(days=today.weekday() + 1)
    return previous_sunday.strftime("%Y-%m-%d")


def week_dates_for(date_text: str) -> list[str]:
    d = datetime.strptime(date_text, "%Y-%m-%d").date()
    week_start = d - timedelta(days=d.weekday())
    return [(week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def build_report(evidence: dict[str, Any], anchor_date: str) -> dict[str, Any]:
    week_id = week_id_for_date(anchor_date)
    week_dates = week_dates_for(anchor_date)
    rules = evidence.get("rules", {}) if isinstance(evidence, dict) else {}
    candidates: list[dict[str, Any]] = []
    confirmed_rules: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for entry in rules.values():
        if not isinstance(entry, dict):
            continue
        days = set(str(d) for d in entry.get("days", []))
        if entry.get("status") == "ready_for_review":
            candidates.append(entry)
        elif entry.get("status") in ("confirmed_by_feedback", "confirmed"):
            confirmed_rules.append(entry)
        elif days.intersection(week_dates) and entry.get("status") == "observed":
            observations.append(entry)
    candidates.sort(key=lambda r: (
        0 if r.get("status") == "ready_for_review" else 1,
        -int(r.get("days_seen", 0) or 0),
        -int(r.get("articles_seen", 0) or 0),
        str(r.get("title") or ""),
    ))
    return {
        "week_id": week_id,
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "published_by": "weekly_learning_report",
        "range": {"start": week_dates[0], "end": week_dates[-1]},
        "summary": {
            "candidate_count": len(candidates),
            "ready_for_review": sum(1 for r in candidates if r.get("status") == "ready_for_review"),
            "confirmed_by_feedback": len(confirmed_rules),
            "pending": sum(1 for r in candidates if r.get("status") == "pending"),
            "observing": len(observations),
        },
        "candidates": candidates[:40],
        "confirmed_rules": confirmed_rules[:40],
        "observations": observations[:12],
        "instructions_for_user": [
            "Adopt: this rule can enter STYLE_PROFILE.md.",
            "Reject: this is not your preference and should not be proposed again.",
            "Limit: this rule only applies to a specific article type or context.",
            "Hold: keep observing; do not promote it into the formal style profile yet.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Any date inside the week to publish, YYYY-MM-DD.")
    args = parser.parse_args()
    anchor_date = args.date or previous_full_week_anchor()
    evidence = load_json(EVIDENCE_PATH, {"version": 1, "rules": {}}) or {"version": 1, "rules": {}}
    report = build_report(evidence, anchor_date)
    write_json(WEEKLY_DIR / f"{report['week_id']}.json", report)
    write_json(WEEKLY_DIR / "latest.json", report)
    index = load_json(WEEKLY_DIR / "_index.json", {"weeks": []}) or {"weeks": []}
    weeks = index.setdefault("weeks", [])
    if report["week_id"] not in weeks:
        weeks.append(report["week_id"])
    index["weeks"] = sorted(str(w) for w in weeks)
    index["latest"] = report["week_id"]
    index["latest_published_at"] = report["generated_at"]
    write_json(WEEKLY_DIR / "_index.json", index)
    print(
        "WEEKLY_LEARNING_REPORT_PUBLISHED: "
        f"{report['week_id']} {report['range']['start']}..{report['range']['end']} "
        f"candidates={report['summary']['candidate_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
