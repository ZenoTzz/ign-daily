#!/usr/bin/env python3
"""Helpers for selecting OpenAI-compatible provider credentials."""
from __future__ import annotations

import os


def provider_from_base_url(base_url: str) -> str:
    value = (base_url or "").lower()
    if "generativelanguage.googleapis.com" in value or "googleapis.com" in value:
        return "gemini"
    if "deepseek" in value:
        return "deepseek"
    return "generic"


def resolve_api_key(base_url: str = "") -> str:
    """Pick the right API key for the configured OpenAI-compatible endpoint."""
    provider = provider_from_base_url(base_url)
    if provider == "gemini":
        candidates = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TRANSLATOR_API_KEY")
    elif provider == "deepseek":
        candidates = ("TRANSLATOR_API_KEY", "DEEPSEEK_API_KEY")
    else:
        candidates = ("TRANSLATOR_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY")
    for name in candidates:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def api_key_help(base_url: str = "") -> str:
    provider = provider_from_base_url(base_url)
    if provider == "gemini":
        return "GEMINI_API_KEY/GOOGLE_API_KEY is not set for Gemini API"
    if provider == "deepseek":
        return "TRANSLATOR_API_KEY/DEEPSEEK_API_KEY is not set for DeepSeek API"
    return "TRANSLATOR_API_KEY/GEMINI_API_KEY/GOOGLE_API_KEY/DEEPSEEK_API_KEY is not set"
