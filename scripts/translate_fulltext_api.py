#!/usr/bin/env python3
"""Translate requested full articles with an OpenAI-compatible chat API.

This is a guarded automation path. Good translations are finalized as normal.
If the deterministic audit rejects a model output, the draft is saved as a
manual-review translation, the request is removed from the hourly queue, and the
failure reason is written to data/YYYY-MM-DD/translation_failures.json. This
prevents the same article/model/error from burning tokens every hour.

Usage:
  TRANSLATOR_API_KEY=... python3 scripts/translate_fulltext_api.py [YYYY-MM-DD|--all]
"""
from __future__ import annotations

import json
import os
import re
import hashlib
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio, dict_path, env_paths
from api_translation_audit import SUMMARY_HARD_MAX, SUMMARY_TARGET_MAX, check_translation, compact_char_len
from audit_doctor import diagnose as diagnose_audit_failure
from chinese_punctuation import normalize_translation_quotes
from currency_utils import normalize_translation_currency
from dict_matcher import restore_dictionary_spacing_in_data, term_in_text
from dict_matcher import matched_terms_for_article
from dict_matcher import normalize_pending_dict
from normalize_currency_files import normalize_date as normalize_currency_date
from platform_names import normalize_platform_names_in_translation
from prompt_blocks import (
    chunk_user_payload,
    fulltext_user_payload,
    stable_json,
    translation_system_prompt,
    with_translation_style,
)
from translate_titles_deepseek import apply_title_dictionary, call_deepseek_response, extract_article_text, extract_json, flatten_dict_terms
from usage_logger import record_deepseek_usage_safe


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"


def load_env_file() -> None:
    for path in env_paths():
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def default_date() -> str:
    now = datetime.now(CST)
    today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d") if now < today_0800 else (now + timedelta(days=1)).strftime("%Y-%m-%d")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(CST).isoformat()


def failure_path(date: str) -> Path:
    return DATA_DIR / date / "translation_failures.json"


