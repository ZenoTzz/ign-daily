#!/usr/bin/env python3
"""Translate need_titles.json queues with the DeepSeek chat-completions API.

This script only fills homepage metadata:
  - cn_title
  - summary
  - category
  - emoji

It does not translate full articles and does not write translations/NN.json.

Usage:
  DEEPSEEK_API_KEY=... python3 scripts/translate_titles_deepseek.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio, dict_path, env_paths


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
CATEGORIES = ["游戏新闻", "评测评分", "影视资讯", "人物新闻", "行业动态", "科技新闻", "观点推荐"]


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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def matched_terms(text: str, limit: int = 30) -> dict[str, str]:
    terms = flatten_dict_terms()
    lower = text.lower()
    hits: dict[str, str] = {}
    for en, cn in sorted(terms.items(), key=lambda kv: len(kv[0]), reverse=True):
        if en.lower() in lower:
            hits[en] = cn
        if len(hits) >= limit:
            break
    return hits


def fetch_article_text(url: str, max_chars: int = 9000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", html)
    html = re.sub(r"(?is)<(br|p|div|section|article|h[1-6])\b[^>]*>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def call_deepseek(api_key: str, model: str, base_url: str, messages: list[dict[str, str]]) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1200,
        "stream": False,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def build_messages(article: dict[str, Any], article_text: str, terms: dict[str, str]) -> list[dict[str, str]]:
    system = (
        "你是 IGN Daily 的中文首页标题摘要编辑。只输出严格 JSON。"
        "不要翻译全文，不要写 Markdown。标题要自然、有新闻感；摘要 80-160 个中文字符。"
        "如果词库中有译名，必须使用词库译名。"
    )
    user = {
        "en_title": article.get("en_title", ""),
        "current_cn_title": article.get("cn_title", ""),
        "url": article.get("url", ""),
        "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
        "allowed_categories": CATEGORIES,
        "matched_dictionary_terms": terms,
        "article_text_excerpt": article_text,
        "required_json_schema": {
            "cn_title": "中文标题",
            "summary": "中文摘要，80-160字",
            "category": "必须从 allowed_categories 选一个",
            "emoji": "一个相关 emoji",
            "pending_dict": [{"en": "未确认英文名", "cn": "建议译名", "reason": "为什么需要人工确认"}],
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    category = str(result.get("category") or "游戏新闻")
    if category not in CATEGORIES:
        category = "游戏新闻"
    emoji = str(result.get("emoji") or "📰").strip()[:4]
    pending = result.get("pending_dict")
    if not isinstance(pending, list):
        pending = []
    return {
        "cn_title": str(result.get("cn_title") or "").strip(),
        "summary": str(result.get("summary") or "").strip(),
        "category": category,
        "emoji": emoji,
        "pending_dict": pending,
    }


def translate_date(date: str, limit: int = 8) -> int:
    load_env_file()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("DEEPSEEK_SKIP: DEEPSEEK_API_KEY is not set")
        return 0

    model = os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_MODEL
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_BASE_URL

    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    queue_path = day_dir / "need_titles.json"
    if not index_path.exists():
        print(f"DEEPSEEK_SKIP: no index.json for {date}")
        return 0
    if not queue_path.exists():
        print(f"DEEPSEEK_SKIP: no need_titles.json for {date}")
        return 0

    index = load_json(index_path)
    queue = load_json(queue_path)
    if not queue:
        print(f"DEEPSEEK_SKIP: empty need_titles.json for {date}")
        return 0

    by_url = {a.get("url"): a for a in index.get("articles", []) if a.get("url")}
    remaining = []
    translated = 0
    for item in queue:
        if translated >= limit:
            remaining.append(item)
            continue
        url = item.get("url")
        article = by_url.get(url)
        if not article:
            print(f"[KEEP] queue URL not found in index: {url}")
            remaining.append(item)
            continue
        try:
            article_text = fetch_article_text(url)
            terms = matched_terms((article.get("en_title") or "") + "\n" + article_text)
            messages = build_messages(article, article_text, terms)
            raw = call_deepseek(api_key, model, base_url, messages)
            result = normalize_result(extract_json(raw))
            if not result["cn_title"] or not result["summary"]:
                raise ValueError("model returned empty cn_title or summary")
            article["cn_title"] = result["cn_title"]
            article["summary"] = result["summary"]
            article["category"] = result["category"]
            article["emoji"] = result["emoji"]
            if result["pending_dict"]:
                article["pending_dict"] = result["pending_dict"]
            translated += 1
            print(f"[OK] #{article.get('id')} {result['cn_title']}")
            time.sleep(0.5)
        except Exception as exc:
            print(f"[KEEP] failed to translate {url}: {exc}")
            remaining.append(item)

    write_json(index_path, index)
    write_json(queue_path, remaining)
    print(f"DEEPSEEK_TITLE_TRANSLATE_DONE: date={date}, translated={translated}, remaining={len(remaining)}")
    return translated


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else default_date()
    limit = int(os.environ.get("DEEPSEEK_TITLE_LIMIT", "8"))
    translate_date(date, limit=limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
