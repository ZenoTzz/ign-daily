#!/usr/bin/env python3
"""Conservative sentence/quote translation memory for IGN Daily.

Only entries explicitly marked ``approved`` participate in translation. Exact
paragraph matches can be applied deterministically. Exact quote matches are
passed to the translator as locked references and verified before publication.
Fuzzy matching is intentionally out of scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from common_paths import DATA_DIR, configure_utf8_stdio


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
MEMORY_PATH = DATA_DIR / "translation-memory.json"
APPROVED_STATUS = "approved"
MIN_QUOTE_CHARS = 24

_QUOTE_PATTERNS = (
    re.compile(r'"([^"\n]+)"'),
    re.compile(r"“([^”\n]+)”"),
    re.compile(r"‘([^’\n]+)’"),
)


def normalize_english(text: str) -> str:
    """Normalize presentation-only differences without changing semantics."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "\u00a0": " "}))
    return re.sub(r"\s+", " ", value).strip()


def memory_key(english: str) -> str:
    return hashlib.sha256(normalize_english(english).encode("utf-8")).hexdigest()


def empty_document() -> dict[str, Any]:
    return {
        "_meta": {
            "schema_version": 2,
            "description": "Exact paragraph and quote translations approved directly or through user-polished copies.",
        },
        "entries": [],
    }


