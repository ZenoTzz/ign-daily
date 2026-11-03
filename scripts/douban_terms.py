"""Best-effort public-page lookup. Results are candidates, never dictionary writes.

No cookies, proxy rotation, private API keys, model calls or CAPTCHA bypass.
The shared cache also acts as a circuit breaker across title/body workers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from common_paths import DATA_DIR, configure_utf8_stdio
from dict_matcher import iter_dict_terms, term_in_text
from runtime_write_lock import atomic_json, read_json, write_lock

CACHE_PATH = DATA_DIR / "douban-lookup-cache.json"
COOLDOWN = 600
FAILURE_COOLDOWN = 21600
TTL = 30 * 86400
MAX_BYTES = 1024 * 1024


def detail_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "movie.douban.com" or parsed.port not in (None, 443):
        raise ValueError("Only HTTPS Douban movie/person detail pages are accepted")
    if parsed.username or parsed.password or not re.fullmatch(r"/(subject|celebrity|personage)/\d+/?", parsed.path):
        raise ValueError("Invalid Douban detail URL")
    return "https://movie.douban.com" + parsed.path.rstrip("/") + "/"


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self.links = []
        self._h1 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h1":
            self._h1 = True
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "h1":
            self._h1 = False

    def handle_data(self, data):
        if self._h1:
            self.headings.append(data)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A security/login redirect is a failure, not an invitation to bypass it.
        return None


def fetch_page(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "IGNDaily-DictionaryLookup/1.0", "Accept": "text/html"})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=3) as response:
        if "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError("Not an HTML page")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Page too large")
        text = raw.decode("utf-8", errors="strict")
    if any(marker in text for marker in ("sec.douban.com", "检测到有异常请求", "验证码", "访问豆瓣的方式有点像机器人")):
        raise ValueError("Douban access restricted")
    return text


def parse_candidate(en: str, url: str, html: str) -> dict | None:
    url = detail_url(url)
    page = Page()
    page.feed(html)
    heading = re.sub(r"\s+", " ", " ".join(page.headings)).strip()
    year = re.search(r"\((\d{4})\)\s*$", heading)
    heading = re.sub(r"\s*\(\d{4}\)\s*$", "", heading)
    # Identity evidence must be the page heading, not a mention in its biography.
    match = re.fullmatch(r"(.+?)\s+" + re.escape(en), heading, re.I)
    if not match:
        return None
    cn = match.group(1).strip()
    if not re.search(r"[\u4e00-\u9fff]", cn) or re.search(r"[A-Za-z<>]", cn):
        return None
    cat = "movies_tv" if "/subject/" in url else "people"
    return {"en": en, "cn": cn, "cat": cat, "source": "ai_guess",
            "reference_source": "douban", "source_url": url,
            "reference_year": year.group(1) if year else "",
            "note": "豆瓣页面候选" + ("（" + year.group(1) + "）" if year else "") + "，需核对年份/人物身份后入库：" + url}


def search_urls(html: str) -> list[str]:
    page = Page()
    page.feed(html)
    urls = []
    for href in page.links:
        parsed = urllib.parse.urlsplit(href)
        if parsed.hostname == "www.douban.com" and parsed.path == "/link2/":
            href = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        try:
            url = detail_url(href)
        except ValueError:
            continue
        if url not in urls:
            urls.append(url)
    return urls[:2]


def lookup(en: str, *, url: str | None = None) -> list[dict]:
    """At most three requests, no retries, and never raises into translation."""
    en = " ".join(en.split())
    if not en or len(en) > 100:
        return []
    key = en.casefold() + "|" + (url or "")
    now = time.time()
    try:
        if url:
            url = detail_url(url)
        with write_lock():
            cache = read_json(CACHE_PATH, {})
            row = cache.get("entries", {}).get(key, {})
            if row and now - row.get("at", 0) < (TTL if row.get("candidates") else FAILURE_COOLDOWN):
                return row.get("candidates", [])
            if now < cache.get("next_request_at", 0):
                return []
            # Reserve before network I/O; concurrent workers must not duplicate it.
            cache["next_request_at"] = now + COOLDOWN
            atomic_json(CACHE_PATH, cache)
        if url:
            urls = [url]
        else:
            search = "https://www.douban.com/search?" + urllib.parse.urlencode({"cat": "1002", "q": en})
            urls = search_urls(fetch_page(search))
        found = []
        for candidate_url in urls:
            candidate = parse_candidate(en, candidate_url, fetch_page(candidate_url))
            if candidate:
                found.append(candidate)
        # Ambiguous same-name pages must not silently select the first identity.
        if len(found) > 1:
            found = []
        with write_lock():
            cache = read_json(CACHE_PATH, {})
            entries = cache.setdefault("entries", {})
            entries[key] = {"at": now, "candidates": found}
            cache["last_status"] = "pending_review" if found else "no_unambiguous_match"
            cache["entries"] = dict(sorted(entries.items(), key=lambda pair: pair[1].get("at", 0), reverse=True)[:500])
            if not found:
                cache["next_request_at"] = now + FAILURE_COOLDOWN
            atomic_json(CACHE_PATH, cache)
        return found
    except Exception as exc:
        try:
            with write_lock():
                cache = read_json(CACHE_PATH, {})
                cache["next_request_at"] = now + FAILURE_COOLDOWN
                cache["last_status"] = "unavailable:" + type(exc).__name__
                atomic_json(CACHE_PATH, cache)
        except Exception:
            pass
        return []


def missing_names(source: str, translated: str) -> list[str]:
    """Conservative heuristic; not an entity classifier or a source of facts."""
    known = {en.casefold() for en, _, _ in iter_dict_terms()}
    pattern = r"(?<![\w])(?:[A-Z][a-z]+(?:['’-][A-Za-z]+)?)(?:\s+(?:(?:of|the)\s+)*[A-Z][A-Za-z'’-]+){1,4}"
    found = []
    for match in re.finditer(pattern, source):
        name = match.group().strip()
        if name.casefold() not in known and term_in_text(name, translated, case_sensitive=True) and name not in found:
            found.append(name)
    return found


def pending_for_translation(source: str, translated: str) -> list[dict]:
    try:
        if os.environ.get("IGN_DAILY_DOUBAN_LOOKUP", "0") != "1":
            return []
        if not re.search(r"\b(?:film|movie|actor|actress|television|series|director)\b", source, re.I):
            return []
        names = missing_names(source, translated)
        return lookup(names[0]) if names else []
    except Exception:
        return []


def main():
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("english")
    parser.add_argument("--url", help="Known Douban detail URL; no search needed")
    args = parser.parse_args()
    candidates = lookup(args.english, url=args.url)
    cache = read_json(CACHE_PATH, {})
    print(json.dumps({"candidates": candidates, "status": cache.get("last_status", "cooldown_or_unavailable")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
