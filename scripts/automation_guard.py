#!/usr/bin/env python3
"""Read data/automation-config.json and tell an automation whether to run.

Usage:
  python3 scripts/automation_guard.py title
  python3 scripts/automation_guard.py fulltext
  python3 scripts/automation_guard.py nightly

Exit code is always 0 so cron jobs do not look failed just because a task is
owned by API mode. Check the printed AUTOMATION_GUARD line.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from common_paths import DATA_DIR, configure_utf8_stdio


configure_utf8_stdio()
CONFIG_PATH = DATA_DIR / "automation-config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {
            "title_translator": "openclaw",
            "fulltext_translator": "openclaw",
            "nightly_learner": "openclaw",
            "api_model": "deepseek-v4-flash",
        }
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def main() -> int:
    task = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if task not in {"title", "fulltext", "nightly"}:
        print("Usage: python3 scripts/automation_guard.py title|fulltext|nightly")
        return 0

    cfg = load_config()
    title_mode = cfg.get("title_translator", "openclaw")
    fulltext_mode = cfg.get("fulltext_translator", "openclaw")
    nightly_mode = cfg.get("nightly_learner", "openclaw")
    model = cfg.get("api_model", "")

    if task == "nightly":
        if nightly_mode in {"api", "deepseek"}:
            print(f"AUTOMATION_GUARD SKIP task=nightly owner=api model={cfg.get('api_nightly_model') or model}")
            return 0
        print(f"AUTOMATION_GUARD RUN task=nightly owner=openclaw model={model}")
        return 0

    mode = title_mode if task == "title" else fulltext_mode
    if mode in {"api", "deepseek"}:
        print(f"AUTOMATION_GUARD SKIP task={task} owner=api model={model}")
        return 0

    print(f"AUTOMATION_GUARD RUN task={task} owner=openclaw model={model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
