#!/usr/bin/env python3
"""Quick repository health check for a new agent.

Usage:
  python3 scripts/agent_doctor.py

This script checks the invariants agents most often forget: expected files,
active dictionary location, stale hard-coded paths, and basic JSON/Python
parseability. It does not modify files.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from common_paths import (
    DATA_DIR,
    REPO_ROOT,
    configure_utf8_stdio,
    dict_path,
    exchange_rates_path,
)
from dict_matcher import DICT_CATEGORIES


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
RATE_RANGES = {
    "USD": (5.0, 9.0),
    "EUR": (5.0, 12.0),
    "GBP": (6.0, 14.0),
    "JPY_100": (3.0, 8.0),
    "KRW_100": (0.3, 0.8),
}
MAX_RATE_AGE_HOURS = 36


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)
    print(f"[FAIL] {msg}")


def date_window(date: str) -> tuple[datetime, datetime]:
    end = datetime.strptime(date, "%Y-%m-%d").replace(
        tzinfo=CST, hour=8, minute=0, second=0, microsecond=0
    )
    return end - timedelta(days=1), end


def main() -> int:
    errors: list[str] = []

    required = [
        "AGENTS.md",
        "docs/ARCHITECTURE.md",
        "docs/TRANSLATION_REQUIREMENTS.md",
        "TRANSLATION_GUIDE.md",
        "STYLE_PROFILE.md",
        "data/README.md",
        "scripts/README.md",
        "scripts/common_paths.py",
        "scripts/pre_push_check.py",
        "scripts/article_cache.py",
        "scripts/prompt_blocks.py",
        "scripts/nightly_style_api.py",
        ".github/workflows/hourly-rss.yml",
        ".github/workflows/api-translation.yml",
        ".github/workflows/nightly-style.yml",
        ".github/workflows/deepseek-usage.yml",
        "data/automation-config.json",
        "data/usage/deepseek/index.json",
        "data/usage/deepseek-balance.json",
        "data/dict.json",
        "data/index-list.json",
    ]
    for rel in required:
        path = REPO_ROOT / rel
        if path.exists():
            ok(f"exists: {rel}")
        else:
            fail(errors, f"missing: {rel}")

    active_dict = dict_path()
    if active_dict == DATA_DIR / "dict.json":
        ok("active dictionary is data/dict.json")
    else:
        fail(errors, f"active dictionary is not data/dict.json: {active_dict}")

    if active_dict.exists():
        dictionary = json.loads(active_dict.read_text(encoding="utf-8-sig"))
        unknown_categories = sorted(set(dictionary) - {"_meta", *DICT_CATEGORIES})
        if unknown_categories:
            fail(
                errors,
                f"dictionary has unknown categories: {', '.join(unknown_categories)}",
            )
        else:
            ok("dictionary categories are canonical")

    exchange_path = exchange_rates_path()
    if not exchange_path.exists():
        fail(errors, f"missing exchange rates: {exchange_path}")
    else:
        try:
            exchange_data = json.loads(exchange_path.read_text(encoding="utf-8-sig"))
            validation = exchange_data.get("validation") or {}
            rates = exchange_data.get("rates_to_cny") or {}
            if (
                validation.get("verified") is True
                and int(validation.get("source_count") or 0) >= 2
            ):
                ok("exchange rates are multi-source verified")
            else:
                fail(errors, "exchange rates are not multi-source verified")
            updated_at = str(exchange_data.get("updated_at") or "")
            try:
                updated_dt = datetime.strptime(
                    updated_at, "%Y-%m-%d %H:%M:%S +08:00"
                ).replace(tzinfo=CST)
                age = datetime.now(CST) - updated_dt
                if age <= timedelta(hours=MAX_RATE_AGE_HOURS):
                    ok("exchange rates are fresh")
                else:
                    fail(errors, f"exchange rates are stale: {age}")
            except ValueError:
                fail(errors, f"exchange rates have invalid updated_at: {updated_at}")
            for key, (low, high) in RATE_RANGES.items():
                value = float(rates.get(key))
                if low <= value <= high:
                    continue
                fail(errors, f"exchange rate {key} outside sane range: {value}")
        except Exception as exc:
            fail(errors, f"exchange-rate validation failed: {exc}")

    for p in REPO_ROOT.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            fail(errors, f"python parse error: {p.relative_to(REPO_ROOT)}: {exc}")
    if not any("python parse error" in e for e in errors):
        ok("all Python files parse")

    for p in REPO_ROOT.rglob("*.json"):
        try:
            json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            fail(errors, f"json parse error: {p.relative_to(REPO_ROOT)}: {exc}")
    if not any("json parse error" in e for e in errors):
        ok("all JSON files parse")

    encoding_check = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_encoding_health.py")],
        cwd=REPO_ROOT,
    )
    if encoding_check.returncode == 0:
        ok("encoding health check passed")
    else:
        fail(errors, "encoding health check failed")

    dated_indexes = sorted(DATA_DIR.glob("20??-??-??/index.json"))
    for index_path in dated_indexes:
        data = json.loads(index_path.read_text(encoding="utf-8-sig"))
        date = index_path.parent.name
        seen_ids: set[int] = set()
        seen_urls: set[str] = set()
        for article in data.get("articles", []):
            aid = article.get("id")
            url = article.get("url")
            if isinstance(aid, int):
                if aid in seen_ids:
                    fail(errors, f"duplicate article id in {date}/index.json: #{aid}")
                seen_ids.add(aid)
            if url:
                if url in seen_urls:
                    fail(errors, f"duplicate article url in {date}/index.json: {url}")
                seen_urls.add(url)
            if isinstance(aid, int):
                source_path = index_path.parent / "sources" / f"{aid:02d}.json"
                if source_path.exists():
                    source = json.loads(source_path.read_text(encoding="utf-8-sig"))
                    if source.get("url") and url and source.get("url") != url:
                        fail(errors, f"source URL mismatch in {date}: #{aid}")
                trans_rel = article.get("translation_path")
                if trans_rel:
                    trans_path = index_path.parent / trans_rel
                    if trans_path.exists():
                        trans = json.loads(trans_path.read_text(encoding="utf-8-sig"))
                        if trans.get("url") and url and trans.get("url") != url:
                            fail(errors, f"translation URL mismatch in {date}: #{aid}")
    latest_index = dated_indexes[-1] if dated_indexes else None
    for index_path in [latest_index] if latest_index else []:
        data = json.loads(index_path.read_text(encoding="utf-8-sig"))
        window_start, window_end = date_window(index_path.parent.name)
        for article in data.get("articles", []):
            if not article.get("publish_time_cn"):
                fail(
                    errors,
                    f"latest index missing publish_time_cn: {index_path.parent.name} #{article.get('id')}",
                )
                break
            try:
                publish_dt = datetime.strptime(
                    article["publish_time_cn"], "%Y-%m-%d %H:%M"
                ).replace(tzinfo=CST)
            except ValueError:
                fail(
                    errors,
                    f"latest index invalid publish_time_cn: {index_path.parent.name} #{article.get('id')}",
                )
                continue
            if publish_dt < window_start or publish_dt >= window_end:
                fail(
                    errors,
                    f"latest index publish_time outside date window: {index_path.parent.name} #{article.get('id')}",
                )
        for article in data.get("articles", []):
            if article.get("translation_status") != "done":
                continue
            aid = article.get("id")
            if article.get("cn_title") == article.get("en_title"):
                fail(
                    errors,
                    f"latest done article title still English: {index_path.parent.name} #{aid}",
                )
            if not article.get("summary"):
                fail(
                    errors,
                    f"latest done article missing summary: {index_path.parent.name} #{aid}",
                )

    stale_patterns = [
        "IGN_TRANSLATE_INSTRUCTIONS.md",
        "HEARTBEAT.md",
        "assets/github-api.js",
        "scripts/push_daily.py",
    ]
    ignored_doc_parts = {".git", ".venv", "node_modules", "tmp", "__pycache__"}
    scan_files = [
        path
        for path in REPO_ROOT.rglob("*.md")
        if not ignored_doc_parts.intersection(path.relative_to(REPO_ROOT).parts)
    ]
    for p in scan_files:
        text = p.read_text(encoding="utf-8")
        for pattern in stale_patterns:
            if pattern in text:
                fail(
                    errors, f"stale doc reference {pattern}: {p.relative_to(REPO_ROOT)}"
                )

        for raw_target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            target = raw_target.strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            else:
                target = target.split(maxsplit=1)[0]
            if not target or target.startswith(
                ("#", "http://", "https://", "mailto:", "app://")
            ):
                continue
            target = unquote(target.split("#", 1)[0])
            linked = (p.parent / target).resolve()
            if not linked.exists():
                fail(
                    errors,
                    f"broken Markdown link {raw_target}: {p.relative_to(REPO_ROOT)}",
                )

    if errors:
        print(f"\nAGENT_DOCTOR_FAILED: {len(errors)} issue(s)")
        return 1
    print("\nAGENT_DOCTOR_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
