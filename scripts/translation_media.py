"""Shared helpers for preserving cached source media in translation files."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def image_url(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("url") or "").strip()
    return ""


def valid_image_url(value: Any) -> bool:
    return image_url(value).startswith(("https://", "http://"))


def image_key(value: Any) -> str:
    """Identify transformed variants of the same IGN asset as one image."""
    url = image_url(value)
    if not valid_image_url(url):
        return ""
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", ""))


def normalize_image(value: Any) -> dict[str, str] | None:
    url = image_url(value)
    if not valid_image_url(url):
        return None
    caption = str(value.get("caption") or "").strip() if isinstance(value, dict) else ""
    return {"url": url, "caption": caption}


def merge_images(existing: Any, source: Any) -> list[dict[str, str]]:
    """Keep translated captions while appending every missing cached source asset."""
    merged: list[dict[str, str]] = []
    positions: dict[str, int] = {}
    for collection in (existing, source):
        if not isinstance(collection, list):
            continue
        for value in collection:
            item = normalize_image(value)
            if item is None:
                continue
            key = image_key(item)
            if key in positions:
                current = merged[positions[key]]
                if not current["caption"] and item["caption"]:
                    current["caption"] = item["caption"]
                continue
            positions[key] = len(merged)
            merged.append(item)
    return merged


def missing_source_images(translation_images: Any, source_images: Any) -> list[str]:
    translated = {image_key(item) for item in translation_images or []} if isinstance(translation_images, list) else set()
    missing: list[str] = []
    seen: set[str] = set()
    if not isinstance(source_images, list):
        return missing
    for item in source_images:
        key = image_key(item)
        if key and key not in translated and key not in seen:
            missing.append(image_url(item))
            seen.add(key)
    return missing
