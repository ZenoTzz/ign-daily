#!/usr/bin/env python3
"""Normalize hard-rule Chinese punctuation in translated fields."""
from __future__ import annotations

from typing import Any


DISALLOWED_DOUBLE_QUOTES = ('"', "\u201c", "\u201d", "\uff02")


def normalize_chinese_quotes(text: str) -> str:
    """Convert curly/fullwidth/straight double quotes to Chinese corner quotes."""
    value = str(text or "").replace("\u201c", "\u300c").replace("\u201d", "\u300d")
    output: list[str] = []
    open_quote = True
    for char in value:
        if char in {'"', "\uff02"}:
            output.append("\u300c" if open_quote else "\u300d")
            open_quote = not open_quote
        else:
            output.append(char)
    return "".join(output)


def normalize_translation_quotes(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize Chinese-facing fields in a translation object in place."""
    for key in ("cn_title", "subtitle", "summary", "opus_summary"):
        if isinstance(data.get(key), str):
            data[key] = normalize_chinese_quotes(data[key])
    for paragraph in data.get("paragraphs", []):
        if isinstance(paragraph, dict) and isinstance(paragraph.get("cn"), str):
            paragraph["cn"] = normalize_chinese_quotes(paragraph["cn"])
    return data


def disallowed_double_quotes(text: str) -> list[str]:
    return [char for char in DISALLOWED_DOUBLE_QUOTES if char in str(text or "")]
