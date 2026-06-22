#!/usr/bin/env python3
"""
Incremental IGN RSS fetcher.

Responsibilities:
- assign articles to the Beijing-time news window ending at 08:00;
- append real news to data/{date}/index.json and data/{date}/need_titles.json;
- quarantine promo/shopping posts in data/{date}/filtered_rss.json instead of
  silently dropping them, so the website can restore false positives;
- optionally scan recent news dates so manual refresh can backfill a failed run.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from common_paths import REPO_ROOT, configure_utf8_stdio

configure_utf8_stdio()

CST = timezone(timedelta(hours=8))
IGN_DAILY = Path(REPO_ROOT)
DATA_DIR = IGN_DAILY / "data"

RSS_PAGES = [
    "https://feeds.feedburner.com/ign/all",
    "https://www.ign.com/rss/articles/feed?start=20&count=20",
    "https://www.ign.com/rss/articles/feed?start=40&count=20",
]

FILTER_PATTERNS = [
    r"\bsave \d+%",
    r"\bsave \$\d",
    r"\bdrops? to \$",
    r"\bdrops? to the lowest",
    r"\bbest .+ deals?\b",
    r"\bon sale\b",
    r"\bdiscount\b",
    r"\bcoupon\b",
    r"\bpromo(?:tion)?\b",
    r"\bmemorial.day\b",
    r"\bblack.friday\b",
    r"\bprime.day\b",
    r"\bcyber.monday\b",
    r"\bamazon.deal\b",
    r"\bbest.buy.deal\b",
    r"\bwalmart.deal\b",
    r"\ball-time low\b",
    r"\bpre[- ]?orders?\b",
    r"\bup for pre[- ]?order\b",
    r"\bwhere to buy\b",
    r"\bexclusively at\b",
    r"\bavailable (?:now )?(?:at|from)\b",
    r"\bbuy .+ (?:at|from)\b",
    r"\bcodes?\s*\([a-z]+\s+\d{4}\)",
    r"\baction figures?\b",
    r"\bcollectibles?\b",
    r"\bmerch(?:andise)?\b",
    r"\blego sets?\b",
    r"\bcollector'?s edition\b",
    r"\blimited edition\b",
    r"\bunder \$\d+",
    r"\bfor only \$\d+",
    r"\blowest price\b",
]
FILTER_URL = [
    "deal",
    "sale",
    "discount",
    "promo",
    "memorial-day",
    "black-friday",
    "prime-day",
    "cyber-monday",
    "amazon-deal",
    "best-buy-deal",
    "walmart-deal",
    "coupon",
    "codes-",
    "-codes",
    "/codes",
    "preorder",
    "pre-order",
    "where-to-buy",
    "prime-day",
    "action-figure",
    "collectible",
    "collectibles",
    "merchandise",
    "merch",
    "lego-set",
    "exclusively-at",
    "lowest-price",
    "under-",
]
FILTER_CATEGORY_PATTERNS = [
    r"\bdeals?\b",
    r"\bshopping\b",
    r"\bcommerce\b",
]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_filter_config() -> dict:
    cfg = read_json(DATA_DIR / "rss-filter-config.json", {})
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "allow_patterns": list(cfg.get("allow_patterns") or []),
        "block_patterns": list(cfg.get("block_patterns") or []),
        "block_url_keywords": list(cfg.get("block_url_keywords") or []),
        "filtered_retention_days": int(cfg.get("filtered_retention_days") or 7),
    }


def matches_any(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        if not pattern:
            continue
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return pattern
        except re.error:
            if pattern.lower() in text.lower():
                return pattern
    return ""


def filter_reason(title: str, url: str, description: str, categories: str, cfg: dict) -> str:
    text = " ".join(part for part in (title, description, categories) if part).lower()
    url_l = url.lower()

    allowed = matches_any(cfg["allow_patterns"], f"{text} {url_l}")
    if allowed:
        return ""

    custom_block = matches_any(cfg["block_patterns"], text)
    if custom_block:
        return f"custom:{custom_block}"

    built_in = matches_any(FILTER_PATTERNS, text)
    if built_in:
        return f"text:{built_in}"

    category_hit = matches_any(FILTER_CATEGORY_PATTERNS, categories or "")
    if category_hit:
        return f"category:{category_hit}"

    for keyword in [*FILTER_URL, *cfg["block_url_keywords"]]:
        if keyword and keyword.lower() in url_l:
            return f"url:{keyword}"

    return ""


def target_news_date(now: datetime) -> str:
    today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now < today_0800:
        return now.strftime("%Y-%m-%d")
    return (now + timedelta(days=1)).strftime("%Y-%m-%d")


def news_window(date_s: str) -> tuple[datetime, datetime]:
    td = datetime.strptime(date_s, "%Y-%m-%d").replace(tzinfo=CST)
    end = td.replace(hour=8, minute=0, second=0)
    return end - timedelta(days=1), end


def prune_old_filtered(now: datetime, retention_days: int) -> int:
    cutoff = (now.date() - timedelta(days=retention_days)).isoformat()
    removed = 0
    for path in DATA_DIR.glob("20??-??-??/filtered_rss.json"):
        date_name = path.parent.name
        if date_name < cutoff:
            path.unlink()
            removed += 1
            print(f"  [prune filtered] {path.relative_to(IGN_DAILY)}")
    return removed


def fetch_rss_items() -> list[dict]:
    rows: list[dict] = []
    seen_feed_urls: set[str] = set()
    for rss_url in RSS_PAGES:
        try:
            req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read().decode("utf-8", errors="replace")
            root = ET.fromstring(data)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_str = item.findtext("pubDate") or ""
                description = strip_html(item.findtext("description") or "")
                categories = " ".join((c.text or "").strip() for c in item.findall("category"))

                if not title or not link or link in seen_feed_urls:
                    continue

                try:
                    pub_dt = parsedate_to_datetime(pub_str).astimezone(CST)
                except Exception:
                    continue

                seen_feed_urls.add(link)
                rows.append(
                    {
                        "title": title,
                        "url": link,
                        "pub_dt": pub_dt,
                        "description": description,
                        "categories": categories,
                        "rss_url": rss_url,
                    }
                )
        except Exception as e:
            print(f"  WARN: {rss_url} failed: {e}")
    return rows


def ensure_history_row(target_date: str, total: int) -> None:
    hist_path = DATA_DIR / "index-list.json"
    hist = read_json(hist_path, [])
    hist = hist if isinstance(hist, list) else []
    for row in hist:
        if row.get("date") == target_date:
            row["total"] = total
            break
    else:
        hist.append({"date": target_date, "total": total, "translated": 0, "translatedTitles": []})
    hist.sort(key=lambda x: x.get("date", ""), reverse=True)
    write_json(hist_path, hist)


def process_target_date(target_date: str, now: datetime, filter_config: dict, rss_items: list[dict]) -> dict:
    window_start, window_end = news_window(target_date)
    print(f"Target date: {target_date} (Beijing now: {now.strftime('%Y-%m-%d %H:%M')})")
    print(f"Window: {window_start.strftime('%Y-%m-%d %H:%M')} -> {window_end.strftime('%Y-%m-%d %H:%M')} Beijing")

    date_dir = DATA_DIR / target_date
    index_path = date_dir / "index.json"
    filtered_path = date_dir / "filtered_rss.json"

    idx = read_json(index_path, {"date": target_date, "articles": [], "total": 0})
    existing_articles = idx.get("articles", []) if isinstance(idx, dict) else []
    existing_urls = {a.get("url") for a in existing_articles if a.get("url")}
    max_id = max((int(a.get("id", 0) or 0) for a in existing_articles), default=0)

    filtered_existing = read_json(filtered_path, [])
    if not isinstance(filtered_existing, list):
        filtered_existing = []
    filtered_urls = {a.get("url") for a in filtered_existing if a.get("url")}
    seen_urls = set(existing_urls) | set(filtered_urls)

    new_articles: list[dict] = []
    new_filtered: list[dict] = []

    for item in rss_items:
        title = item["title"]
        link = item["url"]
        pub_dt = item["pub_dt"]
        description = item["description"]
        categories = item["categories"]
        rss_url = item["rss_url"]

        if link in seen_urls or pub_dt < window_start or pub_dt >= window_end:
            continue

        reason = filter_reason(title, link, description, categories, filter_config)
        if reason:
            seen_urls.add(link)
            row = {
                "title": title,
                "url": link,
                "pubDate_cst": pub_dt.strftime("%Y-%m-%d %H:%M"),
                "description": description[:500],
                "categories": categories,
                "reason": reason,
                "rss_url": rss_url,
                "filtered_at_cn": now.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "filtered",
            }
            new_filtered.append(row)
            print(f"  [quarantine] {title[:80]} ({reason})")
            continue

        seen_urls.add(link)
        new_articles.append(
            {
                "title": title,
                "url": link,
                "pubDate_cst": pub_dt.strftime("%Y-%m-%d %H:%M"),
            }
        )

    if new_filtered:
        filtered_existing.extend(new_filtered)
        filtered_existing.sort(key=lambda x: x.get("pubDate_cst", ""), reverse=True)
        write_json(filtered_path, filtered_existing)

    if new_articles:
        date_dir.mkdir(parents=True, exist_ok=True)
        (date_dir / "translations").mkdir(parents=True, exist_ok=True)

        if not isinstance(idx, dict) or not isinstance(idx.get("articles"), list):
            idx = {"date": target_date, "articles": [], "total": 0}

        assigned = []
        for article in new_articles:
            max_id += 1
            assigned.append((max_id, article))
            idx["articles"].append(
                {
                    "id": max_id,
                    "category": "\u6e38\u620f\u65b0\u95fb",
                    "emoji": "\U0001f3ae",
                    "en_title": article["title"],
                    "cn_title": article["title"],
                    "summary": "",
                    "url": article["url"],
                    "publish_time_cn": article["pubDate_cst"],
                    "pub_date": article["pubDate_cst"],
                    "cover_image": "",
                    "translation_status": "none",
                }
            )
            print(f"  [+] #{max_id} {article['title'][:60]}")

        idx["articles"].sort(
            key=lambda a: a.get("publish_time_cn") or a.get("pub_date") or a.get("pubDate_cst") or "",
            reverse=True,
        )
        idx["total"] = len(idx["articles"])
        write_json(index_path, idx)
        ensure_history_row(target_date, idx["total"])

        need_path = date_dir / "need_titles.json"
        need_queue = read_json(need_path, [])
        need_queue = need_queue if isinstance(need_queue, list) else []
        queued_urls = {q.get("url") for q in need_queue if q.get("url")}
        for aid, article in assigned:
            if article["url"] in queued_urls:
                continue
            need_queue.append(
                {
                    "id": aid,
                    "url": article["url"],
                    "en_title": article["title"],
                    "pub_date": article["pubDate_cst"],
                }
            )
            queued_urls.add(article["url"])
        write_json(need_path, need_queue)
        print(f"\n[QUEUE] {len(new_articles)} articles queued for title translation for {target_date}")

    return {
        "target_date": target_date,
        "new_count": len(new_articles),
        "filtered_count": len(new_filtered),
        "changed_count": len(new_articles) + len(new_filtered),
        "next_id": max_id + 1,
        "articles": new_articles,
        "filtered_articles": new_filtered,
    }


def target_dates_for_run(now: datetime, lookback_days: int, explicit_dates: list[str]) -> list[str]:
    if explicit_dates:
        return explicit_dates
    current = target_news_date(now)
    base = datetime.strptime(current, "%Y-%m-%d").date()
    return [(base - timedelta(days=offset)).isoformat() for offset in range(max(1, lookback_days))]


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--lookback-days", type=int, default=1, help="Scan current news date plus N-1 previous dates.")
    parser.add_argument("--target-date", action="append", default=[], help="Explicit YYYY-MM-DD date. Can be repeated.")
    args = parser.parse_args()

    now = datetime.now(CST)
    filter_config = load_filter_config()
    cleanup_count = prune_old_filtered(now, filter_config["filtered_retention_days"])
    target_dates = target_dates_for_run(now, args.lookback_days, args.target_date)
    rss_items = fetch_rss_items()
    summaries = [process_target_date(date_s, now, filter_config, rss_items) for date_s in target_dates]

    new_articles = [a for summary in summaries for a in summary["articles"]]
    new_filtered = [a for summary in summaries for a in summary["filtered_articles"]]
    changed_count = sum(summary["changed_count"] for summary in summaries) + cleanup_count
    changed_dates = [s["target_date"] for s in summaries if s["changed_count"] > 0]
    new_target_dates = [s["target_date"] for s in summaries if s["new_count"] > 0]

    write_json(
        IGN_DAILY / "ign_rss_new.json",
        {
            "target_date": target_dates[0] if target_dates else "",
            "target_dates": target_dates,
            "changed_dates": changed_dates,
            "new_target_dates": new_target_dates,
            "new_count": len(new_articles),
            "filtered_count": len(new_filtered),
            "cleanup_count": cleanup_count,
            "changed_count": changed_count,
            "articles": new_articles,
            "filtered_articles": new_filtered,
            "runs": summaries,
        },
    )

    if changed_count == 0:
        print("No new RSS changes.")
        return 0

    if os.environ.get("IGN_DAILY_SKIP_GIT") == "1":
        print("[SKIP_GIT] RSS files updated; caller will validate and commit.")
        return 0

    os.chdir(IGN_DAILY)
    add = subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
    if add.returncode != 0:
        print(f"[ERR] git add failed: {add.stderr}")
        return add.returncode
    commit = subprocess.run(
        ["git", "commit", "-m", f"feat: incremental RSS {len(new_articles)} new, {len(new_filtered)} filtered for {','.join(changed_dates or target_dates)}"],
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
        print(f"[ERR] git commit failed: {commit.stderr}")
        return commit.returncode
    push_script = IGN_DAILY / "scripts" / "git_push.py"
    if push_script.exists():
        push = subprocess.run([sys.executable, str(push_script)], capture_output=True, text=True)
        if push.returncode != 0:
            print(push.stdout)
            print(push.stderr)
            return push.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
