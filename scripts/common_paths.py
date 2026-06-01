"""Shared path helpers for IGN Daily scripts.

Scripts are expected to live in ``ign-daily/scripts`` and run from any cwd.
Keep all repo/workspace path guessing here so validation scripts do not
silently scan the wrong directory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"


def env_paths() -> list[Path]:
    """Return .env candidates in priority order."""
    candidates = [
        REPO_ROOT / ".env",
        REPO_ROOT / "scripts" / ".env",
    ]
    workspace = os.environ.get("WORKSPACE")
    if workspace:
        candidates.append(Path(workspace) / ".env")
    candidates.append(Path(r"C:\Users\Administrator\.openclaw\workspace\.env"))
    return candidates


def dict_path() -> Path:
    """Return the active dictionary path.

    The web app edits data/dict.json, so scripts should prefer that file.
    Older workspaces may still provide game_names_dict.json; keep it as a
    compatibility fallback.
    """
    candidates = [
        DATA_DIR / "dict.json",
        REPO_ROOT / "game_names_dict.json",
    ]
    workspace = os.environ.get("WORKSPACE")
    if workspace:
        candidates.append(Path(workspace) / "game_names_dict.json")
    candidates.append(Path(r"C:\Users\Administrator\.openclaw\workspace\game_names_dict.json"))
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def exchange_rates_path() -> Path:
    candidates = [
        REPO_ROOT / "exchange_rates.json",
    ]
    workspace = os.environ.get("WORKSPACE")
    if workspace:
        candidates.append(Path(workspace) / "exchange_rates.json")
    candidates.append(Path(r"C:\Users\Administrator\.openclaw\workspace\exchange_rates.json"))
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def configure_utf8_stdio() -> None:
    """Make emoji/Chinese script output safe on Windows consoles."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
