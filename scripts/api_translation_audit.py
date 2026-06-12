#!/usr/bin/env python3
"""Audit API translations against hard project rules.

This script is intentionally deterministic: it checks dictionary hits, currency
mentions, paragraph shape, and obvious web-page noise before an API translation
is accepted. The fulltext API path can use the issue list to ask the model for
a focused repair instead of re-translating the whole article.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio, dict_path
from chinese_punctuation import disallowed_double_quotes
from currency_utils import find_missing_currency, normalize_currency_symbols
from dict_matcher import matched_terms_for_article, term_in_text


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))

EN_CURRENCY_RE = re.compile(
    r"(?ix)"
    r"("
    r"(?:US\$|\$|€|£)\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|thousand|m|bn|k)?"
    r"|"
    r"\d[\d,]*(?:\.\d+)?\s*(?:million|billion|thousand|m|bn|k)?\s*"
    r"(?:US\s*dollars?|U\.S\.\s*dollars?|dollars?|USD|euros?|EUR|pounds?|GBP|yen|JPY)"
    r")"
)

CN_NOISE_PATTERNS = (
    "新闻 • 评测",
    "游戏指南",
    "书籍指南",
    "阵亡将士纪念日促销",
    "乐高套装评测",
    "桌游评测",
    "宝可梦星球",
    "IGN商店",
    "游戏发售日期",
    "MapGenie",
    "HowLongToBeat",
    "Maxroll",
    "Eurogamer",
    "VG247",
    "Rock Paper Shotgun",
    "IGN YouTube",
    "IGN TikTok",
    "隐私政策",
    "使用条款",
    "联系我们",
)

EN_NOISE_PATTERNS = (
    "privacy policy",
    "terms of use",
    "contact us",
    "ign youtube",
    "ign tiktok",
    "howlongtobeat",
    "mapgenie",
    "rock paper shotgun",
    "eurogamer",
    "maxroll",
    "vg247",
)

CN_CALQUE_PATTERNS = (
    (
        re.compile(r"我们究竟(?:要|会)?与[^。！？]{1,40}(?:做什么|干什么)"),
        "literal 'what we do with' structure; translate the contextual interaction or action",
    ),
    (
        re.compile(r"一项[^，。！？]{0,24}(?:期待|想要)[^，。！？]{0,12}(?:选项|选择)"),
        "abstract English noun structure; rewrite as a natural Chinese verb phrase",
    ),
    (
        re.compile(r"(?:自身|本身)和[^，。！？]{1,24}都可以操控"),
        "controllable has no explicit actor; state clearly who controls which subjects",
    ),
)


def default_date() -> str:
    now = datetime.now(CST)
    today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d") if now < today_0800 else (now + timedelta(days=1)).strftime("%Y-%m-%d")


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


def matched_dictionary_terms(text: str, limit: int = 80, article: dict[str, Any] | None = None) -> dict[str, str]:
    return matched_terms_for_article(text, article=article, limit=limit)


def is_effective_chinese_term(cn: str) -> bool:
    """Skip dictionary entries whose "Chinese" value is just an English name."""
    if not cn:
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", cn))


def translation_text(data: dict[str, Any]) -> str:
    parts = [
        str(data.get("cn_title") or ""),
        str(data.get("subtitle") or ""),
        str(data.get("opus_summary") or ""),
    ]
    for para in data.get("paragraphs", []):
        if isinstance(para, dict):
            parts.append(str(para.get("cn") or ""))
        elif isinstance(para, str):
            parts.append(para)
    return "\n".join(parts)


def compact_char_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


SUMMARY_TARGET_MIN = 70
SUMMARY_TARGET_MAX = 80
SUMMARY_HARD_MIN = 60
SUMMARY_HARD_MAX = 110


def source_text_from_paragraphs(paragraphs_en: list[str], article: dict[str, Any] | None = None) -> str:
    title = ""
    if article:
        title = "\n".join(str(article.get(k) or "") for k in ("en_title", "title"))
    return title + "\n" + "\n".join(paragraphs_en)


def check_translation(
    *,
    article: dict[str, Any] | None,
    paragraphs_en: list[str],
    data: dict[str, Any],
    required_terms: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    cn_text = translation_text(data)
    source_text = source_text_from_paragraphs(paragraphs_en, article)
    terms = required_terms or matched_dictionary_terms(source_text, article=article)

    para_items = data.get("paragraphs")
    if not isinstance(para_items, list):
        issues.append({"type": "paragraph_shape", "detail": "paragraphs must be a list"})
    elif len(para_items) != len(paragraphs_en):
        issues.append({
            "type": "paragraph_shape",
            "detail": f"paragraph count mismatch: expected {len(paragraphs_en)}, got {len(para_items)}",
        })

    opus_summary = str(data.get("opus_summary") or "").strip()
    if not opus_summary:
        issues.append({"type": "summary_length", "detail": "opus_summary is missing"})
    else:
        summary_len = compact_char_len(opus_summary)
        if summary_len < SUMMARY_HARD_MIN or summary_len > SUMMARY_HARD_MAX:
            issues.append({
                "type": "summary_length",
                "detail": (
                    f"opus_summary targets {SUMMARY_TARGET_MIN}-{SUMMARY_TARGET_MAX} non-space characters "
                    f"and must stay within {SUMMARY_HARD_MIN}-{SUMMARY_HARD_MAX}, got {summary_len}"
                ),
            })

    bad_quotes = disallowed_double_quotes(cn_text)
    if bad_quotes:
        rendered = " ".join(f"U+{ord(char):04X}" for char in bad_quotes)
        issues.append({
            "type": "punctuation_quotes",
            "detail": f"Chinese translation contains non-corner double quotes ({rendered}); use \u300c\u300d",
        })

    for pattern, detail in CN_CALQUE_PATTERNS:
        match = pattern.search(cn_text)
        if match:
            issues.append({
                "type": "translation_style_calque",
                "detail": f"{detail}: {match.group(0)}",
            })

    for en, cn in terms.items():
        if not is_effective_chinese_term(cn):
            continue
        if cn and cn not in cn_text:
            issues.append({
                "type": "dictionary",
                "detail": f"source contains '{en}', but required dictionary translation '{cn}' is missing",
                "en": en,
                "expected_cn": cn,
            })

    for found, context in find_missing_currency(cn_text):
        issues.append({
            "type": "currency_cn",
            "detail": f"translated text has foreign-currency amount without CNY conversion: {found}",
            "context": context,
        })

    source_currency = EN_CURRENCY_RE.findall(source_text)
    if source_currency and "人民币" not in cn_text:
        preview = ", ".join(source_currency[:5])
        issues.append({
            "type": "currency_source",
            "detail": f"source mentions foreign-currency amount(s), but translation has no CNY conversion: {preview}",
        })

    normalized_cn = normalize_currency_symbols(cn_text)
    if re.search(r"(?i)(US\$|\$|€|£|\bUSD\b|\bEUR\b|\bGBP\b|\bJPY\b)", normalized_cn):
        issues.append({
            "type": "currency_symbol",
            "detail": "translation still contains raw currency symbol/code; convert it to Chinese currency text plus CNY",
        })

    lower_source = source_text.lower()
    for phrase in EN_NOISE_PATTERNS:
        if phrase in lower_source:
            issues.append({
                "type": "source_noise",
                "detail": f"source paragraphs appear to contain web-page noise: {phrase}",
            })
            break

    for phrase in CN_NOISE_PATTERNS:
        if phrase in cn_text:
            issues.append({
                "type": "translation_noise",
                "detail": f"translation contains likely navigation/footer text: {phrase}",
            })
            break

    return issues


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else default_date()
    article_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    if not index_path.exists():
        print(f"API_TRANSLATION_AUDIT_SKIP: no index.json for {date}")
        return 0
    index = load_json(index_path)
    articles = index.get("articles", [])
    targets = [a for a in articles if not article_id or int(a.get("id", -1)) == article_id]
    all_issues: list[tuple[int, dict[str, str]]] = []
    for article in targets:
        aid = int(article.get("id", -1))
        trans_path = day_dir / "translations" / f"{aid:02d}.json"
        if not trans_path.exists():
            continue
        data = load_json(trans_path)
        paragraphs_en = []
        for para in data.get("paragraphs", []):
            if isinstance(para, dict):
                paragraphs_en.append(str(para.get("en") or ""))
        issues = check_translation(article=article, paragraphs_en=paragraphs_en, data=data)
        all_issues.extend((aid, issue) for issue in issues)

    if all_issues:
        print(f"API_TRANSLATION_AUDIT_FAIL: {len(all_issues)} issue(s)")
        for aid, issue in all_issues:
            print(f"  #{aid} [{issue['type']}] {issue['detail']}")
        return 1
    print("API_TRANSLATION_AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
