#!/usr/bin/env python3
"""Translate need_titles.json queues with an OpenAI-compatible chat API.

This script only fills homepage metadata:
  - cn_title
  - summary
  - category
  - emoji

It does not translate full articles and does not write translations/NN.json.

Usage:
  TRANSLATOR_API_KEY=... python3 scripts/translate_titles_deepseek.py [YYYY-MM-DD|--all]
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


def term_in_text(en_term: str, text: str) -> bool:
    pattern = r"(?<![A-Za-z0-9])" + re.escape(en_term) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text, flags=re.I) is not None


def apply_title_dictionary(en_title: str, cn_title: str) -> str:
    """Force dictionary names into a title when the English title contains them."""
    title = cn_title or ""
    for en_term, cn_term in sorted(flatten_dict_terms().items(), key=lambda kv: len(kv[0]), reverse=True):
        if not term_in_text(en_term, en_title or "") or not cn_term or cn_term in title:
            continue
        prefix = cn_term.split("：", 1)[0].split(":", 1)[0]
        if prefix and prefix in title:
            title = re.sub(rf"《{re.escape(prefix)}[^》]*》", f"《{cn_term}》", title)
            if cn_term in title:
                continue
        title = f"《{cn_term}》{title}"
    return title


NOISE_PHRASES = (
    "advertisement",
    "ign recommends",
    "continue reading",
    "sign up",
    "newsletter",
    "privacy policy",
    "terms of use",
    "contact us",
    "all rights reserved",
    "mapgenie",
    "howlongtobeat",
    "rock paper shotgun",
    "eurogamer",
    "maxroll",
    "vg247",
    "ign youtube",
    "ign tiktok",
    "ign's x",
    "is a freelance writer with ign",
    "contributed to ign",
    "be sure to give",
    "follow him on",
    "follow her on",
)


def remove_html_noise(html: str) -> str:
    html = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>|<noscript\b.*?</noscript>", " ", html)
    html = re.sub(r"(?is)<svg\b.*?</svg>|<picture\b.*?</picture>|<figure\b.*?</figure>", " ", html)
    html = re.sub(r"(?is)<(header|nav|footer|aside|form|button)\b.*?</\1>", " ", html)
    html = re.sub(r"(?is)<[^>]+(?:nav|footer|header|sidebar|menu|breadcrumb|social|share|newsletter|promo|ad-|advert|recommend)[^>]*>.*?</[^>]+>", " ", html)
    return html


def html_to_text(html: str) -> str:
    html = remove_html_noise(html)
    html = re.sub(r"(?is)<(br|p|div|section|article|main|h[1-6]|li|blockquote)\b[^>]*>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_noise_line(line: str) -> bool:
    text = re.sub(r"\s+", " ", line).strip()
    if not text:
        return True
    lower = text.lower()
    if any(p in lower for p in NOISE_PHRASES):
        return True
    if text.count("•") >= 3 or text.count("|") >= 4:
        return True
    if len(text) < 35 and re.search(r"^(news|reviews|guides|videos|games|movies|tv|deals)\b", lower):
        return True
    return False


def clean_article_text(text: str, max_chars: int) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if not is_noise_line(line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:max_chars]


def extract_article_text(html: str, max_chars: int) -> str:
    html = remove_html_noise(html)
    paragraph_hits = []
    for match in re.finditer(r"(?is)<p\b([^>]*)>(.*?)</p>", html):
        attrs, body = match.group(1), match.group(2)
        if re.search(r'data-cy=["\']paragraph["\']', attrs, re.I) or re.search(r'class=["\'][^"\']*\bparagraph\b', attrs, re.I):
            line = clean_article_text(html_to_text(body), max_chars=max_chars)
            if line:
                paragraph_hits.append(line)
    if len(paragraph_hits) >= 2:
        return clean_article_text("\n\n".join(paragraph_hits), max_chars=max_chars)

    candidates = []
    for pattern in (
        r"(?is)<article\b[^>]*>(.*?)</article>",
        r"(?is)<main\b[^>]*>(.*?)</main>",
        r"(?is)<div\b[^>]*(?:article|content|page-content|post-content|article-content)[^>]*>(.*?)</div>",
    ):
        candidates.extend(match.group(1) for match in re.finditer(pattern, html))
    candidates.append(html)
    best = ""
    best_score = -1
    for candidate in candidates:
        text = clean_article_text(html_to_text(candidate), max_chars=max_chars * 2)
        score = len(text) - 600 * sum(1 for p in NOISE_PHRASES if p in text.lower()) - 120 * text.count("•")
        if score > best_score:
            best = text
            best_score = score
    return best[:max_chars]


def fetch_article_text(url: str, max_chars: int = 9000) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return extract_article_text(html, max_chars)


def cached_source_path(date: str, article: dict[str, Any]) -> Path:
    return DATA_DIR / date / "sources" / f"{int(article['id']):02d}.json"


def cached_article_text(date: str, article: dict[str, Any], max_chars: int = 9000) -> str:
    path = cached_source_path(date, article)
    if not path.exists():
        return ""
    try:
        source = load_json(path)
    except Exception:
        return ""
    body = str(source.get("body_en") or "").strip()
    if not body and isinstance(source.get("paragraphs_en"), list):
        body = "\n\n".join(str(p).strip() for p in source["paragraphs_en"] if str(p).strip())
    return body[:max_chars]


def read_optional(path: str, max_chars: int = 10000) -> str:
    p = REPO_ROOT / path
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")[:max_chars]


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


def call_deepseek(api_key: str, model: str, base_url: str, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens or 1200,
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
        "translation_guide": read_optional("TRANSLATION_GUIDE.md", 9000),
        "style_profile": read_optional("STYLE_PROFILE.md", 7000),
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
    api_key = (os.environ.get("TRANSLATOR_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        print("API_TITLE_SKIP: TRANSLATOR_API_KEY/DEEPSEEK_API_KEY is not set")
        return 0

    model = (os.environ.get("TRANSLATOR_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "").strip() or DEFAULT_MODEL
    base_url = (os.environ.get("TRANSLATOR_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL

    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    queue_path = day_dir / "need_titles.json"
    if not index_path.exists():
        print(f"API_TITLE_SKIP: no index.json for {date}")
        return 0
    if not queue_path.exists():
        print(f"API_TITLE_SKIP: no need_titles.json for {date}")
        return 0

    index = load_json(index_path)
    queue = load_json(queue_path)
    if not queue:
        print(f"API_TITLE_SKIP: empty need_titles.json for {date}")
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
            article_text = cached_article_text(date, article) or fetch_article_text(url)
            terms = matched_terms((article.get("en_title") or "") + "\n" + article_text)
            messages = build_messages(article, article_text, terms)
            raw = call_deepseek(api_key, model, base_url, messages)
            result = normalize_result(extract_json(raw))
            if not result["cn_title"] or not result["summary"]:
                raise ValueError("model returned empty cn_title or summary")
            article["cn_title"] = apply_title_dictionary(article.get("en_title", ""), result["cn_title"])
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
    print(f"API_TITLE_TRANSLATE_DONE: date={date}, translated={translated}, remaining={len(remaining)}")
    return translated


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else default_date()
    limit = int(os.environ.get("TRANSLATOR_TITLE_LIMIT") or os.environ.get("DEEPSEEK_TITLE_LIMIT") or "30")
    if target == "--all":
        total = 0
        for queue_path in sorted(DATA_DIR.glob("20??-??-??/need_titles.json")):
            try:
                if load_json(queue_path):
                    total += translate_date(queue_path.parent.name, limit=limit)
            except Exception as exc:
                print(f"[KEEP] failed date {queue_path.parent.name}: {exc}")
        print(f"API_TITLE_TRANSLATE_ALL_DONE: translated={total}")
    else:
        translate_date(target, limit=limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
