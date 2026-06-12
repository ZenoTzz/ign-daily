#!/usr/bin/env python3
"""Normalize Chinese double quotes in one date's index and translations."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from chinese_punctuation import normalize_chinese_quotes, normalize_translation_quotes
from common_paths import DATA_DIR, configure_utf8_stdio


configure_utf8_stdio()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_date(date: str) -> int:
    day_dir = DATA_DIR / date
    changed = 0
    index_path = day_dir / "index.json"
    if index_path.exists():
        index = load_json(index_path)
        before = json.dumps(index, ensure_ascii=False, sort_keys=True)
        for article in index.get("articles", []):
            if not isinstance(article, dict):
                continue
            for key in ("cn_title", "subtitle", "summary"):
                if isinstance(article.get(key), str):
                    article[key] = normalize_chinese_quotes(article[key])
        if json.dumps(index, ensure_ascii=False, sort_keys=True) != before:
            write_json(index_path, index)
            changed += 1
            print(f"[QUOTES] normalized {index_path.relative_to(DATA_DIR.parent)}")

    translations_dir = day_dir / "translations"
    for path in sorted(translations_dir.glob("*.json")):
        data = load_json(path)
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        normalize_translation_quotes(data)
        if json.dumps(data, ensure_ascii=False, sort_keys=True) != before:
            write_json(path, data)
            changed += 1
            print(f"[QUOTES] normalized {path.relative_to(DATA_DIR.parent)}")
    return changed


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/normalize_translation_quotes.py YYYY-MM-DD")
        return 2
    changed = normalize_date(sys.argv[1])
    print(f"NORMALIZE_TRANSLATION_QUOTES_OK: {changed} file(s) changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
