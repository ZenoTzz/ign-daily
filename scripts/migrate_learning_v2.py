#!/usr/bin/env python3
"""Archive unsafe v1 candidates and initialize the v2 evidence pool."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone

from common_paths import DATA_DIR

CST = timezone(timedelta(hours=8))
LEARNING = DATA_DIR / "learning"
EVIDENCE = LEARNING / "style-evidence.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    data = json.loads(EVIDENCE.read_text(encoding="utf-8-sig")) if EVIDENCE.exists() else {"version": 1, "rules": {}}
    rules = data.get("rules") or {}
    keep = {}
    quarantine = []
    for rid, rule in rules.items():
        if not isinstance(rule, dict):
            continue
        explicitly_confirmed = rule.get("status") in {"confirmed", "confirmed_by_feedback"} and bool(rule.get("feedback"))
        if rule.get("type") == "dictionary_candidate" and not explicitly_confirmed:
            quarantined = dict(rule)
            quarantined["quarantine_reason"] = "legacy_v1_unreviewed_dictionary_candidate"
            quarantine.append(quarantined)
        else:
            keep[rid] = rule
    print(f"LEARNING_V2_MIGRATION: keep={len(keep)} quarantine={len(quarantine)} apply={args.apply}")
    if not args.apply:
        return 0
    stamp = datetime.now(CST).strftime("%Y%m%d-%H%M%S")
    archive = LEARNING / "archive" / f"v1-{stamp}"
    archive.mkdir(parents=True, exist_ok=True)
    if EVIDENCE.exists():
        shutil.copy2(EVIDENCE, archive / "style-evidence.json")
    (archive / "quarantined-candidates.json").write_text(
        json.dumps({"count": len(quarantine), "candidates": quarantine}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    data["version"] = 2
    data["migration"] = {"at": datetime.now(CST).isoformat(timespec="seconds"), "quarantined": len(quarantine), "archive": str(archive.relative_to(DATA_DIR))}
    data["rules"] = keep
    EVIDENCE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
