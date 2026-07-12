#!/usr/bin/env python3
"""Block publication when a full translation omits, merges, or rewrites source paragraphs.

The source cache is authoritative for full-text work.  ``paragraphs[].en`` is
deliberately retained in translation JSON, so it can serve as an auditable
one-to-one alignment record rather than a model-generated paraphrase.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common_paths import DATA_DIR, configure_utf8_stdio


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))

# These are publisher bylines/credits, not article body.  Keep this list
# intentionally narrow: uncertain text must stay in the translation.
NON_BODY_PATTERNS = (
    re.compile(r"^Photographer:\s*", re.I),
    re.compile(r"^Image Credit:\s*", re.I),
    re.compile(r"^Photo by\b", re.I),
    re.compile(r"\b(?:is|serves as) (?:a|an|the) .{0,90}\b(?:at|for) IGN\b", re.I),
    re.compile(r"\bis a freelance writer\b", re.I),
    re.compile(r"\b(?:find|reach|follow) .{0,80}\b(?:Twitter|Bluesky|X|@)\b", re.I),
)


def is_non_body(paragraph: str) -> bool:
    """Return true only for a narrow, documented class of IGN credits."""
    return any(pattern.search(paragraph.strip()) for pattern in NON_BODY_PATTERNS)


def expected_paragraphs(source: dict) -> list[str]:
    return [
        paragraph
        for paragraph in source.get("paragraphs_en", [])
        if isinstance(paragraph, str) and paragraph.strip() and not is_non_body(paragraph)
    ]


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(CST).strftime("%Y-%m-%d")
    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    if not index_path.exists():
        print(f"SOURCE ALIGNMENT BLOCKED: missing {index_path}")
        return 1

    index = json.loads(index_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    checked = 0
    for article in index.get("articles", []):
        if article.get("translation_status") != "done":
            continue
        aid = int(article["id"])
        source_path = day_dir / "sources" / f"{aid:02d}.json"
        translation_path = day_dir / "translations" / f"{aid:02d}.json"
        if not source_path.exists() or not translation_path.exists():
            errors.append(f"#{aid}: missing source or translation file")
            continue
        source = json.loads(source_path.read_text(encoding="utf-8"))
        translation = json.loads(translation_path.read_text(encoding="utf-8"))
        expected = expected_paragraphs(source)
        paragraphs = translation.get("paragraphs")
        checked += 1
        if source.get("url") != translation.get("url"):
            errors.append(f"#{aid}: source and translation URLs differ")
        if not isinstance(paragraphs, list):
            errors.append(f"#{aid}: paragraphs is not a list")
            continue
        if len(paragraphs) != len(expected):
            errors.append(
                f"#{aid}: expected {len(expected)} source-body paragraphs, got {len(paragraphs)}"
            )
            continue
        for position, (source_en, item) in enumerate(zip(expected, paragraphs), start=1):
            if not isinstance(item, dict):
                errors.append(f"#{aid} paragraph {position}: not an object")
                continue
            if item.get("en") != source_en:
                errors.append(
                    f"#{aid} paragraph {position}: en must copy the corresponding source paragraph exactly"
                )
            if not str(item.get("cn") or "").strip():
                errors.append(f"#{aid} paragraph {position}: missing Chinese translation")

    print(f"SOURCE ALIGNMENT CHECK: {date}; translations checked: {checked}")
    if errors:
        print(f"BLOCKED: {len(errors)} source-alignment error(s)")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("SOURCE ALIGNMENT CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
