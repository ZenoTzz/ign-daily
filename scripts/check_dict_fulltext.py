#!/usr/bin/env python3
"""Validate dictionary terms across full source and translation text.

This catches a gap that title-only checks miss: if a source article mentions a
known game, company, or person from data/dict.json, the Chinese translation
must contain the configured Chinese term somewhere in title, summary, subtitle,
body, or translated_terms.

Usage:
  python scripts/check_dict_fulltext.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from common_paths import DATA_DIR, configure_utf8_stdio, dict_path


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))

# Keep this focused on names that materially affect the translated article.
# Broad "terms" and "media" entries have more false positives in source text.
CHECK_CATEGORIES = ("games", "movies_tv", "companies", "people")


def default_date() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def load_terms() -> list[tuple[str, str, str]]:
    payload = json.loads(dict_path().read_text(encoding="utf-8"))
    terms: list[tuple[str, str, str]] = []
    for category in CHECK_CATEGORIES:
        values = payload.get(category, {})
        if not isinstance(values, dict):
            continue
        for en_term, info in values.items():
            if isinstance(info, dict) and info.get("cn"):
                terms.append((str(en_term), str(info["cn"]), category))
    return sorted(terms, key=lambda item: len(item[0]), reverse=True)


def en_pattern(term: str) -> re.Pattern[str]:
    """Match dictionary terms while tolerating punctuation-only source variants.

    IGN titles often vary punctuation around subtitles, for example
    "007 First Light" vs. "007: First Light". The dictionary term remains
    canonical, but source matching must still trigger enforcement.
    """
    pieces = [re.escape(part) for part in re.split(r"[\s:：\\-]+", term) if part]
    if not pieces:
        return re.compile(r"a^")
    flexible = r"[\s:：\\-]+".join(pieces)
    return re.compile(rf"(?<![A-Za-z0-9]){flexible}(?![A-Za-z0-9])", re.I)


def cn_variants(cn_term: str) -> list[str]:
    variants = [cn_term]
    if "/" in cn_term:
        variants.extend(part for part in cn_term.split("/") if part)
    return variants


def source_blob(source: dict) -> str:
    fields = [
        source.get("title_en", ""),
        source.get("summary_en", ""),
        source.get("body_en", ""),
    ]
    fields.extend(source.get("paragraphs_en") or [])
    return "\n".join(str(item) for item in fields if item)


def translation_blob(translation: dict) -> str:
    fields: list[str] = [
        translation.get("cn_title", ""),
        translation.get("subtitle", ""),
        translation.get("opus_summary", ""),
    ]
    for paragraph in translation.get("paragraphs") or []:
        if isinstance(paragraph, dict):
            fields.append(paragraph.get("cn", ""))
    translated_terms = translation.get("translated_terms") or {}
    if isinstance(translated_terms, dict):
        fields.extend(str(value) for value in translated_terms.values())
    return "\n".join(str(item) for item in fields if item)


def done_article_ids(day_dir: Path) -> list[int]:
    index_path = day_dir / "index.json"
    if not index_path.exists():
        return []
    index = json.loads(index_path.read_text(encoding="utf-8"))
    return [
        int(article["id"])
        for article in index.get("articles", [])
        if article.get("translation_status") == "done"
    ]


def find_misses(date: str) -> list[dict[str, str]]:
    day_dir = DATA_DIR / date
    terms = load_terms()
    misses: list[dict[str, str]] = []

    for article_id in done_article_ids(day_dir):
        source_path = day_dir / "sources" / f"{article_id:02d}.json"
        translation_path = day_dir / "translations" / f"{article_id:02d}.json"
        if not source_path.exists() or not translation_path.exists():
            continue

        source = json.loads(source_path.read_text(encoding="utf-8"))
        translation = json.loads(translation_path.read_text(encoding="utf-8"))
        source_text = source_blob(source)
        translated_text = translation_blob(translation)

        for en_term, cn_term, category in terms:
            match = en_pattern(en_term).search(source_text)
            if not match:
                continue
            if (
                category in ("games", "movies_tv")
                and " " not in en_term
                and not en_term.islower()
                and match.group(0).islower()
            ):
                continue
            if any(variant in translated_text for variant in cn_variants(cn_term)):
                continue
            misses.append(
                {
                    "id": str(article_id),
                    "title": translation.get("cn_title", ""),
                    "category": category,
                    "en": en_term,
                    "cn": cn_term,
                }
            )
    return misses


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = list(argv)
    date = args[0] if args else default_date()
    misses = find_misses(date)
    if not misses:
        print(f"DICT_FULLTEXT_OK: all checked terms present in {date}.")
        return 0

    print(f"DICT_FULLTEXT_MISMATCH: {len(misses)} missing term(s) in {date}:")
    for miss in misses:
        print(
            f"  #{miss['id']} [{miss['category']}] "
            f"{miss['en']} -> {miss['cn']}"
        )
        print(f"       current: {miss['title']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
