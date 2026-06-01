#!/usr/bin/env python3
"""Validate RSS-only updates before an automated commit.

This check is intentionally lighter than pre_push_check.py. RSS automation may
queue English placeholder titles for a later AI title/summary pass, so this
script only verifies data shape, publish times, and queue consistency.

Usage:
  python3 scripts/rss_queue_check.py YYYY-MM-DD
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
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


def default_date() -> str:
    now = datetime.now(CST)
    today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d") if now < today_0800 else (now + timedelta(days=1)).strftime("%Y-%m-%d")


def load_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)
    print(f"[FAIL] {message}")


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else default_date()
    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    queue_path = day_dir / "need_titles.json"
    index_list_path = DATA_DIR / "index-list.json"
    errors: list[str] = []

    if not index_path.exists():
        fail(errors, f"missing index.json: {index_path}")
        return 1

    index = load_json(index_path)
    articles = index.get("articles")
    if not isinstance(articles, list):
        fail(errors, "index.json articles must be a list")
        return 1

    seen_ids: set[int] = set()
    seen_urls: set[str] = set()
    by_url: dict[str, dict] = {}
    for article in articles:
        aid = article.get("id")
        url = article.get("url")
        if not isinstance(aid, int):
            fail(errors, f"article has invalid id: {aid!r}")
        elif aid in seen_ids:
            fail(errors, f"duplicate article id: {aid}")
        else:
            seen_ids.add(aid)

        if not url:
            fail(errors, f"article #{aid} missing url")
        elif url in seen_urls:
            fail(errors, f"duplicate article url: {url}")
        else:
            seen_urls.add(url)
            by_url[url] = article

        for field in ("en_title", "cn_title", "publish_time_cn"):
            if not article.get(field):
                fail(errors, f"article #{aid} missing {field}")

        publish_time = article.get("publish_time_cn", "")
        if publish_time and not TIME_RE.match(publish_time):
            fail(errors, f"article #{aid} invalid publish_time_cn: {publish_time!r}")

    if index.get("total") != len(articles):
        fail(errors, f"index total {index.get('total')} != article count {len(articles)}")

    if index_list_path.exists():
        index_list = load_json(index_list_path)
        entry = next((item for item in index_list if item.get("date") == date), None)
        if not entry:
            fail(errors, f"data/index-list.json missing date {date}")
        elif entry.get("total") != len(articles):
            fail(errors, f"index-list total {entry.get('total')} != article count {len(articles)}")

    if queue_path.exists():
        queue = load_json(queue_path)
        if not isinstance(queue, list):
            fail(errors, "need_titles.json must be a list")
        else:
            queued_urls: set[str] = set()
            for item in queue:
                url = item.get("url")
                if not url:
                    fail(errors, "need_titles item missing url")
                    continue
                if url in queued_urls:
                    fail(errors, f"duplicate need_titles url: {url}")
                queued_urls.add(url)
                article = by_url.get(url)
                if not article:
                    fail(errors, f"need_titles url not found in index.json: {url}")
                    continue
                if item.get("en_title") and item.get("en_title") != article.get("en_title"):
                    fail(errors, f"need_titles title mismatch for #{article.get('id')}")
                if item.get("pub_date") and item.get("pub_date") != article.get("publish_time_cn"):
                    fail(errors, f"need_titles pub_date mismatch for #{article.get('id')}")

    if errors:
        print(f"\nRSS_QUEUE_CHECK_BLOCKED: {len(errors)} error(s)")
        return 1

    print(f"RSS_QUEUE_CHECK_OK: {date}, articles={len(articles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
