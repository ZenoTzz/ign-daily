#!/usr/bin/env python3
"""Check key project files for mojibake or broken UTF-8 text.

This catches real encoding damage, not console display issues. It scans only
project docs, UI files, workflows, and scripts; article data can contain user
content and is intentionally excluded.
"""
from __future__ import annotations

import sys
from pathlib import Path

from common_paths import REPO_ROOT, configure_utf8_stdio


configure_utf8_stdio()

TEXT_EXTENSIONS = {".html", ".css", ".js", ".md", ".py", ".yml", ".yaml", ".json"}
SCAN_ROOTS = [
    REPO_ROOT,
    REPO_ROOT / "assets",
    REPO_ROOT / "scripts",
    REPO_ROOT / ".github" / "workflows",
]
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "data",
    "node_modules",
}

MOJIBAKE_MARKERS = {
    chr(0x9358): "common UTF-8-as-GBK marker",
    chr(0x9428): "common UTF-8-as-GBK marker",
    chr(0x9983): "emoji mojibake marker",
    chr(0x9225): "smart quote mojibake marker",
    chr(0x6D93): "common Chinese mojibake marker",
    chr(0x9286): "Chinese punctuation mojibake marker",
    chr(0xFFFD): "Unicode replacement character",
}


def iter_scan_files() -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = [p for p in root.rglob("*") if p.is_file()]
        for path in candidates:
            rel_parts = set(path.relative_to(REPO_ROOT).parts[:-1])
            if rel_parts & SKIP_DIRS:
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            if path in seen:
                continue
            seen.add(path)
            files.append(path)
    return sorted(files)


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def main() -> int:
    issues: list[str] = []
    scanned = 0
    for path in iter_scan_files():
        scanned += 1
        rel = path.relative_to(REPO_ROOT)
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            issues.append(f"{rel}: invalid UTF-8 at byte {exc.start}")
            continue
        for marker, reason in MOJIBAKE_MARKERS.items():
            offset = text.find(marker)
            if offset == -1:
                continue
            line = line_for_offset(text, offset)
            snippet = text[max(0, offset - 20): offset + 40].replace("\n", "\\n")
            issues.append(f"{rel}:{line}: possible mojibake '{marker}' ({reason}) near: {snippet}")
            break

    if issues:
        print(f"ENCODING_HEALTH_FAIL: {len(issues)} issue(s) in {scanned} file(s)")
        for issue in issues:
            print(f"  {issue}")
        return 1
    print(f"ENCODING_HEALTH_OK: scanned {scanned} key text file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
