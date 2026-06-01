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
from pathlib import Path

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio, dict_path


configure_utf8_stdio()


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)
    print(f"[FAIL] {msg}")


def main() -> int:
    errors: list[str] = []

    required = [
        "AGENT_BOOTSTRAP.md",
        "AGENT_HANDOFF.md",
        "TRANSLATION_GUIDE.md",
        "scripts/common_paths.py",
        "scripts/pre_push_check.py",
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

    for p in REPO_ROOT.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"))
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

    stale_patterns = [
        "IGN_TRANSLATE_INSTRUCTIONS.md",
        "HEARTBEAT.md",
        "assets/github-api.js",
        "scripts/push_daily.py",
    ]
    scan_files = [
        *REPO_ROOT.glob("*.md"),
        *(REPO_ROOT / "scripts").glob("*.md"),
        *(REPO_ROOT / "data").glob("*.md"),
    ]
    for p in scan_files:
        text = p.read_text(encoding="utf-8")
        for pattern in stale_patterns:
            if pattern in text:
                fail(errors, f"stale doc reference {pattern}: {p.relative_to(REPO_ROOT)}")

    if errors:
        print(f"\nAGENT_DOCTOR_FAILED: {len(errors)} issue(s)")
        return 1
    print("\nAGENT_DOCTOR_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

