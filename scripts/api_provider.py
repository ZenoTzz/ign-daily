#!/usr/bin/env python3
"""Helpers for selecting OpenAI-compatible provider credentials."""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit


GENERIC_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})


def provider_from_base_url(base_url: str) -> str:
    value = (base_url or "").lower()
    if "generativelanguage.googleapis.com" in value or "googleapis.com" in value:
        return "gemini"
    if "deepseek" in value:
        return "deepseek"
    return "generic"


def chat_completions_endpoint(base_url: str) -> str:
    """Return the Chat Completions endpoint for an OpenAI-compatible base URL.

    Accept both a normal API root (``.../v1``) and an already-complete endpoint
    so configuration can be copied from either a provider guide or an existing
    deployment without producing a doubled path.
    """
    value = (base_url or "").strip()
    if not value:
        return "/chat/completions"
    parts = urlsplit(value)
    path = parts.path.rstrip("/")
    if path.casefold().endswith("/chat/completions"):
        final_path = path
    else:
        final_path = f"{path}/chat/completions" if path else "/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, final_path, parts.query, parts.fragment))


def is_gpt56_model(model: str) -> bool:
    """Whether *model* is a GPT-5.6 model requiring the newer request shape."""
    return (model or "").strip().casefold().startswith("gpt-5.6")


def normalize_reasoning_effort(value: str | None = None) -> str | None:
    """Normalize the exact GPT-5.6 reasoning scale without collapsing xhigh.

    ``TRANSLATOR_REASONING_EFFORT`` is the preferred variable.  The legacy
    ``TRANSLATOR_THINKING_MODE`` name is accepted so existing workflow wiring
    can be migrated independently.  ``disabled`` maps to the API's explicit
    ``none`` value; unknown values are omitted instead of silently changing the
    requested effort.
    """
    raw = value
    if raw is None:
        raw = os.environ.get("TRANSLATOR_REASONING_EFFORT")
    if raw is None:
        raw = os.environ.get("TRANSLATOR_THINKING_MODE")
    raw = (raw or "").strip().casefold()
    if raw in {"disabled", "off", "false", "no"}:
        return "none"
    return raw if raw in GENERIC_REASONING_EFFORTS else None


def resolve_api_key(base_url: str = "") -> str:
    """Pick the right API key for the configured OpenAI-compatible endpoint."""
    provider = provider_from_base_url(base_url)
    if provider == "gemini":
        candidates = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TRANSLATOR_API_KEY")
    elif provider == "deepseek":
        candidates = ("TRANSLATOR_API_KEY", "DEEPSEEK_API_KEY")
    else:
        # A credential issued for another provider must never be sent to a
        # generic relay merely because it exists in the same environment.
        candidates = ("TRANSLATOR_API_KEY",)
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
    return "TRANSLATOR_API_KEY is not set for the OpenAI-compatible API"
