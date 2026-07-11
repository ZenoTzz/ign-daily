#!/usr/bin/env python3
"""Apply audited Codex semantic decisions to the evidence pool."""
from __future__ import annotations

import json
from pathlib import Path

from common_paths import DATA_DIR
from learning_quality import promotion_status

LEARNING = DATA_DIR / "learning"
EVIDENCE = LEARNING / "style-evidence.json"
RESULTS = LEARNING / "semantic-review-results.json"


def main() -> int:
    if not RESULTS.exists():
        print("CODEX_REVIEW_SKIP: no semantic-review-results.json")
        return 0
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8-sig"))
    results = json.loads(RESULTS.read_text(encoding="utf-8-sig"))
    rules = evidence.get("rules") or {}
    changed = 0
    for result in results.get("results", []):
        rid = str(result.get("id") or "")
        entry = rules.get(rid)
        if not isinstance(entry, dict):
            continue
        decision = str(result.get("decision") or "observe")
        if decision not in {"approve", "reject", "observe", "one_off", "fact_correction"}:
            continue
        entry["semantic_review"] = "approved" if decision == "approve" else ("rejected" if decision == "reject" else decision)
        entry["semantic_rationale"] = str(result.get("rationale") or "")
        entry["counterexamples"] = result.get("counterexamples") if isinstance(result.get("counterexamples"), list) else []
        entry["misuse_risk"] = str(result.get("misuse_risk") or "")
        if result.get("refined_rule"):
            entry["rule"] = str(result["refined_rule"])
        if result.get("scope"):
            entry["scope"] = str(result["scope"])
        entry["status"] = promotion_status(
            days_seen=int(entry.get("days_seen", 0) or 0),
            articles_seen=int(entry.get("articles_seen", 0) or 0),
            contradictions=int(entry.get("contradictions", 0) or 0),
            semantic_review=entry["semantic_review"],
        )
        if decision in {"one_off", "fact_correction"}:
            entry["status"] = "archived_observation"
        changed += 1
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CODEX_REVIEW_APPLIED: {changed} decisions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

