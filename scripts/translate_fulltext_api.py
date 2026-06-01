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
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio, dict_path, env_paths
from translate_titles_deepseek import apply_title_dictionary, call_deepseek, extract_json, flatten_dict_terms


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
DEFAULT_MODEL = "deepseek-v4-flash"
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
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", html)
    html = re.sub(r"(?is)<(br|p|div|section|article|h[1-6]|li)\b[^>]*>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def split_paragraphs(text: str) -> list[str]:
    chunks = [p.strip() for p in re.split(r"\n{1,}", text) if p.strip()]
    bad = ("advertisement", "ign recommends", "continue reading", "sign up")
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
        "必须遵守翻译指南、风格画像和词库命中。金额必须补人民币换算；中文标点使用全角；作品名用《》。"
    )
    user = {
        "article": {
            "id": article.get("id"),
            "url": article.get("url"),
            "en_title": article.get("en_title"),
            "cn_title": article.get("cn_title"),
            "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
            "summary": article.get("summary", ""),
        },
        "translation_guide": read_optional("TRANSLATION_GUIDE.md", 14000),
        "style_profile": read_optional("STYLE_PROFILE.md", 8000),
        "matched_dictionary_terms": terms,
        "paragraphs_en": paragraphs,
        "required_json_schema": {
            "id": article.get("id"),
            "url": article.get("url"),
            "en_title": article.get("en_title"),
            "cn_title": "中文标题",
            "subtitle": "2-15字中文创意短句",
            "opus_summary": "150-260字中文总述",
            "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
            "paragraphs": [{"en": "原文段落", "cn": "中文译文"}],
            "pending_dict": [{"en": "未确认英文名", "cn": "建议译名", "reason": "原因"}],
            "translated_terms": {},
            "cover": "",
            "images": [],
        },
    }
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
        "每个元素必须包含 index 和 cn。中文标点用全角，作品名用《》。"
    )
    user = {
        "article": {
            "id": article.get("id"),
            "url": article.get("url"),
            "en_title": article.get("en_title"),
            "cn_title": article.get("cn_title"),
        },
        "matched_dictionary_terms": terms,
        "style_profile": read_optional("STYLE_PROFILE.md", 5000),
        "paragraphs_en": [{"index": idx, "en": en} for idx, en in chunk],
        "required_json_schema": {
            "paragraphs": [{"index": 1, "cn": "中文译文"}]
        },
    }
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
) -> list[dict[str, str]]:
    translated: dict[int, str] = {}
    chunk_size = int(os.environ.get("TRANSLATOR_FULLTEXT_CHUNK_SIZE", "6"))
    indexed = list(enumerate(paragraphs_en, start=1))
    for start in range(0, len(indexed), chunk_size):
        chunk = indexed[start:start + chunk_size]
        raw = call_deepseek(
            api_key,
            model,
            base_url,
            build_chunk_messages(article, chunk, terms),
            max_tokens=int(os.environ.get("TRANSLATOR_FULLTEXT_CHUNK_MAX_TOKENS", "4000")),
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
    return {
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
    }


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
    for article in requested[:limit]:
        text = fetch_article_text(article["url"])
        paragraphs_en = split_paragraphs(text)
        if not paragraphs_en:
            raise RuntimeError(f"no paragraphs extracted for #{article['id']}")
        terms = matched_terms(article.get("en_title", "") + "\n" + text)
        max_tokens = int(os.environ.get("TRANSLATOR_FULLTEXT_MAX_TOKENS", "12000"))
        raw = call_deepseek(api_key, model, base_url, build_messages(article, paragraphs_en, terms), max_tokens=max_tokens)
        result = extract_json(raw)
        try:
            data = normalize_translation(article, result, paragraphs_en)
        except ValueError as exc:
            print(f"[RETRY] fulltext #{article['id']} paragraph format issue: {exc}")
            data = normalize_translation(article, {**result, "paragraphs": translate_paragraph_chunks(api_key, model, base_url, article, paragraphs_en, terms)}, paragraphs_en)
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
    limit = int(os.environ.get("TRANSLATOR_FULLTEXT_LIMIT", "2"))
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
