#!/usr/bin/env python3
"""Fetch and cache clean IGN article sources.

The cache is the single source used by API title summaries and fulltext
translation, so the page is fetched once and later translation jobs reuse the
same cleaned English body and images.

Usage:
  python3 scripts/article_cache.py YYYY-MM-DD [--missing] [--limit N]
  python3 scripts/article_cache.py --all [--missing]
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio
from translate_titles_deepseek import extract_article_text


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


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


def source_path(date: str, article: dict[str, Any]) -> Path:
    return DATA_DIR / date / "sources" / f"{int(article['id']):02d}.json"


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags(text: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def meta_content(html: str, key: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I)
        if match:
            return unescape(match.group(1)).strip()
    return ""


def find_jsonld_images(html: str) -> list[str]:
    images: list[str] = []
    for match in re.finditer(r"(?is)<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", html):
        raw = unescape(match.group(1)).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                img = item.get("image") or item.get("thumbnailUrl")
                if isinstance(img, str):
                    images.append(img)
                elif isinstance(img, list):
                    images.extend(x for x in img if isinstance(x, str))
                elif isinstance(img, dict) and isinstance(img.get("url"), str):
                    images.append(img["url"])
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return images


def extract_images(html: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for key in ("og:image", "twitter:image", "twitter:image:src"):
        value = meta_content(html, key)
        if value:
            found.append(value)
    found.extend(find_jsonld_images(html))
    found.extend(re.findall(r"https?://(?:[a-z0-9-]+\.)?ignimgs\.com/[A-Za-z0-9/_\-.%]+?\.(?:jpg|jpeg|png|webp)(?=[?\"'\s<])", html, re.I))

    seen = set()
    images: list[str] = []
    for url in found:
        clean = unescape(url).split("&quot;")[0].strip()
        if not clean or clean in seen:
            continue
        lower = clean.lower()
        if any(bad in lower for bad in ("logo", "avatar", "/icons/", "placeholder", "sprite", "favicon")):
            continue
        if re.search(r"[_/-](40|60|80|100|120)\.(?:jpg|jpeg|png|webp)", lower):
            continue
        seen.add(clean)
        images.append(clean)
    cover = images[0] if images else ""
    return cover, images[:12]


def split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n{1,}", text) if p.strip()]
    def keep(p: str) -> bool:
        if len(p) >= 35:
            return True
        return bool(re.match(r"^\d+[\.)]\s+\S", p))

    return [p for p in paragraphs if keep(p)][:45]


def fetch_source(date: str, article: dict[str, Any]) -> dict[str, Any]:
    html = fetch_html(article["url"])
    body = extract_article_text(html, 22000)
    cover, images = extract_images(html)
    title = meta_content(html, "og:title") or article.get("en_title") or ""
    description = meta_content(html, "og:description") or meta_content(html, "description")
    source = {
        "id": article.get("id"),
        "url": article.get("url"),
        "title_en": strip_tags(title),
        "summary_en": strip_tags(description),
        "body_en": body,
        "paragraphs_en": split_paragraphs(body),
        "cover_image": cover,
        "images": images,
        "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
        "fetched_at": datetime.now(CST).isoformat(timespec="seconds"),
        "extractor_version": "article_cache_v1",
    }
    if len(source["body_en"]) < 300:
        raise RuntimeError("extracted body is too short")
    return source


def queued_keys(day_dir: Path) -> tuple[set[int], set[str]]:
    ids: set[int] = set()
    urls: set[str] = set()
    for name in ("need_titles.json", "requests.json"):
        path = day_dir / name
        if not path.exists():
            continue
        try:
            data = load_json(path)
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("requested_articles", [])
        if isinstance(data, dict):
            ids.update(int(x) for x in data.get("requested_ids", []) if str(x).isdigit())
        for item in items or []:
            if isinstance(item, dict):
                if item.get("id"):
                    ids.add(int(item["id"]))
                if item.get("url"):
                    urls.add(item["url"])
    return ids, urls


def cache_date(date: str, missing_only: bool = True, limit: int = 20, queued_only: bool = False) -> int:
    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    if not index_path.exists():
        print(f"CACHE_SKIP: no index.json for {date}")
        return 0

    index = load_json(index_path)
    keep_ids, keep_urls = queued_keys(day_dir) if queued_only else (set(), set())
    cached = 0
    for article in index.get("articles", []):
        if cached >= limit:
            break
        if not article.get("url") or not article.get("id"):
            continue
        if queued_only and int(article["id"]) not in keep_ids and article["url"] not in keep_urls:
            continue
        path = source_path(date, article)
        if missing_only and path.exists():
            continue
        try:
            source = fetch_source(date, article)
            write_json(path, source)
            if source.get("cover_image") and not article.get("cover_image"):
                article["cover_image"] = source["cover_image"]
            if source.get("images"):
                article["images"] = source["images"]
            article["source_status"] = "cached"
            article["source_fetched_at"] = source["fetched_at"]
            cached += 1
            print(f"[CACHE] {date} #{article.get('id')} {source['title_en'][:70]}")
            time.sleep(0.4)
        except Exception as exc:
            article["source_status"] = "failed"
            article["source_error"] = str(exc)[:180]
            print(f"[KEEP] source fetch failed #{article.get('id')}: {exc}")

    if cached:
        write_json(index_path, index)
    print(f"ARTICLE_CACHE_DONE: date={date}, cached={cached}")
    return cached


def main() -> int:
    args = sys.argv[1:]
    target = "--all" if "--all" in args else next((arg for arg in args if not arg.startswith("--")), default_date())
    missing_only = "--force" not in args
    limit = 20
    if "--limit" in args:
        pos = args.index("--limit")
        if pos + 1 < len(args):
            limit = int(args[pos + 1])

    if target == "--all":
        total = 0
        for index_path in sorted(DATA_DIR.glob("20??-??-??/index.json")):
            total += cache_date(index_path.parent.name, missing_only=missing_only, limit=limit, queued_only="--queued" in args)
        print(f"ARTICLE_CACHE_ALL_DONE: cached={total}")
    else:
        cache_date(target, missing_only=missing_only, limit=limit, queued_only="--queued" in args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
