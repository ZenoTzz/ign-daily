#!/usr/bin/env python3
"""Build exact translation memory from user-polished article copies.

The builder is deliberately conservative: it aligns the original translated
Chinese with the imported polished Chinese, keeps only high-confidence ordered
pairs, verifies the English anchor against the source cache, and quarantines
conflicting polished versions instead of choosing one silently.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio
from translation_memory import (
    MEMORY_PATH,
    extract_quotes,
    load_memory,
    memory_key,
    normalize_english,
    validate_document,
)


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
MIN_ALIGNMENT_RATIO = 0.45
AUTO_APPROVAL_MIN_RATIO = 0.80
GAP_PENALTY = -0.42
_CN_QUOTE_RE = re.compile(r"「([^」]+)」")
_NOISE_MARKERS = (
    "image credit",
    "is ign's",
    "is a freelance writer",
    "you can reach",
    "find him on",
    "find her on",
    "follow him on",
    "follow her on",
    "copyright",
    "all rights reserved",
)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def normalize_chinese(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def polished_paragraphs(polished: dict[str, Any]) -> list[str]:
    paragraphs = polished.get("paragraphs")
    if isinstance(paragraphs, list):
        result: list[str] = []
        for item in paragraphs:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = str(item.get("cn") or item.get("text") or "")
            else:
                text = ""
            if text.strip():
                result.append(text.strip())
        if result:
            return result
    body = str(polished.get("body") or "")
    chunks = [part.strip() for part in re.split(r"\n{2,}", body) if part.strip()]
    if len(chunks) <= 1:
        chunks = [part.strip() for part in body.splitlines() if part.strip()]
    return chunks


def _similarity(before: str, after: str) -> float:
    left = normalize_chinese(before)
    right = normalize_chinese(after)
    if not left or not right:
        return 0.0
    length_ratio = min(len(left), len(right)) / max(len(left), len(right))
    if length_ratio < 0.35:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def align_polished(before: list[str], after: list[str]) -> list[tuple[int, int, float]]:
    """Ordered global alignment with a minimum semantic-shape similarity gate."""
    n, m = len(before), len(after)
    scores = [[float("-inf")] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int, str, float] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    scores[0][0] = 0.0
    for i in range(1, n + 1):
        scores[i][0] = scores[i - 1][0] + GAP_PENALTY
        back[i][0] = (i - 1, 0, "skip_before", 0.0)
    for j in range(1, m + 1):
        scores[0][j] = scores[0][j - 1] + GAP_PENALTY
        back[0][j] = (0, j - 1, "skip_after", 0.0)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options: list[tuple[float, tuple[int, int, str, float]]] = [
                (scores[i - 1][j] + GAP_PENALTY, (i - 1, j, "skip_before", 0.0)),
                (scores[i][j - 1] + GAP_PENALTY, (i, j - 1, "skip_after", 0.0)),
            ]
            ratio = _similarity(before[i - 1], after[j - 1])
            if ratio >= MIN_ALIGNMENT_RATIO:
                options.append((scores[i - 1][j - 1] + (2.0 * ratio - 0.35), (i - 1, j - 1, "match", ratio)))
            scores[i][j], back[i][j] = max(options, key=lambda item: item[0])
    pairs: list[tuple[int, int, float]] = []
    i, j = n, m
    while i or j:
        step = back[i][j]
        if step is None:
            break
        prev_i, prev_j, operation, ratio = step
        if operation == "match":
            pairs.append((i - 1, j - 1, ratio))
        i, j = prev_i, prev_j
    pairs.reverse()
    return pairs


def is_noise(english: str) -> bool:
    normalized = normalize_english(english).casefold()
    if len(normalized) < 30:
        return True
    return any(marker in normalized for marker in _NOISE_MARKERS)


def valid_chinese(chinese: str) -> bool:
    text = normalize_chinese(chinese)
    if len(text) < 4:
        return False
    bad = ("[原文缺失]", "[MANUAL_TRANSLATION_REQUIRED]", "待人工翻译", "翻译失败")
    return not any(marker in text for marker in bad)


def english_quotes_are_balanced(text: str) -> bool:
    return text.count('"') % 2 == 0 and text.count("“") == text.count("”") and text.count("‘") == text.count("’")


def quote_candidates(english: str, chinese: str) -> list[tuple[str, str]]:
    if not english_quotes_are_balanced(english):
        return []
    english_quotes = extract_quotes(english)
    chinese_quotes = [match.group(1).strip() for match in _CN_QUOTE_RE.finditer(chinese) if len(match.group(1).strip()) >= 8]
    if not english_quotes or len(english_quotes) != len(chinese_quotes):
        return []
    return list(zip(english_quotes, chinese_quotes))


def _source_time(polished: dict[str, Any]) -> str:
    imported = polished.get("import_source") if isinstance(polished.get("import_source"), dict) else {}
    return str(polished.get("updated_at") or imported.get("imported_at") or "")


def collect_candidates(data_dir: Path = DATA_DIR) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    stats = {
        "polished_articles": 0,
        "aligned_paragraphs": 0,
        "skipped_unaligned": 0,
        "quote_pairs": 0,
    }
    for index_path in sorted(data_dir.glob("20??-??-??/polished/_index.json")):
        date = index_path.parent.parent.name
        mapping = load_json(index_path)
        for raw_id, filename in mapping.items():
            try:
                article_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            polished_path = index_path.parent / str(filename)
            source_path = index_path.parent.parent / "sources" / f"{article_id:02d}.json"
            translation_path = index_path.parent.parent / "translations" / f"{article_id:02d}.json"
            if not polished_path.exists() or not source_path.exists() or not translation_path.exists():
                continue
            polished = load_json(polished_path)
            source = load_json(source_path)
            translation = load_json(translation_path)
            source_url = str(source.get("url") or "")
            translation_url = str(translation.get("url") or "")
            polished_url = str(polished.get("url") or "")
            urls = {value for value in (source_url, translation_url, polished_url) if value}
            if len(urls) > 1:
                continue
            source_set = {normalize_english(value) for value in source.get("paragraphs_en") or [] if str(value).strip()}
            translated_items = []
            for item in translation.get("paragraphs") or []:
                if not isinstance(item, dict):
                    continue
                english = str(item.get("en") or "").strip()
                chinese = str(item.get("cn") or "").strip()
                if not english or not chinese or normalize_english(english) not in source_set:
                    continue
                translated_items.append({"en": english, "cn": chinese})
            after = polished_paragraphs(polished)
            if not translated_items or not after:
                continue
            stats["polished_articles"] += 1
            pairs = align_polished([item["cn"] for item in translated_items], after)
            stats["skipped_unaligned"] += max(len(translated_items), len(after)) - len(pairs)
            for before_index, after_index, ratio in pairs:
                english = translated_items[before_index]["en"]
                chinese = after[after_index]
                if is_noise(english) or not valid_chinese(chinese):
                    continue
                evidence = {
                    "date": date,
                    "article_id": article_id,
                    "article_url": source_url or translation_url or polished_url,
                    "paragraph": before_index + 1,
                    "polished_file": str(polished_path.relative_to(data_dir)).replace("\\", "/"),
                    "polished_at": _source_time(polished),
                    "alignment_ratio": round(ratio, 4),
                }
                auto_approve = ratio >= AUTO_APPROVAL_MIN_RATIO
                candidates.append({
                    "kind": "paragraph",
                    "en": english,
                    "cn": chinese,
                    "source": evidence,
                    "auto_approve": auto_approve,
                })
                stats["aligned_paragraphs"] += 1
                for quote_en, quote_cn in quote_candidates(english, chinese):
                    candidates.append({
                        "kind": "quote",
                        "en": quote_en,
                        "cn": quote_cn,
                        "source": evidence,
                        "auto_approve": auto_approve,
                    })
                    stats["quote_pairs"] += 1
    return candidates, stats


def _entry_identity(entry: dict[str, Any]) -> tuple[str, str]:
    return str(entry.get("kind") or "paragraph"), memory_key(str(entry.get("en") or ""))


def build_document(
    existing: dict[str, Any],
    candidates: list[dict[str, Any]],
    stats: dict[str, int],
    *,
    now: str,
) -> dict[str, Any]:
    manual = [
        dict(entry) for entry in existing.get("entries", [])
        if isinstance(entry, dict) and entry.get("origin") != "polished_auto"
    ]
    manual_keys = {memory_key(str(entry.get("en") or "")) for entry in manual if str(entry.get("en") or "").strip()}
    previous_auto = {
        _entry_identity(entry): entry
        for entry in existing.get("entries", [])
        if isinstance(entry, dict) and entry.get("origin") == "polished_auto"
    }
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        identity = _entry_identity(candidate)
        if identity[1] in manual_keys:
            continue
        group = grouped.setdefault(identity, {"kind": identity[0], "key": identity[1], "en": candidate["en"], "variants": {}})
        normalized_cn = normalize_chinese(candidate["cn"])
        variant = group["variants"].setdefault(
            normalized_cn,
            {"cn": candidate["cn"], "sources": [], "auto_approve": False},
        )
        variant["sources"].append(candidate["source"])
        variant["auto_approve"] = variant["auto_approve"] or bool(candidate.get("auto_approve", True))

    generated: list[dict[str, Any]] = []
    conflicts = 0
    for identity, group in sorted(grouped.items()):
        variants = list(group["variants"].values())
        previous = previous_auto.get(identity) or {}
        active_from = str(previous.get("active_from") or now)
        if len(variants) == 1:
            variant = variants[0]
            sources = sorted(variant["sources"], key=lambda item: (item.get("polished_at") or "", item.get("date") or ""))
            status = "approved" if variant["auto_approve"] else "candidate"
            generated.append({
                "key": group["key"],
                "kind": group["kind"],
                "en": group["en"],
                "cn": variant["cn"],
                "status": status,
                "origin": "polished_auto",
                **({
                    "approved_by": "user_polish",
                    "approved_at": sources[-1].get("polished_at") or now,
                } if status == "approved" else {
                    "review_reason": f"alignment_below_{AUTO_APPROVAL_MIN_RATIO:.2f}",
                }),
                "active_from": active_from,
                "updated_at": now,
                "source": sources[-1],
                "sources": sources,
                "evidence_count": len(sources),
            })
        else:
            conflicts += 1
            generated.append({
                "key": group["key"],
                "kind": group["kind"],
                "en": group["en"],
                "status": "conflict",
                "origin": "polished_auto",
                "active_from": active_from,
                "updated_at": now,
                "alternatives": sorted(variants, key=lambda item: item["cn"]),
            })
    document = {
        "_meta": {
            **(existing.get("_meta") if isinstance(existing.get("_meta"), dict) else {}),
            "schema_version": 2,
            "description": "Exact paragraph and quote translations learned from user-polished copies.",
            "builder": "rebuild_translation_memory.py",
            "last_rebuilt": now,
            "approved_auto_entries": sum(1 for entry in generated if entry.get("status") == "approved"),
            "candidate_auto_entries": sum(1 for entry in generated if entry.get("status") == "candidate"),
            "conflicts": conflicts,
            "stats": stats,
        },
        "entries": [*manual, *generated],
    }
    errors = validate_document(document)
    if errors:
        raise ValueError("rebuilt translation memory is invalid: " + "; ".join(errors))
    return document


def _comparable(document: dict[str, Any]) -> dict[str, Any]:
    copy = json.loads(json.dumps(document, ensure_ascii=False))
    meta = copy.get("_meta") if isinstance(copy.get("_meta"), dict) else {}
    meta.pop("last_rebuilt", None)
    for entry in copy.get("entries", []):
        if isinstance(entry, dict) and entry.get("origin") == "polished_auto":
            entry.pop("updated_at", None)
    return copy


def rebuild_memory(
    *,
    data_dir: Path = DATA_DIR,
    memory_path: Path = MEMORY_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    existing = load_memory(memory_path)
    candidates, stats = collect_candidates(data_dir)
    now = datetime.now(CST).isoformat()
    document = build_document(existing, candidates, stats, now=now)
    changed = _comparable(existing) != _comparable(document)
    if changed and not dry_run:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "TRANSLATION_MEMORY_REBUILD "
        f"changed={int(changed)} candidates={len(candidates)} "
        f"approved={document['_meta']['approved_auto_entries']} conflicts={document['_meta']['conflicts']}"
    )
    return {"changed": changed, "document": document, "candidate_count": len(candidates)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rebuild_memory(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
