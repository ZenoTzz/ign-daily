#!/usr/bin/env python3
"""Move entries from unknown dictionary categories into a canonical fallback."""
from __future__ import annotations

import argparse
import json
from typing import Any

from common_paths import configure_utf8_stdio, dict_path
from dict_matcher import DICT_CATEGORIES


configure_utf8_stdio()


def normalize_dictionary(data: dict[str, Any], fallback: str = "terms") -> tuple[dict[str, Any], int, int]:
    if fallback not in DICT_CATEGORIES:
        raise ValueError(f"invalid fallback category: {fallback}")
    target = data.setdefault(fallback, {})
    moved = 0
    collisions = 0
    for category in list(data):
        if category == "_meta" or category in DICT_CATEGORIES:
            continue
        entries = data.get(category)
        if not isinstance(entries, dict):
            del data[category]
            continue
        for en, raw_value in entries.items():
            if any(en in (data.get(cat) or {}) for cat in DICT_CATEGORIES):
                collisions += 1
                continue
            value = dict(raw_value) if isinstance(raw_value, dict) else {"cn": str(raw_value)}
            value.setdefault("source", "user")
            target[en] = value
            moved += 1
        del data[category]
    return data, moved, collisions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--fallback", default="terms", choices=DICT_CATEGORIES)
    args = parser.parse_args()

    path = dict_path()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    normalized, moved, collisions = normalize_dictionary(data, args.fallback)
    print(f"DICT_CATEGORY_NORMALIZE: moved={moved}, collisions_kept={collisions}, fallback={args.fallback}")
    if args.write:
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"DICT_CATEGORY_NORMALIZE_WRITTEN: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
