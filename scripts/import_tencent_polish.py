"""Import polished articles from a public Tencent Docs document.

The expected document layout is:

    YY/MM/DD Article title
    Subtitle
    First body paragraph
    Second body paragraph
    ...

Only high-confidence matches against existing translated articles are written.
Existing manually-created polish files are preserved unless
``--replace-existing`` is explicitly supplied.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio


DEFAULT_CONFIG = DATA_DIR / "tencent-polish-config.json"
DATE_LINE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{2})\s+(.+)$")
SHARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,}$")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class DocumentArticle:
    date: str
    title: str
    subtitle: str
    paragraphs: list[str]


@dataclass(frozen=True)
class TranslationCandidate:
    article: dict[str, Any]
    translation: dict[str, Any]

    @property
    def article_id(self) -> int:
        return int(self.article["id"])


@dataclass(frozen=True)
class Match:
    source: DocumentArticle
    candidate: TranslationCandidate
    score: float
    title_score: float
    body_score: float
    margin: float


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_config(path: Path) -> dict[str, Any]:
    config = load_json(path, {})
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    if not str(config.get("document_url") or "").strip():
        raise ValueError(f"document_url is missing from {path}")
    return config


def share_id_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) < 2 or parts[-2] != "doc" or not SHARE_ID_RE.match(parts[-1]):
        raise ValueError(f"Unsupported Tencent Docs URL: {url}")
    return parts[-1]


def fetch_document_payload(url: str, timeout: int = 45) -> tuple[str, bytes]:
    share_id = share_id_from_url(url)
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": url,
    }
    opener.open(Request(url, headers=headers), timeout=timeout).read()

    params = {
        "id": share_id,
        "normal": "1",
        "noEscape": "1",
        "outformat": "1",
        "doc_chunk_version": "3",
        "doc_chunk_flag": "0",
        "commandsFormat": "1",
        "u": "0",
    }
    api_url = f"https://docs.qq.com/dop-api/opendoc?{urlencode(params)}"
    api_headers = {**headers, "X-Requested-With": "XMLHttpRequest"}
    raw = opener.open(Request(api_url, headers=api_headers), timeout=timeout).read()
    response = json.loads(raw.decode("utf-8"))
    client_vars = response.get("clientVars") or {}
    collab = client_vars.get("collab_client_vars") or {}
    initial = collab.get("initialAttributedText") or {}
    encoded_texts = initial.get("text") or []
    if not encoded_texts or not isinstance(encoded_texts[0], str):
        error = client_vars.get("errmsg") or client_vars.get("errcode") or "missing document text"
        raise RuntimeError(f"Tencent Docs returned no readable content: {error}")

    title = str(client_vars.get("padTitle") or client_vars.get("title") or "").strip()
    return title, base64.b64decode(encoded_texts[0])


def read_varint(buffer: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(buffer):
        byte = buffer[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
        if shift > 70:
            break
    raise ValueError("Invalid protobuf varint")


def protobuf_fields(buffer: bytes) -> Iterable[tuple[int, int, bytes | int]]:
    position = 0
    while position < len(buffer):
        key, position = read_varint(buffer, position)
        field_number = key >> 3
        wire_type = key & 7
        if field_number == 0:
            raise ValueError("Invalid protobuf field number")
        if wire_type == 0:
            value, position = read_varint(buffer, position)
            yield field_number, wire_type, value
        elif wire_type == 1:
            end = position + 8
            if end > len(buffer):
                raise ValueError("Truncated protobuf fixed64 field")
            yield field_number, wire_type, buffer[position:end]
            position = end
        elif wire_type == 2:
            size, position = read_varint(buffer, position)
            end = position + size
            if end > len(buffer):
                raise ValueError("Truncated protobuf bytes field")
            yield field_number, wire_type, buffer[position:end]
            position = end
        elif wire_type == 5:
            end = position + 4
            if end > len(buffer):
                raise ValueError("Truncated protobuf fixed32 field")
            yield field_number, wire_type, buffer[position:end]
            position = end
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")


def protobuf_child(buffer: bytes, field_number: int) -> bytes:
    children = [
        value
        for number, wire_type, value in protobuf_fields(buffer)
        if number == field_number and wire_type == 2 and isinstance(value, bytes)
    ]
    if not children:
        raise ValueError(f"Missing protobuf field {field_number}")
    return max(children, key=len)


def looks_like_document_text(value: str) -> bool:
    markers = sum(
        bool(DATE_LINE_RE.match(line.strip()))
        for line in re.split(r"[\r\n]+", value)
    )
    return markers >= 1 and len(value) >= 100


def find_document_text(buffer: bytes) -> str:
    # Tencent's current full-document response stores text at this path.
    try:
        current = buffer
        for field_number in (1, 2, 6, 1):
            current = protobuf_child(current, field_number)
        text = current.decode("utf-8")
        if looks_like_document_text(text):
            return text
    except (UnicodeDecodeError, ValueError):
        pass

    best: tuple[int, int, str] | None = None

    def visit(payload: bytes, depth: int) -> None:
        nonlocal best
        if depth > 7:
            return
        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError:
            decoded = ""
        if decoded and looks_like_document_text(decoded):
            marker_count = sum(
                bool(DATE_LINE_RE.match(line.strip()))
                for line in re.split(r"[\r\n]+", decoded)
            )
            candidate = (marker_count, len(decoded), decoded)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        try:
            fields = list(protobuf_fields(payload))
        except ValueError:
            return
        for _number, wire_type, value in fields:
            if wire_type == 2 and isinstance(value, bytes) and len(value) > 1:
                visit(value, depth + 1)

    visit(buffer, 0)
    if best is None:
        raise RuntimeError("Could not locate plain document text in Tencent payload")
    return best[2]


def parse_document_articles(text: str) -> list[DocumentArticle]:
    lines = [
        line.strip()
        for line in re.split(r"[\r\n]+", text.replace("\u00a0", " "))
        if line.strip()
    ]
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = DATE_LINE_RE.match(line)
        if match:
            starts.append((index, match))

    articles: list[DocumentArticle] = []
    for number, (start, match) in enumerate(starts):
        end = starts[number + 1][0] if number + 1 < len(starts) else len(lines)
        content = lines[start + 1 : end]
        if len(content) < 2:
            continue
        year, month, day, title = match.groups()
        date = f"20{year}-{month}-{day}"
        articles.append(
            DocumentArticle(
                date=date,
                title=title.strip(),
                subtitle=content[0],
                paragraphs=content[1:],
            )
        )
    return articles


def normalized(value: str, limit: int = 1600) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    value = value.replace("“", "「").replace("”", "」")
    value = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    return value[:limit]


def similarity(left: str, right: str) -> float:
    left_norm = normalized(left)
    right_norm = normalized(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        length_ratio = min(len(left_norm), len(right_norm)) / max(len(left_norm), len(right_norm))
        return max(0.82, length_ratio)
    return SequenceMatcher(None, left_norm, right_norm, autojunk=False).ratio()


def translation_paragraphs(translation: dict[str, Any]) -> list[str]:
    values = translation.get("paragraphs") or []
    result: list[str] = []
    for item in values:
        if isinstance(item, dict):
            text = str(item.get("cn") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def load_candidates(date: str) -> list[TranslationCandidate]:
    day_dir = DATA_DIR / date
    index = load_json(day_dir / "index.json", {})
    articles = index.get("articles") if isinstance(index, dict) else None
    if not isinstance(articles, list):
        return []

    candidates: list[TranslationCandidate] = []
    for article in articles:
        if not isinstance(article, dict) or "id" not in article:
            continue
        article_id = int(article["id"])
        relative_path = str(article.get("translation_path") or f"translations/{article_id:02d}.json")
        translation_path = day_dir / relative_path
        if not translation_path.exists():
            translation_path = day_dir / "translations" / f"{article_id:02d}.json"
        translation = load_json(translation_path, {})
        if isinstance(translation, dict) and translation:
            candidates.append(TranslationCandidate(article=article, translation=translation))
    return candidates


def score_pair(source: DocumentArticle, candidate: TranslationCandidate) -> tuple[float, float, float]:
    title_values = [
        str(candidate.translation.get("cn_title") or ""),
        str(candidate.article.get("cn_title") or ""),
    ]
    title_score = max(similarity(source.title, value) for value in title_values)

    source_body = source.paragraphs
    translated_body = translation_paragraphs(candidate.translation)
    body_scores = [0.0]
    if source_body and translated_body:
        body_scores.extend(
            [
                similarity(source_body[0], translated_body[0]),
                similarity("\n".join(source_body[:2]), "\n".join(translated_body[:2])),
                similarity("\n".join(source_body[:3]), "\n".join(translated_body[:3])),
            ]
        )
    body_score = max(body_scores)
    if body_score:
        score = title_score * 0.42 + body_score * 0.58
    else:
        score = title_score * 0.82
    return score, title_score, body_score


def match_articles(
    sources: list[DocumentArticle],
    candidates: list[TranslationCandidate],
) -> tuple[list[Match], list[tuple[DocumentArticle, str]]]:
    proposals: list[Match] = []
    skipped: list[tuple[DocumentArticle, str]] = []

    for source in sources:
        ranked: list[tuple[float, float, float, TranslationCandidate]] = []
        for candidate in candidates:
            score, title_score, body_score = score_pair(source, candidate)
            ranked.append((score, title_score, body_score, candidate))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            skipped.append((source, "no translated candidates"))
            continue

        best_score, title_score, body_score, candidate = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = best_score - second_score
        confident = (
            (best_score >= 0.68 and (margin >= 0.06 or best_score >= 0.90))
            or (body_score >= 0.90 and best_score >= 0.55 and margin >= 0.05)
            or (best_score >= 0.64 and margin >= 0.25)
            or (title_score >= 0.88 and best_score >= 0.62 and margin >= 0.10)
        )
        if not confident:
            skipped.append(
                (
                    source,
                    f"low confidence best=#{candidate.article_id} "
                    f"score={best_score:.3f} margin={margin:.3f}",
                )
            )
            continue
        proposals.append(
            Match(
                source=source,
                candidate=candidate,
                score=best_score,
                title_score=title_score,
                body_score=body_score,
                margin=margin,
            )
        )

    by_candidate: dict[int, list[Match]] = {}
    for proposal in proposals:
        by_candidate.setdefault(proposal.candidate.article_id, []).append(proposal)

    accepted: list[Match] = []
    for article_id, conflicts in by_candidate.items():
        conflicts.sort(key=lambda item: item.score, reverse=True)
        accepted.append(conflicts[0])
        for conflict in conflicts[1:]:
            skipped.append(
                (
                    conflict.source,
                    f"candidate conflict: article #{article_id} already matched "
                    f"to {conflicts[0].source.title}",
                )
            )
    accepted.sort(key=lambda item: item.candidate.article_id)
    return accepted, skipped


def polish_filename(article: dict[str, Any]) -> str:
    article_id = int(article["id"])
    title = str(article.get("cn_title") or "untitled")
    safe_title = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", "_", title).strip("_")[:60]
    return f"{article_id:02d}_{safe_title or 'untitled'}.json"


def source_fingerprint(source: DocumentArticle) -> str:
    payload = "\n".join([source.date, source.title, source.subtitle, *source.paragraphs])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_matches(
    date: str,
    matches: list[Match],
    document_url: str,
    document_title: str,
    *,
    dry_run: bool,
    replace_existing: bool,
) -> tuple[int, int, list[str]]:
    polished_dir = DATA_DIR / date / "polished"
    index_path = polished_dir / "_index.json"
    polish_index = load_json(index_path, {})
    if not isinstance(polish_index, dict):
        polish_index = {}

    imported = 0
    unchanged = 0
    messages: list[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    for match in matches:
        article = match.candidate.article
        article_id = match.candidate.article_id
        key = str(article_id)
        filename = str(polish_index.get(key) or polish_filename(article))
        output_path = polished_dir / filename
        existing = load_json(output_path, {})
        existing_import = existing.get("import_source") if isinstance(existing, dict) else None
        imported_by_tencent = (
            isinstance(existing_import, dict)
            and existing_import.get("type") == "tencent_docs"
        )
        if existing and not replace_existing and not imported_by_tencent:
            unchanged += 1
            messages.append(f"SKIP {date} #{article_id:02d}: existing manual polish")
            continue

        fingerprint = source_fingerprint(match.source)
        if (
            existing
            and isinstance(existing_import, dict)
            and existing_import.get("fingerprint") == fingerprint
        ):
            unchanged += 1
            messages.append(f"SAME {date} #{article_id:02d}: {match.source.title}")
            continue

        payload = {
            "id": article_id,
            "cn_title": article.get("cn_title") or match.candidate.translation.get("cn_title") or "",
            "en_title": article.get("en_title") or match.candidate.translation.get("en_title") or "",
            "url": article.get("url") or match.candidate.translation.get("url") or "",
            "category": article.get("category") or "",
            "title": match.source.title,
            "subtitle": match.source.subtitle,
            "body": "\n".join(match.source.paragraphs),
            "updated_at": now,
            "paragraphs": match.source.paragraphs,
            "import_source": {
                "type": "tencent_docs",
                "document_url": document_url,
                "document_title": document_title,
                "fingerprint": fingerprint,
                "imported_at": now,
                "match_score": round(match.score, 4),
            },
        }
        polish_index[key] = filename
        imported += 1
        messages.append(
            f"{'WOULD' if dry_run else 'IMPORT'} {date} #{article_id:02d} "
            f"score={match.score:.3f}: {match.source.title}"
        )
        if not dry_run:
            write_json(output_path, payload)

    if imported and not dry_run:
        sorted_index = dict(sorted(polish_index.items(), key=lambda item: int(item[0])))
        write_json(index_path, sorted_index)
    return imported, unchanged, messages


def dates_to_process(
    articles: list[DocumentArticle],
    requested_date: str | None,
    all_dates: bool,
    timezone_name: str,
) -> list[str]:
    available = sorted({article.date for article in articles})
    if all_dates:
        return available
    if requested_date:
        return [requested_date]
    today = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
    return [today]


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", help="Import one YYYY-MM-DD date")
    parser.add_argument("--all", action="store_true", help="Import every date found in the document")
    parser.add_argument("--dry-run", action="store_true", help="Show matches without writing files")
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace existing manual polish files as well as prior Tencent imports",
    )
    args = parser.parse_args()
    if args.all and args.date:
        parser.error("--all and --date cannot be used together")

    config = load_config(args.config)
    document_url = str(config["document_url"]).strip()
    timezone_name = str(config.get("timezone") or "Asia/Shanghai")
    expected_title = str(config.get("document_title") or "").strip()

    document_title, payload = fetch_document_payload(document_url)
    if expected_title and document_title and expected_title != document_title:
        raise RuntimeError(
            f"Document title changed: expected {expected_title!r}, got {document_title!r}"
        )
    document_text = find_document_text(payload)
    articles = parse_document_articles(document_text)
    if not articles:
        raise RuntimeError("No dated articles found in Tencent document")

    selected_dates = dates_to_process(articles, args.date, args.all, timezone_name)
    total_imported = 0
    total_unchanged = 0
    total_matched = 0
    total_skipped = 0

    print(
        f"Tencent document: {document_title or expected_title or document_url} "
        f"({len(articles)} articles)"
    )
    for date in selected_dates:
        sources = [article for article in articles if article.date == date]
        if not sources:
            print(f"NO_SOURCE {date}: no entries in Tencent document")
            continue
        candidates = load_candidates(date)
        matches, skipped = match_articles(sources, candidates)
        imported, unchanged, messages = import_matches(
            date,
            matches,
            document_url,
            document_title or expected_title,
            dry_run=args.dry_run,
            replace_existing=args.replace_existing,
        )
        total_imported += imported
        total_unchanged += unchanged
        total_matched += len(matches)
        total_skipped += len(skipped)
        print(
            f"\n[{date}] source={len(sources)} translated={len(candidates)} "
            f"matched={len(matches)} skipped={len(skipped)}"
        )
        for message in messages:
            print(message)
        for source, reason in skipped:
            print(f"SKIP {date}: {source.title} ({reason})")

    action = "would_import" if args.dry_run else "imported"
    print(
        f"\nSUMMARY {action}={total_imported} unchanged={total_unchanged} "
        f"matched={total_matched} skipped={total_skipped}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
