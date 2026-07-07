#!/usr/bin/env python3
"""Run all required checks before pushing translation work.

Usage:
  python3 scripts/pre_push_check.py [YYYY-MM-DD]

This is the memory-saver wrapper for agents: run one command, get the same
three checks required by the handoff docs.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common_paths import REPO_ROOT, configure_utf8_stdio


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))


def default_date() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def run_check(script: str, date: str) -> int:
    path = REPO_ROOT / "scripts" / script
    print(f"\n=== {script} {date} ===")
    result = subprocess.run([sys.executable, str(path), date], cwd=REPO_ROOT)
    if result.returncode == 0:
        print(f"[OK] {script}")
    else:
        print(f"[FAIL] {script} exited {result.returncode}")
    return result.returncode


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else default_date()
    checks = [
        "post_translate_check.py",
        "check_currency.py",
        "enforce_dict_titles.py",
        "check_dict_fulltext.py",
    ]
    failures = [script for script in checks if run_check(script, date) != 0]
    if failures:
        print(f"\nBLOCKED: {len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("\nALL PRE-PUSH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

