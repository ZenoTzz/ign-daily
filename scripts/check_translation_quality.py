#!/usr/bin/env python3
"""Validate the versioned independent-review gate for published translations."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio

sys.path.insert(0, str(REPO_ROOT / "server_api"))
from translation_quality import validate_translation_quality  # noqa: E402


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(CST).strftime("%Y-%m-%d")
    day = DATA_DIR / date
    index_path = day / "index.json"
    if not index_path.exists():
        print(f"QUALITY REVIEW BLOCKED: missing {index_path}")
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    errors: list[str] = []
    checked = 0
    legacy = 0
    for article in index.get("articles", []):
        if article.get("translation_status") != "done":
            continue
        article_id = int(article["id"])
        path = day / "translations" / f"{article_id:02d}.json"
        if not path.exists():
            errors.append(f"#{article_id}: missing translation file")
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        # Historical translations remain immutable. New work opts into v1 and
        # the API completion endpoint independently requires v1 for every new job.
        if "quality_gate_version" not in data:
            legacy += 1
            continue
        checked += 1
        errors.extend(f"#{article_id}: {error}" for error in validate_translation_quality(data))
    print(f"QUALITY REVIEW CHECK: {date}; gated={checked}; legacy={legacy}")
    if errors:
        print(f"BLOCKED: {len(errors)} quality-review error(s)")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("QUALITY REVIEW CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
