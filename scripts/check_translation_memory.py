#!/usr/bin/env python3
"""Block publication when an approved exact translation memory is not reused."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from common_paths import DATA_DIR, configure_utf8_stdio
from translation_memory import find_hits, validate_locks


configure_utf8_stdio()


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def hits_active_for_translation(hits: list[dict], translation: dict) -> list[dict]:
    """Grandfather translations created before a memory rule became active."""
    translated_at = parse_time(translation.get("translated_at"))
    if translated_at is None:
        return hits
    active: list[dict] = []
    for hit in hits:
        active_from = parse_time(hit.get("active_from"))
        if active_from is None or translated_at >= active_from:
            active.append(hit)
    return active


def check_date(date: str) -> list[str]:
    day = DATA_DIR / date
    translations = day / "translations"
    errors: list[str] = []
    if not translations.exists():
        return errors
    for translation_path in sorted(translations.glob("[0-9][0-9].json")):
        article_id = int(translation_path.stem)
        source_path = day / "sources" / f"{article_id:02d}.json"
        if not source_path.exists():
            continue
        source = load_json(source_path)
        translation = load_json(translation_path)
        paragraphs_en = source.get("paragraphs_en") or []
        if not isinstance(paragraphs_en, list):
            continue
        hits = find_hits(str(value) for value in paragraphs_en)
        hits = hits_active_for_translation(hits, translation)
        for error in validate_locks(translation, hits):
            errors.append(f"#{article_id:02d}: {error}")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_translation_memory.py YYYY-MM-DD")
        return 2
    try:
        errors = check_date(sys.argv[1])
    except ValueError as exc:
        print(f"TRANSLATION_MEMORY_CHECK_FAILED\n- {exc}")
        return 1
    if errors:
        print("TRANSLATION_MEMORY_CHECK_FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("TRANSLATION_MEMORY_CHECK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
