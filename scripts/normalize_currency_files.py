#!/usr/bin/env python3
"""Normalize currency conversions in stored article JSON files."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio
from currency_utils import normalize_currency_text, normalize_translation_currency


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))


def default_date() -> str:
    now = datetime.now(CST)
    today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d") if now < today_0800 else (now + timedelta(days=1)).strftime("%Y-%m-%d")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_index(path: Path) -> bool:
    if not path.exists():
        return False
    data = read_json(path)
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    for article in data.get("articles", []):
        if isinstance(article.get("summary"), str):
            article["summary"] = normalize_currency_text(article["summary"])
        if isinstance(article.get("cn_title"), str):
            article["cn_title"] = normalize_currency_text(article["cn_title"])
    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if before != after:
        write_json(path, data)
        return True
    return False


def normalize_translation(path: Path) -> bool:
    data = read_json(path)
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    normalize_translation_currency(data)
    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if before != after:
        write_json(path, data)
        return True
    return False


def normalize_comparison(path: Path) -> bool:
    data = read_json(path)
    before = json.dumps(data, ensure_ascii=False, sort_keys=True)
    for result in data.get("results", []):
        if isinstance(result, dict):
            normalize_translation_currency(result)
    after = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if before != after:
        write_json(path, data)
        return True
    return False


def normalize_date(date: str) -> int:
    day_dir = DATA_DIR / date
    if not day_dir.exists():
        print(f"NORMALIZE_CURRENCY_SKIP: no data dir for {date}")
        return 0

    changed = 0
    if normalize_index(day_dir / "index.json"):
        changed += 1
        print(f"[currency] normalized {date}/index.json")

    trans_dir = day_dir / "translations"
    if trans_dir.exists():
        for path in sorted(trans_dir.glob("*.json")):
            if normalize_translation(path):
                changed += 1
                print(f"[currency] normalized {date}/translations/{path.name}")

    compare_dir = day_dir / "comparisons"
    if compare_dir.exists():
        for path in sorted(compare_dir.glob("*.json")):
            if normalize_comparison(path):
                changed += 1
                print(f"[currency] normalized {date}/comparisons/{path.name}")

    print(f"NORMALIZE_CURRENCY_DONE: date={date}, changed_files={changed}")
    return changed


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else default_date()
    if target == "--all":
        total = 0
        for day_dir in sorted(DATA_DIR.glob("20??-??-??")):
            total += normalize_date(day_dir.name)
        print(f"NORMALIZE_CURRENCY_ALL_DONE: changed_files={total}")
    else:
        normalize_date(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
