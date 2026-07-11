#!/usr/bin/env python3
"""Build the mandatory semantic-review queue for Codex-owned nightly learning."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common_paths import DATA_DIR

CST = timezone(timedelta(hours=8))
LEARNING = DATA_DIR / "learning"
EVIDENCE = LEARNING / "style-evidence.json"
QUEUE = LEARNING / "semantic-review-queue.json"


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8-sig")) if EVIDENCE.exists() else {"rules": {}}
    items = []
    for rule in (evidence.get("rules") or {}).values():
        if not isinstance(rule, dict) or rule.get("status") != "observed":
            continue
        if rule.get("semantic_review") in {"approved", "rejected"}:
            continue
        items.append({
            "id": rule.get("id"),
            "type": rule.get("type") or "style_observation",
            "title": rule.get("title"),
            "proposed_rule": rule.get("rule"),
            "scope": rule.get("scope"),
            "days_seen": rule.get("days_seen", 0),
            "articles_seen": rule.get("articles_seen", 0),
            "contradictions": rule.get("contradictions", 0),
            "alternatives": rule.get("alternatives", {}),
            "examples": rule.get("examples", [])[:8],
            "questions": [
                "这是稳定偏好、事实纠错、词库实体、格式偏好还是一次性修改？",
                "英文和中文是否在上下文中指向同一实体？",
                "是否存在反例或更合理解释？",
                "规则能否明确执行，误用风险是什么？",
            ],
        })
    payload = {
        "schema_version": 2,
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "instructions": "Codex must write semantic-review-results.json; mechanical scripts cannot approve candidates.",
        "allowed_decisions": ["approve", "reject", "observe", "one_off", "fact_correction"],
        "items": items,
    }
    QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"CODEX_REVIEW_QUEUE_READY: {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

