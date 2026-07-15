#!/usr/bin/env python3
"""Restore missing translation media from the cached IGN source files.

Codex/manual translation writes may contain an empty ``images`` list or a
malformed ``cover`` URL. The article cache is authoritative for those fields,
so this script repairs only invalid or absent media without touching the
translation body.

Usage:
    python3 scripts/ensure_translation_media.py YYYY-MM-DD
    python3 scripts/ensure_translation_media.py YYYY-MM-DD --id 15
    python3 scripts/ensure_translation_media.py YYYY-MM-DD --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from translation_media import image_url, merge_images, valid_image_url


REPO = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def valid_url(value: Any) -> bool:
    return valid_image_url(value) and ")width=" not in image_url(value)


def numeric_id(path: Path) -> int:
    return int(path.stem)


def repair(date: str, article_id: int | None, dry_run: bool) -> int:
    day_dir = REPO / "data" / date
    translations_dir = day_dir / "translations"
    sources_dir = day_dir / "sources"
    index_path = day_dir / "index.json"
    if not translations_dir.is_dir() or not sources_dir.is_dir() or not index_path.is_file():
        raise SystemExit(f"Missing translation/source/index data for {date}")

    index = read_json(index_path)
    articles = {int(article["id"]): article for article in index.get("articles", []) if str(article.get("id", "")).isdigit()}
    paths = [translations_dir / f"{article_id:02d}.json"] if article_id is not None else sorted(translations_dir.glob("*.json"), key=numeric_id)

    repaired = 0
    index_changed = False
    for translation_path in paths:
        if not translation_path.is_file():
            print(f"[SKIP] Missing translation: {translation_path.name}")
            continue
        aid = numeric_id(translation_path)
        source_path = sources_dir / translation_path.name
        if not source_path.is_file():
            print(f"[SKIP] #{aid}: no source cache")
            continue

        translation = read_json(translation_path)
        source = read_json(source_path)
        source_cover = image_url(source.get("cover_image"))
        source_images = [item for item in source.get("images", []) if valid_url(item)] if isinstance(source.get("images"), list) else []
        changed = False

        if source_cover and not valid_url(translation.get("cover")):
            translation["cover"] = source_cover
            changed = True
        merged_translation_images = merge_images(translation.get("images"), source_images)
        if source_images and merged_translation_images != translation.get("images"):
            translation["images"] = merged_translation_images
            changed = True

        article = articles.get(aid)
        if article:
            if source_cover and not valid_url(article.get("cover_image")):
                article["cover_image"] = source_cover
                index_changed = True
            merged_article_images = merge_images(article.get("images"), source_images)
            if source_images and merged_article_images != article.get("images"):
                article["images"] = merged_article_images
                index_changed = True

        if changed:
            repaired += 1
            print(f"[REPAIR] #{aid}: restored cover/images from source cache")
            if not dry_run:
                write_json(translation_path, translation)

    if index_changed and not dry_run:
        write_json(index_path, index)
    print(f"[OK] {'Would repair' if dry_run else 'Repaired'} {repaired} translation file(s)")
    return repaired


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore missing translation media from source cache")
    parser.add_argument("date")
    parser.add_argument("--id", type=int, dest="article_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repair(args.date, args.article_id, args.dry_run)
