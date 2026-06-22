#!/usr/bin/env python3
"""Normalize platform brand spellings in Chinese-facing translation output."""
from __future__ import annotations

import re
from typing import Any


XBOX_RE = re.compile(r"(?<![A-Za-z0-9])xbox(?![A-Za-z0-9])", re.I)


def normalize_platform_text(value: str) -> str:
    return XBOX_RE.sub("XBOX", str(value or ""))


def normalize_platform_names_in_translation(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize user-visible translated fields without touching source fields."""
    for key in ("cn_title", "subtitle", "summary", "opus_summary"):
        if isinstance(data.get(key), str):
            data[key] = normalize_platform_text(data[key])
    for paragraph in data.get("paragraphs", []):
        if isinstance(paragraph, dict) and isinstance(paragraph.get("cn"), str):
            paragraph["cn"] = normalize_platform_text(paragraph["cn"])
    for key in ("translated_terms",):
        if isinstance(data.get(key), dict):
            data[key] = {
                term: normalize_platform_text(value) if isinstance(value, str) else value
                for term, value in data[key].items()
            }
    for item in data.get("pending_dict", []):
        if isinstance(item, dict) and isinstance(item.get("cn"), str):
            item["cn"] = normalize_platform_text(item["cn"])
    return data
