#!/usr/bin/env python3
"""Translate requested full articles with an OpenAI-compatible chat API.

This is a guarded automation path. It writes translations/NN.json, then runs
translate_pipeline.py --post and pre_push_check.py. If validation fails, it
leaves the request in requests.json and exits non-zero so Actions will not push.

Usage:
  TRANSLATOR_API_KEY=... python3 scripts/translate_fulltext_api.py [YYYY-MM-DD|--all]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio, dict_path, env_paths
from currency_utils import normalize_translation_currency
from prompt_blocks import chunk_user_payload, fulltext_user_payload
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


def matched_terms(text: str, limit: int = 60) -> dict[str, str]:
    lower = text.lower()
    hits: dict[str, str] = {}
    for en, cn in sorted(flatten_dict_terms().items(), key=lambda kv: len(kv[0]), reverse=True):
        if en.lower() in lower:
            hits[en] = cn
        if len(hits) >= limit:
            break
    return hits


def read_optional(path: str, max_chars: int = 10000) -> str:
    p = REPO_ROOT / path
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")[:max_chars]


def build_messages(article: dict[str, Any], paragraphs: list[str], terms: dict[str, str]) -> list[dict[str, str]]:
    system = (
        "你是 IGN Daily 的中文全文翻译 agent。必须严格输出 JSON，不要 Markdown。"
        "逐段翻译 paragraphs_en，保持段落数量和顺序一致。"
        "必须遵守翻译指南、风格画像和词库命中。所有外币金额必须补人民币换算；中文标点使用全角；作品名用《》。"
    )
    user = fulltext_user_payload(article=article, paragraphs=paragraphs, terms=terms)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
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
    system = (
        "你是 IGN Daily 的中文逐段翻译 agent。只输出严格 JSON，不要 Markdown。"
        "必须返回与 paragraphs_en 数量完全一致的 paragraphs 数组。"
        "每个元素必须包含 index 和 cn。所有外币金额必须补人民币换算；中文标点用全角，作品名用《》。"
    )
    user = chunk_user_payload(article=article, chunk=chunk, terms=terms)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
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
    for start in range(0, len(indexed), chunk_size):
        chunk = indexed[start:start + chunk_size]
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
    return [{"en": en, "cn": translated[i]} for i, en in indexed]


def normalize_translation(article: dict[str, Any], result: dict[str, Any], paragraphs_en: list[str]) -> dict[str, Any]:
    normalized = normalize_paragraphs(result, paragraphs_en)
    return normalize_translation_currency({
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
        "pending_dict": result.get("pending_dict") if isinstance(result.get("pending_dict"), list) else [],
        "translated_terms": result.get("translated_terms") if isinstance(result.get("translated_terms"), dict) else {},
        "cover": str(result.get("cover") or article.get("cover_image") or "").strip(),
        "images": result.get("images") if isinstance(result.get("images"), list) else [],
    })


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
        text = source_text(source) or fetch_article_text(article["url"])
        paragraphs_en = split_paragraphs(text)
        if not paragraphs_en:
            raise RuntimeError(f"no paragraphs extracted for #{article['id']}")
        terms = matched_terms(article.get("en_title", "") + "\n" + text)
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
        result = extract_json(raw)
        try:
            data = normalize_translation(article, result, paragraphs_en)
        except ValueError as exc:
            print(f"[RETRY] fulltext #{article['id']} paragraph format issue: {exc}")
            data = normalize_translation(article, {**result, "paragraphs": translate_paragraph_chunks(api_key, model, base_url, article, paragraphs_en, terms, article_date=date)}, paragraphs_en)
        data["translator"] = "api"
        data["translator_provider"] = "openai-compatible"
        data["translator_model"] = model
        if source:
            if not data.get("cover") and source.get("cover_image"):
                data["cover"] = source["cover_image"]
            if not data.get("images") and isinstance(source.get("images"), list):
                data["images"] = source["images"]
        trans_path = DATA_DIR / date / "translations" / f"{article['id']:02d}.json"
        write_json(trans_path, data)
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "translate_pipeline.py"), date, str(article["id"]), "--post"], cwd=REPO_ROOT, check=True)
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "pre_push_check.py"), date], cwd=REPO_ROOT, check=True)
        req = remove_completed_request(req, article)
        write_json(req_path, req)
        translated += 1
        print(f"[OK] fulltext #{article['id']} {data['cn_title']}")
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
