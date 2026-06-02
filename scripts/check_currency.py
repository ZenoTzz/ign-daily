#!/usr/bin/env python3
"""Check translated Chinese text for foreign-currency amounts without CNY conversion."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common_paths import DATA_DIR, configure_utf8_stdio
from currency_utils import find_missing_currency, load_rates, normalize_currency_text


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))


def default_date() -> str:
    now = datetime.now(CST)
    today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d") if now < today_0800 else (now + timedelta(days=1)).strftime("%Y-%m-%d")


def read_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def suggestion(found: str) -> str:
    normalized = normalize_currency_text(found, rates=load_rates())
    return normalized if normalized != found else f"{found}(约合人民币?元)"


def add_issues(issues: list[dict], source: str, text: str, label: str = "") -> None:
    for found, context in find_missing_currency(text):
        issues.append({
            "source": source,
            "label": label,
            "found": found,
            "suggestion": suggestion(found),
            "context": context,
        })


def check_index(day_dir: Path, issues: list[dict]) -> None:
    path = day_dir / "index.json"
    if not path.exists():
        return
    data = read_json(path)
    for article in data.get("articles", []):
        aid = article.get("id")
        add_issues(issues, "index.json", article.get("summary", ""), f"#{aid} summary")


def check_translation_file(path: Path, issues: list[dict]) -> None:
    data = read_json(path)
    add_issues(issues, path.name, data.get("cn_title", ""), "cn_title")
    add_issues(issues, path.name, data.get("opus_summary", ""), "opus_summary")
    for i, para in enumerate(data.get("paragraphs", []), start=1):
        if isinstance(para, dict):
            add_issues(issues, path.name, para.get("cn", ""), f"para[{i}]")


def check_comparison_file(path: Path, issues: list[dict]) -> None:
    data = read_json(path)
    for result in data.get("results", []):
        model = result.get("translator_model") or result.get("label") or "model"
        add_issues(issues, path.name, result.get("cn_title", ""), f"{model} cn_title")
        add_issues(issues, path.name, result.get("opus_summary", ""), f"{model} opus_summary")
        for i, para in enumerate(result.get("paragraphs", []), start=1):
            if isinstance(para, dict):
                add_issues(issues, path.name, para.get("cn", ""), f"{model} para[{i}]")


def main() -> int:
    date_str = sys.argv[1] if len(sys.argv) > 1 else default_date()
    day_dir = DATA_DIR / date_str
    if not day_dir.exists():
        print(f"No data dir for {date_str}")
        return 0

    issues: list[dict] = []
    check_index(day_dir, issues)

    trans_dir = day_dir / "translations"
    if trans_dir.exists():
        for path in sorted(trans_dir.glob("*.json")):
            check_translation_file(path, issues)

    compare_dir = day_dir / "comparisons"
    if compare_dir.exists():
        for path in sorted(compare_dir.glob("*.json")):
            check_comparison_file(path, issues)

    if issues:
        print(f"CURRENCY_CHECK: {len(issues)} amount(s) missing CNY conversion in {date_str}:")
        for issue in issues:
            label = f" {issue['label']}" if issue.get("label") else ""
            print(f"  {issue['source']}{label}: {issue['found']} -> suggest: {issue['suggestion']}")
            print(f"    context: ...{issue['context']}...")
        print("\nFix these before pushing.")
        return 1

    print(f"CURRENCY_CHECK_OK: all amounts in {date_str} include CNY conversions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