def failure_fingerprint(article: dict[str, Any], model: str, issues: list[dict[str, str]] | None, text: str) -> str:
    payload = {
        "id": article.get("id"),
        "url": article.get("url"),
        "model": model,
        "issue_types": [x.get("type") for x in (issues or [])],
        "issue_details": [x.get("detail") for x in (issues or [])][:8],
        "source_sha1": hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_failures(date: str) -> dict[str, Any]:
    path = failure_path(date)
    if not path.exists():
        return {"date": date, "items": {}}
    try:
        data = load_json(path)
    except Exception:
        return {"date": date, "items": {}}
    if not isinstance(data, dict):
        return {"date": date, "items": {}}
    data.setdefault("date", date)
    data.setdefault("items", {})
    return data


def save_manual_review_failure(
    *,
    date: str,
    index: dict[str, Any],
    req_path: Path,
    req: dict[str, Any],
    article: dict[str, Any],
    model: str,
    text: str,
    issues: list[dict[str, str]] | None,
    details: str,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aid = int(article["id"])
    ts = now_iso()
    fp = failure_fingerprint(article, model, issues, text)
    trans_rel = f"translations/{aid:02d}.json" if draft else ""

    if draft:
        draft["quality_status"] = "needs_manual_review"
        draft["manual_release_required"] = True
        draft["audit_issues"] = issues or []
        draft["audit_failed_at"] = ts
        draft["audit_failure_reason"] = details
        write_json(DATA_DIR / date / trans_rel, draft)

    failures = load_failures(date)
    failures["updated_at"] = ts
    failures.setdefault("items", {})[str(aid)] = {
        "id": aid,
        "url": article.get("url"),
        "en_title": article.get("en_title"),
        "cn_title": (draft or article).get("cn_title") or article.get("cn_title") or article.get("en_title"),
        "model": model,
        "status": "needs_manual_review",
        "failed_at": ts,
        "reason": details,
        "audit_issues": issues or [],
        "fingerprint": fp,
        "translation_path": trans_rel,
        "retry_policy": "manual_only",
    }
    write_json(failure_path(date), failures)

    for item in index.get("articles", []):
        if int(item.get("id", -1)) != aid:
            continue
        item["translation_status"] = "needs_review"
        item["translation_error"] = details
        item["translation_failed_at"] = ts
        item["translator"] = "api"
        item["translator_provider"] = "openai-compatible"
        item["translator_model"] = model
        if trans_rel:
            item["translation_path"] = trans_rel
        if draft:
            if draft.get("cn_title"):
                item["cn_title"] = draft["cn_title"]
            if draft.get("opus_summary"):
                item["summary"] = draft["opus_summary"]
            elif draft.get("summary"):
                item["summary"] = draft["summary"]
            if draft.get("cover"):
                item["cover_image"] = draft["cover"]
        break
    write_json(DATA_DIR / date / "index.json", index)

    req = remove_completed_request(req, article)
    write_json(req_path, req)
    print(f"[REVIEW] fulltext #{aid} saved for manual review: {details}")
    return req


def clear_manual_review_failure(date: str, article_id: int) -> None:
    path = failure_path(date)
    if not path.exists():
        return
    failures = load_failures(date)
    items = failures.get("items", {})
    if str(article_id) not in items:
        return
    del items[str(article_id)]
    failures["updated_at"] = now_iso()
    write_json(path, failures)


def fetch_article_text(url: str, max_chars: int = 18000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return extract_article_text(html, max_chars)


def cached_source_path(date: str, article: dict[str, Any]) -> Path:
    return DATA_DIR / date / "sources" / f"{int(article['id']):02d}.json"


def load_cached_source(date: str, article: dict[str, Any]) -> dict[str, Any]:
    path = cached_source_path(date, article)
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def source_text(source: dict[str, Any]) -> str:
    body = str(source.get("body_en") or "").strip()
    if body:
        return body
    paragraphs = source.get("paragraphs_en")
    if isinstance(paragraphs, list):
        return "\n\n".join(str(p).strip() for p in paragraphs if str(p).strip())
    return ""


def split_paragraphs(text: str) -> list[str]:
    chunks = [p.strip() for p in re.split(r"\n{1,}", text) if p.strip()]
    bad = (
        "advertisement",
        "ign recommends",
        "continue reading",
        "sign up",
        "privacy policy",
        "terms of use",
        "contact us",
        "howlongtobeat",
        "mapgenie",
        "ign youtube",
    )
    return [p for p in chunks if len(p) >= 40 and not any(b in p.lower() for b in bad)][:35]


def matched_terms(text: str, limit: int = 60, article: dict[str, Any] | None = None) -> dict[str, str]:
    return matched_terms_for_article(text, article=article, limit=limit)


def read_optional(path: str, max_chars: int = 10000) -> str:
    p = REPO_ROOT / path
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")[:max_chars]


def hard_checklist(paragraphs: list[str], terms: dict[str, str]) -> dict[str, Any]:
    source = "\n".join(paragraphs)
    currency_hits = re.findall(
        r"(?i)(?:US\$|\$|€|£)\s*\d[\d,]*(?:\.\d+)?\s*(?:million|billion|thousand|m|bn|k)?|"
        r"\d[\d,]*(?:\.\d+)?\s*(?:million|billion|thousand|m|bn|k)?\s*"
        r"(?:US\s*dollars?|U\.S\.\s*dollars?|dollars?|USD|euros?|EUR|pounds?|GBP|yen|JPY)",
        source,
    )
    return {
        "must_use_dictionary_terms": terms,
        "foreign_currency_mentions_in_source": currency_hits[:30],
        "currency_rule": "Every foreign-currency amount must be rendered as foreign amount plus CNY conversion, e.g. 2.5亿美元(约合人民币18亿元).",
        "opus_summary_length_rule": "opus_summary must be a concise Chinese summary of 70-80 non-space characters.",
        "paragraph_count": len(paragraphs),
        "do_not_translate_or_include_web_noise": [
            "navigation menus",
            "privacy policy",
            "terms of use",
            "contact us",
            "IGN YouTube/TikTok/X links",
            "HowLongToBeat/MapGenie/Eurogamer/VG247 footer links",
        ],
    }


def build_messages(article: dict[str, Any], paragraphs: list[str], terms: dict[str, str]) -> list[dict[str, str]]:
    user = fulltext_user_payload(article=article, paragraphs=paragraphs, terms=terms)
    user["hard_checklist"] = hard_checklist(paragraphs, terms)
    return [
        {"role": "system", "content": translation_system_prompt()},
        {"role": "user", "content": stable_json(user)},
    ]


def build_repair_messages(
    article: dict[str, Any],
    paragraphs_en: list[str],
    data: dict[str, Any],
    terms: dict[str, str],
    issues: list[dict[str, str]],
) -> list[dict[str, str]]:
    payload = with_translation_style({
        "task": {
            "name": "repair_translation",
            "instructions": [
                "保持原译文整体不变，只修复审计列出的问题。",
                "必须保留 paragraphs 数量和顺序。",
                "必须使用词库译名，所有外币金额必须补人民币换算。",
                "必须删除导航、页脚和广告噪音。",
                "只输出严格 JSON，不要 Markdown。",
            ],
        },
        "article": {
            "id": article.get("id"),
            "url": article.get("url"),
            "en_title": article.get("en_title"),
        },
        "hard_checklist": hard_checklist(paragraphs_en, terms),
        "audit_issues": issues,
        "current_translation_json": data,
        "required_json_schema": {
            "id": article.get("id"),
            "url": article.get("url"),
            "en_title": article.get("en_title"),
            "cn_title": "中文标题",
            "subtitle": "2-15字中文短副标题",
            "opus_summary": "70-80个中文字符左右的极简总结",
            "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
            "paragraphs": [{"en": "原文段落", "cn": "修复后的中文译文"}],
            "pending_dict": [],
            "translated_terms": {},
            "cover": "",
            "images": [],
        },
    })
    return [
        {"role": "system", "content": translation_system_prompt()},
        {"role": "user", "content": stable_json(payload)},
    ]


def build_summary_repair_messages(
    article: dict[str, Any],
    paragraphs_en: list[str],
    data: dict[str, Any],
) -> list[dict[str, str]]:
    payload = with_translation_style({
        "task": {
            "name": "repair_summary_only",
            "instructions": [
                "只改写 opus_summary，不得改动标题、正文或其他字段。",
                "摘要必须忠实概括文章核心事实。",
                "长度为70-80个非空白中文字符。",
                "只输出严格 JSON，不要 Markdown。",
            ],
        },
        "article": {
            "en_title": article.get("en_title"),
            "cn_title": data.get("cn_title") or article.get("cn_title"),
        },
        "current_opus_summary": data.get("opus_summary", ""),
        "source_paragraphs_en": paragraphs_en,
        "translated_paragraphs_cn": [
            str(item.get("cn") or "")
            for item in data.get("paragraphs", [])
            if isinstance(item, dict)
        ],
        "required_json_schema": {
            "opus_summary": "忠实、自然的70-80个非空白中文字符摘要",
        },
    })
    return [
        {"role": "system", "content": translation_system_prompt()},
        {"role": "user", "content": stable_json(payload)},
    ]


def extract_paragraph_items(result: dict[str, Any]) -> list[Any]:
    for key in ("paragraphs", "translated_paragraphs", "translations", "body_paragraphs"):
        value = result.get(key)
        if isinstance(value, list) and value:
            return value
    body = result.get("body") or result.get("content") or result.get("cn_body")
    if isinstance(body, str) and body.strip():
        return [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]
    return []


def normalize_paragraphs(result: dict[str, Any], paragraphs_en: list[str]) -> list[dict[str, str]]:
    items = extract_paragraph_items(result)
    if not items:
        raise ValueError("model returned empty paragraphs")

    normalized = []
    for i, en in enumerate(paragraphs_en):
        item = items[i] if i < len(items) else None
        if isinstance(item, dict):
            cn = str(item.get("cn") or item.get("zh") or item.get("translation") or item.get("text") or "").strip()
        elif isinstance(item, str):
            cn = item.strip()
        else:
            cn = ""
        if not cn:
            raise ValueError(f"paragraph {i + 1} missing cn")
        normalized.append({"en": en, "cn": cn})
    return normalized


def build_chunk_messages(article: dict[str, Any], chunk: list[tuple[int, str]], terms: dict[str, str]) -> list[dict[str, str]]:
    user = chunk_user_payload(article=article, chunk=chunk, terms=terms)
    return [
        {"role": "system", "content": translation_system_prompt()},
        {"role": "user", "content": stable_json(user)},
    ]


def translate_paragraph_chunks(
    api_key: str,
    model: str,
    base_url: str,
    article: dict[str, Any],
    paragraphs_en: list[str],
    terms: dict[str, str],
    article_date: str | None = None,
) -> list[dict[str, str]]:
    translated: dict[int, str] = {}
    chunk_size = int(os.environ.get("TRANSLATOR_FULLTEXT_CHUNK_SIZE", "6"))
    indexed = list(enumerate(paragraphs_en, start=1))

    def translate_chunk(chunk: list[tuple[int, str]]) -> None:
        raw, usage = call_deepseek_response(
            api_key,
            model,
            base_url,
            build_chunk_messages(article, chunk, terms),
            max_tokens=int(os.environ.get("TRANSLATOR_FULLTEXT_CHUNK_MAX_TOKENS", "4000")),
        )
        record_deepseek_usage_safe(
            task="fulltext_chunk",
            model=model,
            usage=usage,
            article_id=article.get("id"),
            article_title=article.get("cn_title") or article.get("en_title"),
            article_url=article.get("url"),
            article_date=article_date,
            detail=f"paragraphs {chunk[0][0]}-{chunk[-1][0]}",
        )
        result = extract_json(raw)
        items = extract_paragraph_items(result)
        if len(items) < len(chunk):
            raise ValueError(f"chunk returned {len(items)} paragraphs, expected {len(chunk)}")
        for fallback, item in zip(chunk, items):
            fallback_idx = fallback[0]
            if isinstance(item, dict):
                idx = int(item.get("index") or fallback_idx)
                cn = str(item.get("cn") or item.get("zh") or item.get("translation") or item.get("text") or "").strip()
            else:
                idx = fallback_idx
                cn = str(item).strip()
            if not cn:
                raise ValueError(f"chunk paragraph {idx} missing cn")
            translated[idx] = cn

    for start in range(0, len(indexed), chunk_size):
        chunk = indexed[start:start + chunk_size]
        try:
            translate_chunk(chunk)
        except Exception as exc:
            if len(chunk) == 1:
                idx, en = chunk[0]
                translated[idx] = f"[MANUAL_TRANSLATION_REQUIRED] {en}"
                print(f"[REVIEW] fulltext #{article.get('id')} paragraph {idx} still failed after single retry: {exc}; keeping a review draft")
                return
            print(f"[RETRY] fulltext #{article.get('id')} chunk {chunk[0][0]}-{chunk[-1][0]} failed: {exc}; retrying one paragraph at a time")
            for single in chunk:
                try:
                    translate_chunk([single])
                except Exception as single_exc:
                    idx, en = single
                    translated[idx] = f"[MANUAL_TRANSLATION_REQUIRED] {en}"
                    print(f"[REVIEW] fulltext #{article.get('id')} paragraph {idx} failed after single retry: {single_exc}; keeping a review draft")
    return [{"en": en, "cn": translated[i]} for i, en in indexed]


def normalize_translation(article: dict[str, Any], result: dict[str, Any], paragraphs_en: list[str]) -> dict[str, Any]:
    normalized = normalize_paragraphs(result, paragraphs_en)
    return normalize_platform_names_in_translation(normalize_translation_quotes(restore_dictionary_spacing_in_data(normalize_translation_currency({
        "id": article["id"],
        "url": article["url"],
        "en_title": article["en_title"],
        "cn_title": apply_title_dictionary(
            article.get("en_title", ""),
            str(result.get("cn_title") or article.get("cn_title") or article["en_title"]).strip(),
        ),
        "subtitle": str(result.get("subtitle") or article.get("subtitle") or "看点来了").strip(),
        "opus_summary": str(result.get("opus_summary") or result.get("summary") or article.get("summary") or article.get("cn_title") or "").strip(),
        "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
        "paragraphs": normalized,
        "pending_dict": normalize_pending_dict(result.get("pending_dict")),
        "translated_terms": result.get("translated_terms") if isinstance(result.get("translated_terms"), dict) else {},
        "cover": str(result.get("cover") or article.get("cover_image") or "").strip(),
        "images": result.get("images") if isinstance(result.get("images"), list) else [],
    }))))


def trim_summary_to_limit(summary: str, target_max: int = SUMMARY_TARGET_MAX) -> str:
    """Shorten an overlong summary without spending another API call."""
    text = re.sub(r"\s+", " ", str(summary or "")).strip()
    if compact_char_len(text) <= SUMMARY_HARD_MAX:
        return text

    clauses = re.findall(r".+?(?:[\u3002\uff01\uff1f\uff1b\uff0c]|$)", text)
    kept: list[str] = []
    for clause in clauses:
        candidate = "".join(kept) + clause
        if compact_char_len(candidate) > target_max:
            break
        kept.append(clause)

    shortened = "".join(kept).rstrip("\uff0c\u3001\uff1b\uff1a:,. ")
    if compact_char_len(shortened) < 60:
        # A single long clause is unusual; retain a readable prefix and avoid
        # ending in the middle of an ASCII word or number.
        shortened = text[: target_max - 1].rstrip()
        shortened = re.sub(r"[A-Za-z0-9]+$", "", shortened).rstrip("\uff0c\u3001\uff1b\uff1a:,. ")
    if shortened and shortened[-1] not in "。！？":
        shortened += "。"
    return shortened


def enforce_literal_dictionary_terms(
    data: dict[str, Any],
    paragraphs_en: list[str],
    required_terms: dict[str, str],
) -> dict[str, Any]:
    """Replace an English term when the matching translated field kept it verbatim."""
    repaired = dict(data)
    repaired["paragraphs"] = [
        dict(item) if isinstance(item, dict) else item
        for item in data.get("paragraphs", [])
    ]
    fields = ("cn_title", "subtitle", "opus_summary")
    for en, cn in required_terms.items():
        visible_text = "\n".join(
            [str(repaired.get(key) or "") for key in fields]
            + [
                str(item.get("cn") or "")
                for item in repaired["paragraphs"]
                if isinstance(item, dict)
            ]
        )
        if not en or not cn or cn in visible_text:
            continue
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(en) + r"(?![A-Za-z0-9])", re.I)
        for key in fields:
            value = repaired.get(key)
            if isinstance(value, str) and pattern.search(value):
                repaired[key] = pattern.sub(cn, value)
        for source, item in zip(paragraphs_en, repaired["paragraphs"]):
            if not isinstance(item, dict) or not term_in_text(en, source):
                continue
            value = item.get("cn")
            if isinstance(value, str) and pattern.search(value):
                item["cn"] = pattern.sub(cn, value)
    return normalize_platform_names_in_translation(restore_dictionary_spacing_in_data(repaired))


def repair_translation_once(
    api_key: str,
    model: str,
    base_url: str,
    article: dict[str, Any],
    paragraphs_en: list[str],
    terms: dict[str, str],
    data: dict[str, Any],
    issues: list[dict[str, str]],
    article_date: str,
) -> dict[str, Any]:
    raw, usage = call_deepseek_response(
        api_key,
        model,
        base_url,
        build_repair_messages(article, paragraphs_en, data, terms, issues),
        max_tokens=int(os.environ.get("TRANSLATOR_FULLTEXT_REPAIR_MAX_TOKENS", "12000")),
    )
    record_deepseek_usage_safe(
        task="fulltext_repair",
        model=model,
        usage=usage,
        article_id=article.get("id"),
        article_title=article.get("cn_title") or article.get("en_title"),
        article_url=article.get("url"),
        article_date=article_date,
        detail=f"{len(issues)} audit issue(s)",
    )
    repaired = normalize_translation(article, extract_json(raw), paragraphs_en)
    repaired["repair_source"] = "api_audit"
    repaired["repair_issue_count"] = len(issues)
    return repaired


def repair_summary_once(
    api_key: str,
    model: str,
    base_url: str,
    article: dict[str, Any],
    paragraphs_en: list[str],
    data: dict[str, Any],
    article_date: str,
) -> dict[str, Any]:
    summary = trim_summary_to_limit(str(data.get("opus_summary") or ""))
    if not summary:
        raise ValueError("summary repair returned empty opus_summary")
    repaired = dict(data)
    repaired["opus_summary"] = summary
    repaired["repair_source"] = "deterministic_summary_audit"
    repaired["repair_issue_count"] = 1
    return normalize_platform_names_in_translation(restore_dictionary_spacing_in_data(normalize_translation_currency(repaired)))


def resolve_requests(date: str) -> tuple[Path, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    day_dir = DATA_DIR / date
    index = load_json(day_dir / "index.json")
    req_path = day_dir / "requests.json"
    if not req_path.exists():
        return req_path, index, {"date": date, "requested_ids": [], "requested_articles": []}, []
    req = load_json(req_path)
    by_url = {a.get("url"): a for a in index.get("articles", []) if a.get("url")}
    by_id = {a.get("id"): a for a in index.get("articles", [])}
    requested = []
    seen = set()
    for item in req.get("requested_articles", []):
        art = by_url.get(item.get("url")) or by_id.get(item.get("id"))
        if art and art.get("translation_status") != "done" and art.get("url") not in seen:
            requested.append(art)
            seen.add(art.get("url"))
    for aid in req.get("requested_ids", []):
        art = by_id.get(aid)
        if art and art.get("translation_status") != "done" and art.get("url") not in seen:
            requested.append(art)
            seen.add(art.get("url"))
    return req_path, index, req, requested


def remove_completed_request(req: dict[str, Any], article: dict[str, Any]) -> dict[str, Any]:
    url = article.get("url")
    aid = article.get("id")
    req["requested_ids"] = [x for x in req.get("requested_ids", []) if x != aid]
    req["requested_articles"] = [x for x in req.get("requested_articles", []) if x.get("url") != url and x.get("id") != aid]
    return req


def translate_date(date: str, limit: int = 2) -> int:
    load_env_file()
    api_key = (os.environ.get("TRANSLATOR_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        print("API_FULLTEXT_SKIP: TRANSLATOR_API_KEY/DEEPSEEK_API_KEY is not set")
        return 0
    model = (os.environ.get("TRANSLATOR_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "").strip() or DEFAULT_MODEL
    repair_model = (os.environ.get("TRANSLATOR_REPAIR_MODEL") or "").strip()
    if not repair_model:
        repair_model = "deepseek-v4-pro" if model == "deepseek-v4-flash" else model
    base_url = (os.environ.get("TRANSLATOR_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL
    req_path, index, req, requested = resolve_requests(date)
    if not requested:
        print(f"API_FULLTEXT_SKIP: no requested articles for {date}")
        return 0
    translated = 0
    started = time.monotonic()
    budget_seconds = int(os.environ.get("TRANSLATOR_FULLTEXT_TIME_BUDGET_SECONDS", "1200"))
    for article in requested[:limit]:
        if time.monotonic() - started > budget_seconds:
            print(f"API_FULLTEXT_PAUSE: time budget reached after {translated} article(s)")
            break
        source = load_cached_source(date, article)
        text = ""
        data: dict[str, Any] | None = None
        audit_issues: list[dict[str, str]] = []
        try:
            text = source_text(source) or fetch_article_text(article["url"])
            paragraphs_en = split_paragraphs(text)
            if not paragraphs_en:
                raise RuntimeError(f"no paragraphs extracted for #{article['id']}")
            terms = matched_terms(article.get("en_title", "") + "\n" + text, article=article)
            max_tokens = int(os.environ.get("TRANSLATOR_FULLTEXT_MAX_TOKENS", "12000"))
            raw, usage = call_deepseek_response(api_key, model, base_url, build_messages(article, paragraphs_en, terms), max_tokens=max_tokens)
            record_deepseek_usage_safe(
                task="fulltext",
                model=model,
                usage=usage,
                article_id=article.get("id"),
                article_title=article.get("cn_title") or article.get("en_title"),
                article_url=article.get("url"),
                article_date=date,
            )
            try:
                result = extract_json(raw)
            except Exception as exc:
                print(f"[RETRY] fulltext #{article['id']} returned invalid JSON: {exc}; falling back to paragraph chunks")
                result = {
                    "cn_title": article.get("cn_title") or article.get("en_title") or "",
                    "subtitle": article.get("subtitle") or "",
                    "opus_summary": article.get("summary") or article.get("cn_title") or "",
                    "paragraphs": translate_paragraph_chunks(api_key, model, base_url, article, paragraphs_en, terms, article_date=date),
                    "pending_dict": [],
                    "translated_terms": {},
                    "cover": article.get("cover_image") or "",
                    "images": [],
                }
            try:
                data = normalize_translation(article, result, paragraphs_en)
            except ValueError as exc:
                print(f"[RETRY] fulltext #{article['id']} paragraph format issue: {exc}")
                data = normalize_translation(article, {**result, "paragraphs": translate_paragraph_chunks(api_key, model, base_url, article, paragraphs_en, terms, article_date=date)}, paragraphs_en)
            data = enforce_literal_dictionary_terms(data, paragraphs_en, terms)
            data["opus_summary"] = trim_summary_to_limit(data.get("opus_summary", ""))
            data["translator"] = "api"
            data["translator_provider"] = "openai-compatible"
            data["translator_model"] = model
            if source:
                if not data.get("cover") and source.get("cover_image"):
                    data["cover"] = source["cover_image"]
                if not data.get("images") and isinstance(source.get("images"), list):
                    data["images"] = source["images"]
            audit_issues = check_translation(article=article, paragraphs_en=paragraphs_en, data=data, required_terms=terms)
            if audit_issues and os.environ.get("TRANSLATOR_FULLTEXT_REPAIR", "1") != "0":
                summary_only = all(issue.get("type") == "summary_length" for issue in audit_issues)
                if summary_only:
                    print(f"[REPAIR] fulltext #{article['id']} only needs a summary repair; preserving all paragraphs")
                    data = repair_summary_once(api_key, repair_model, base_url, article, paragraphs_en, data, date)
                else:
                    print(f"[REPAIR] fulltext #{article['id']} audit found {len(audit_issues)} issue(s); asking {repair_model} for focused repair")
                    data = repair_translation_once(api_key, repair_model, base_url, article, paragraphs_en, terms, data, audit_issues, date)
                data = enforce_literal_dictionary_terms(data, paragraphs_en, terms)
                data["opus_summary"] = trim_summary_to_limit(data.get("opus_summary", ""))
                data["translator"] = "api"
                data["translator_provider"] = "openai-compatible"
                data["translator_model"] = model
                if source:
                    if not data.get("cover") and source.get("cover_image"):
                        data["cover"] = source["cover_image"]
                    if not data.get("images") and isinstance(source.get("images"), list):
                        data["images"] = source["images"]
                audit_issues = check_translation(article=article, paragraphs_en=paragraphs_en, data=data, required_terms=terms)
            if audit_issues:
                doctor = diagnose_audit_failure(
                    article=article,
                    paragraphs_en=paragraphs_en,
                    issues=audit_issues,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                )
                if doctor.get("verdict") == "false_positive" and doctor.get("confidence") in {"medium", "high"}:
                    data["audit_doctor"] = doctor
                    print(f"[DOCTOR] fulltext #{article['id']} accepted audit false positive: {doctor.get('reason', '')}")
                else:
                    details = "; ".join(f"[{issue['type']}] {issue['detail']}" for issue in audit_issues[:8])
                    req = save_manual_review_failure(
                        date=date,
                        index=index,
                        req_path=req_path,
                        req=req,
                        article=article,
                        model=model,
                        text=text,
                        issues=audit_issues,
                        details=details,
                        draft=data,
                    )
                    continue
            trans_path = DATA_DIR / date / "translations" / f"{article['id']:02d}.json"
            write_json(trans_path, data)
            subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "translate_pipeline.py"), date, str(article["id"]), "--post"], cwd=REPO_ROOT, check=True)
            article["translation_status"] = "done"
            article["translation_path"] = f"translations/{article['id']:02d}.json"
            article["translator"] = "api"
            article["translator_provider"] = "openai-compatible"
            article["translator_model"] = model
            article.pop("translation_error", None)
            article.pop("translation_failed_at", None)
            normalize_currency_date(date)
            req = remove_completed_request(req, article)
            write_json(req_path, req)
            clear_manual_review_failure(date, int(article["id"]))
            translated += 1
            print(f"[OK] fulltext #{article['id']} {data['cn_title']}")
        except Exception as exc:
            details = str(exc)
            req = save_manual_review_failure(
                date=date,
                index=index,
                req_path=req_path,
                req=req,
                article=article,
                model=model,
                text=text,
                issues=audit_issues,
                details=details,
                draft=data,
            )
    print(f"API_FULLTEXT_TRANSLATE_DONE: date={date}, translated={translated}")
    return translated


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else default_date()
    limit = int(os.environ.get("TRANSLATOR_FULLTEXT_LIMIT", "5"))
    if target == "--all":
        total = 0
        for req_path in sorted(DATA_DIR.glob("20??-??-??/requests.json")):
            total += translate_date(req_path.parent.name, limit=limit)
        print(f"API_FULLTEXT_TRANSLATE_ALL_DONE: translated={total}")
    else:
        translate_date(target, limit=limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
