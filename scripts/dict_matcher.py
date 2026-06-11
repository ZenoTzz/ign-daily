"""Dictionary matching helpers with article-category context."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common_paths import dict_path


DICT_CATEGORIES = ("games", "movies_tv", "companies", "people", "media", "terms")
DICT_SOURCES = ("user", "ign_cn", "bilibili", "consensus", "ai_guess")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def flatten_dict_terms() -> dict[str, str]:
    path = dict_path()
    if not path.exists():
        return {}
    data = load_json(path)
    terms: dict[str, str] = {}
    for cat, items in data.items():
        if cat == "_meta" or not isinstance(items, dict):
            continue
        for en, value in items.items():
            if isinstance(value, dict) and value.get("cn"):
                terms[en] = str(value["cn"])
            elif isinstance(value, str):
                terms[en] = value
    return terms


def normalize_pending_dict(
    items: Any,
    *,
    default_category: str = "terms",
    default_source: str = "ai_guess",
) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        en = str(item.get("en") or "").strip()
        cn = str(item.get("cn") or "").strip()
        if not en or not cn:
            continue
        category = str(item.get("cat") or item.get("category") or default_category).strip()
        if category not in DICT_CATEGORIES:
            category = default_category
        source = str(item.get("source") or default_source).strip()
        if source not in DICT_SOURCES:
            source = default_source
        row = dict(item)
        row["en"] = en
        row["cn"] = cn
        row["cat"] = category
        row["source"] = source
        normalized.append(row)
    return normalized


def spacing_sensitive_cn_terms() -> list[str]:
    terms = []
    for cn in flatten_dict_terms().values():
        text = str(cn or "").strip()
        if re.search(r"[A-Za-z0-9]\s+[\u4e00-\u9fff]", text):
            terms.append(text)
    return sorted(set(terms), key=len, reverse=True)


def restore_dictionary_spacing(text: str) -> str:
    """Restore significant spaces inside dictionary translations."""
    if not text:
        return text
    result = str(text)
    for term in spacing_sensitive_cn_terms():
        compact = re.sub(r"\s+", "", term)
        if compact and compact != term:
            result = result.replace(compact, term)
    return result


def restore_dictionary_spacing_in_data(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("cn_title", "subtitle", "opus_summary", "summary"):
        if isinstance(data.get(key), str):
            data[key] = restore_dictionary_spacing(data[key])
    for para in data.get("paragraphs", []):
        if isinstance(para, dict) and isinstance(para.get("cn"), str):
            para["cn"] = restore_dictionary_spacing(para["cn"])
    return data


def iter_dict_terms() -> list[tuple[str, str, str]]:
    path = dict_path()
    if not path.exists():
        return []
    data = load_json(path)
    rows: list[tuple[str, str, str]] = []
    for cat, items in data.items():
        if cat == "_meta" or not isinstance(items, dict):
            continue
        for en, value in items.items():
            cn = ""
            if isinstance(value, dict) and value.get("cn"):
                cn = str(value["cn"])
            elif isinstance(value, str):
                cn = value
            if en and cn:
                rows.append((en, cn, cat))
    return rows


def term_in_text(en_term: str, text: str, *, case_sensitive: bool = False) -> bool:
    pattern = r"(?<![A-Za-z0-9])" + re.escape(en_term) + r"(?![A-Za-z0-9])"
    flags = 0 if case_sensitive else re.I
    return re.search(pattern, text or "", flags=flags) is not None


def article_category(article: dict[str, Any] | None) -> str:
    if not article:
        return ""
    return str(article.get("category") or article.get("type") or "").strip().lower()


def category_allows_term(dict_category: str, article: dict[str, Any] | None) -> bool:
    category = article_category(article)
    if not category:
        return True

    is_movie_article = any(marker in category for marker in ("\u5f71\u89c6", "\u7535\u5f71", "tv", "movie", "film"))
    is_game_article = any(marker in category for marker in ("\u6e38\u620f", "game"))

    if is_movie_article and dict_category == "games":
        return False
    if is_game_article and dict_category == "movies_tv":
        return False
    return True


def term_matches(en_term: str, text: str, dict_category: str) -> bool:
    source = text or ""
    if en_term == "Doom" and re.search(r"(?<![A-Za-z0-9])Dr\.?\s+Doom(?![A-Za-z0-9])", source):
        return False

    title_like_categories = {"games", "movies_tv", "media"}
    case_sensitive = dict_category in title_like_categories
    return term_in_text(en_term, source, case_sensitive=case_sensitive)


def matched_terms_for_article(text: str, article: dict[str, Any] | None = None, limit: int = 60) -> dict[str, str]:
    hits: dict[str, str] = {}
    for en, cn, cat in sorted(iter_dict_terms(), key=lambda row: len(row[0]), reverse=True):
        if not category_allows_term(cat, article):
            continue
        if term_matches(en, text, cat):
            hits[en] = cn
        if len(hits) >= limit:
            break
    return hits