def load_memory(path: Path = MEMORY_PATH) -> dict[str, Any]:
    if not path.exists():
        return empty_document()
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid translation memory JSON: {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise ValueError(f"invalid translation memory schema: {path}")
    return value


def validate_document(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, str] = {}
    for index, raw in enumerate(document.get("entries", []), start=1):
        if not isinstance(raw, dict):
            errors.append(f"entry {index} is not an object")
            continue
        if raw.get("status") != APPROVED_STATUS:
            continue
        english = str(raw.get("en") or "").strip()
        chinese = str(raw.get("cn") or "").strip()
        kind = str(raw.get("kind") or "paragraph")
        if not english or not chinese:
            errors.append(f"approved entry {index} is missing en or cn")
            continue
        if kind not in {"paragraph", "quote"}:
            errors.append(f"approved entry {index} has unsupported kind {kind!r}")
            continue
        key = memory_key(english)
        stored_key = str(raw.get("key") or "")
        if stored_key and stored_key != key:
            errors.append(f"approved entry {index} has a stale or invalid key")
        previous = seen.get(key)
        if previous is not None and previous != chinese:
            errors.append(f"approved entry {index} conflicts with another translation for the same English")
        seen[key] = chinese
    return errors


def approved_entries(document: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    document = document or load_memory()
    errors = validate_document(document)
    if errors:
        raise ValueError("; ".join(errors))
    result: list[dict[str, Any]] = []
    for raw in document.get("entries", []):
        if not isinstance(raw, dict) or raw.get("status") != APPROVED_STATUS:
            continue
        english = str(raw.get("en") or "").strip()
        chinese = str(raw.get("cn") or "").strip()
        kind = str(raw.get("kind") or "paragraph")
        if not english or not chinese or kind not in {"paragraph", "quote"}:
            continue
        entry = dict(raw)
        entry["key"] = memory_key(english)
        entry["kind"] = kind
        result.append(entry)
    return result


def extract_quotes(paragraph: str) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for pattern in _QUOTE_PATTERNS:
        for match in pattern.finditer(str(paragraph or "")):
            quote = match.group(1).strip()
            normalized = normalize_english(quote)
            if len(normalized) < MIN_QUOTE_CHARS or normalized in seen:
                continue
            seen.add(normalized)
            quotes.append(quote)
    return quotes


def find_hits(
    paragraphs_en: Iterable[str],
    document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    entries = approved_entries(document)
    paragraph_map = {entry["key"]: entry for entry in entries if entry["kind"] == "paragraph"}
    quote_map = {entry["key"]: entry for entry in entries if entry["kind"] == "quote"}
    hits: list[dict[str, Any]] = []
    for index, paragraph in enumerate(paragraphs_en, start=1):
        paragraph_entry = paragraph_map.get(memory_key(paragraph))
        if paragraph_entry:
            hits.append(_hit(index, paragraph_entry))
            continue
        for quote in extract_quotes(paragraph):
            quote_entry = quote_map.get(memory_key(quote))
            if quote_entry:
                hits.append(_hit(index, quote_entry))
    return hits


def _hit(paragraph_index: int, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "paragraph_index": paragraph_index,
        "kind": entry["kind"],
        "key": entry["key"],
        "en": entry["en"],
        "cn": entry["cn"],
        "active_from": entry.get("active_from") or "",
        "source": entry.get("source") or {},
    }


def prompt_payload(hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not hits:
        return None
    return {
        "policy": "These are exact, human-approved matches. Reuse required_cn verbatim. Do not alter numbers, negation, names, or wording.",
        "locked_translations": [
            {
                "paragraph_index": hit["paragraph_index"],
                "match_type": hit["kind"],
                "source_en": hit["en"],
                "required_cn": hit["cn"],
            }
            for hit in hits
        ],
    }


def apply_paragraph_locks(data: dict[str, Any], hits: list[dict[str, Any]]) -> int:
    paragraphs = data.get("paragraphs")
    if not isinstance(paragraphs, list):
        return 0
    applied = 0
    for hit in hits:
        if hit["kind"] != "paragraph":
            continue
        index = int(hit["paragraph_index"]) - 1
        if index < 0 or index >= len(paragraphs) or not isinstance(paragraphs[index], dict):
            continue
        if paragraphs[index].get("cn") != hit["cn"]:
            paragraphs[index]["cn"] = hit["cn"]
            applied += 1
    return applied


def validate_locks(data: dict[str, Any], hits: list[dict[str, Any]]) -> list[str]:
    paragraphs = data.get("paragraphs")
    errors: list[str] = []
    if not isinstance(paragraphs, list):
        return ["translation memory: paragraphs is not a list"] if hits else []
    for hit in hits:
        index = int(hit["paragraph_index"]) - 1
        if index < 0 or index >= len(paragraphs) or not isinstance(paragraphs[index], dict):
            errors.append(f"translation memory: paragraph {index + 1} is missing")
            continue
        chinese = str(paragraphs[index].get("cn") or "")
        if hit["kind"] == "paragraph" and chinese != hit["cn"]:
            errors.append(f"translation memory: paragraph {index + 1} did not reuse the approved translation")
        elif hit["kind"] == "quote" and hit["cn"] not in chinese:
            errors.append(f"translation memory: paragraph {index + 1} did not reuse the approved quote")
    return errors


def upsert_approved(
    english: str,
    chinese: str,
    *,
    kind: str,
    source: dict[str, Any] | None = None,
    note: str = "",
    path: Path = MEMORY_PATH,
) -> dict[str, Any]:
    english = str(english or "").strip()
    chinese = str(chinese or "").strip()
    if kind not in {"paragraph", "quote"}:
        raise ValueError("kind must be paragraph or quote")
    if not english or not chinese:
        raise ValueError("english and chinese are required")
    document = load_memory(path)
    key = memory_key(english)
    now = datetime.now(CST).isoformat()
    entry = {
        "key": key,
        "kind": kind,
        "en": english,
        "cn": chinese,
        "status": APPROVED_STATUS,
        "source": source or {},
        "approved_by": "user",
        "approved_at": now,
        "active_from": now,
        "updated_at": now,
        "note": note,
    }
    entries = document.setdefault("entries", [])
    existing = next((
        item for item in entries
        if isinstance(item, dict)
        and (item.get("key") == key or (item.get("en") and memory_key(str(item["en"])) == key))
    ), None)
    if existing is None:
        entries.append(entry)
    else:
        existing.clear()
        existing.update(entry)
    document.setdefault("_meta", {})["last_updated"] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry


def _load_article_pair(date: str, article_id: int, paragraph_number: int) -> tuple[str, str, dict[str, Any]]:
    source_path = DATA_DIR / date / "sources" / f"{article_id:02d}.json"
    translation_path = DATA_DIR / date / "translations" / f"{article_id:02d}.json"
    source = json.loads(source_path.read_text(encoding="utf-8-sig"))
    translation = json.loads(translation_path.read_text(encoding="utf-8-sig"))
    source_paragraphs = source.get("paragraphs_en") or []
    translated_paragraphs = translation.get("paragraphs") or []
    index = paragraph_number - 1
    if index < 0 or index >= len(source_paragraphs) or index >= len(translated_paragraphs):
        raise ValueError("paragraph number is outside the source/translation range")
    chinese = translated_paragraphs[index].get("cn") if isinstance(translated_paragraphs[index], dict) else ""
    return str(source_paragraphs[index]), str(chinese or ""), {
        "date": date,
        "article_id": article_id,
        "article_url": translation.get("url") or source.get("url") or "",
        "paragraph": paragraph_number,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create the empty memory document if missing")
    list_parser = subparsers.add_parser("list", help="List approved entries")
    list_parser.add_argument("--kind", choices=("paragraph", "quote"))
    approve = subparsers.add_parser("approve", help="Add an explicitly user-approved translation")
    approve.add_argument("--kind", choices=("paragraph", "quote"), default="paragraph")
    approve.add_argument("--en")
    approve.add_argument("--cn")
    approve.add_argument("--date")
    approve.add_argument("--article-id", type=int)
    approve.add_argument("--paragraph", type=int)
    approve.add_argument("--note", default="")
    args = parser.parse_args()

    if args.command == "init":
        if not MEMORY_PATH.exists():
            MEMORY_PATH.write_text(json.dumps(empty_document(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(MEMORY_PATH)
        return 0
    if args.command == "list":
        entries = approved_entries()
        if args.kind:
            entries = [entry for entry in entries if entry["kind"] == args.kind]
        for entry in entries:
            print(f"{entry['kind']}\t{entry['en']}\t{entry['cn']}")
        print(f"APPROVED_TRANSLATION_MEMORY={len(entries)}")
        return 0

    source: dict[str, Any] = {}
    english, chinese = args.en, args.cn
    if args.date and args.article_id and args.paragraph:
        english, chinese, source = _load_article_pair(args.date, args.article_id, args.paragraph)
    if not english or not chinese:
        parser.error("approve requires --en/--cn or --date/--article-id/--paragraph")
    entry = upsert_approved(english, chinese, kind=args.kind, source=source, note=args.note)
    print(f"APPROVED {entry['kind']} {entry['key'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
