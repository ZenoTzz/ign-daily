#!/usr/bin/env python3
"""Translate one article with one or more API models for manual comparison.

This script is manual-only. It writes data/{date}/comparisons/NN.json and marks
the article with comparison metadata in index.json. It does not modify
translations/NN.json or requests.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio
from translate_fulltext_api import (
    DEFAULT_BASE_URL,
    build_messages,
    fetch_article_text,
    load_cached_source,
    load_env_file,
    load_json,
    matched_terms,
    normalize_translation,
    source_text,
    split_paragraphs,
    translate_paragraph_chunks,
    write_json,
)
from translate_titles_deepseek import call_deepseek_response, extract_json
from usage_logger import record_deepseek_usage_safe


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
DEFAULT_MODEL_A = "deepseek-v4-pro"
DEFAULT_MODEL_B = "deepseek-v4-flash"


def now_cn() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def find_article(index: dict[str, Any], article_id: int) -> dict[str, Any]:
    for article in index.get("articles", []):
        if int(article.get("id") or -1) == article_id:
            return article
    raise RuntimeError(f"article #{article_id} not found in index.json")


def model_label(model: str) -> str:
    lower = model.lower()
    if "deepseek" in lower and "v4" in lower and "pro" in lower:
        return "DeepSeek V4 Pro"
    if "deepseek" in lower and "v4" in lower and "flash" in lower:
        return "DeepSeek V4 Flash"
    return model.replace("-", " ").title()


def load_compare_models(default_base_url: str) -> list[dict[str, str]]:
    raw = os.environ.get("TRANSLATOR_COMPARE_MODELS", "").strip()
    models: list[dict[str, str]] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, str):
                        model = item.strip()
                        if model:
                            models.append({"model": model, "label": model_label(model), "base_url": default_base_url})
                    elif isinstance(item, dict):
                        model = str(item.get("model") or "").strip()
                        if model:
                            models.append({
                                "model": model,
                                "label": str(item.get("label") or model_label(model)).strip(),
                                "base_url": str(item.get("base_url") or item.get("baseUrl") or default_base_url).strip(),
                                "provider": str(item.get("provider") or "openai-compatible").strip(),
                            })
        except Exception as exc:
            raise RuntimeError(f"invalid TRANSLATOR_COMPARE_MODELS JSON: {exc}") from exc

    if not models:
        model_a = (os.environ.get("TRANSLATOR_COMPARE_MODEL_A") or DEFAULT_MODEL_A).strip()
        model_b = (os.environ.get("TRANSLATOR_COMPARE_MODEL_B") or DEFAULT_MODEL_B).strip()
        models = [
            {"model": model_a, "label": model_label(model_a), "base_url": default_base_url},
            {"model": model_b, "label": model_label(model_b), "base_url": default_base_url},
        ]

    deduped = []
    seen = set()
    for item in models:
        key = (item["model"], item.get("base_url") or default_base_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    if not deduped:
        raise RuntimeError("comparison requires at least one model")
    return deduped


def translate_once(
    *,
    api_key: str,
    base_url: str,
    model: str,
    date: str,
    article: dict[str, Any],
    paragraphs_en: list[str],
    terms: dict[str, str],
) -> dict[str, Any]:
    raw, usage = call_deepseek_response(
        api_key,
        model,
        base_url,
        build_messages(article, paragraphs_en, terms),
        max_tokens=int(os.environ.get("TRANSLATOR_COMPARE_MAX_TOKENS", "12000")),
    )
    record_deepseek_usage_safe(
        task="compare_fulltext",
        model=model,
        usage=usage,
        article_id=article.get("id"),
        article_title=article.get("cn_title") or article.get("en_title"),
        article_url=article.get("url"),
        article_date=date,
        detail="manual comparison",
    )
    result = extract_json(raw)
    try:
        data = normalize_translation(article, result, paragraphs_en)
    except ValueError as exc:
        print(f"[RETRY] compare #{article['id']} {model} paragraph format issue: {exc}")
        data = normalize_translation(
            article,
            {
                **result,
                "paragraphs": translate_paragraph_chunks(
                    api_key,
                    model,
                    base_url,
                    article,
                    paragraphs_en,
                    terms,
                    article_date=date,
                ),
            },
            paragraphs_en,
        )
    data["translator"] = "api"
    data["translator_provider"] = "openai-compatible"
    data["translator_model"] = model
    return data


def run(date: str, article_id: int) -> int:
    load_env_file()
    api_key = (os.environ.get("TRANSLATOR_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("TRANSLATOR_API_KEY/DEEPSEEK_API_KEY is not set")

    base_url = (os.environ.get("TRANSLATOR_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL
    compare_models = load_compare_models(base_url)

    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    index = load_json(index_path)
    article = find_article(index, article_id)

    source = load_cached_source(date, article)
    text = source_text(source) or fetch_article_text(article["url"])
    paragraphs_en = split_paragraphs(text)
    if not paragraphs_en:
        raise RuntimeError(f"no paragraphs extracted for #{article_id}")
    terms = matched_terms(article.get("en_title", "") + "\n" + text)

    results = []
    for idx, model_info in enumerate(compare_models, start=1):
        model = model_info["model"]
        label = model_info.get("label") or model_label(model)
        model_base_url = model_info.get("base_url") or base_url
        print(f"[COMPARE] #{article_id} {idx}: {label} ({model})")
        translated = translate_once(
            api_key=api_key,
            base_url=model_base_url,
            model=model,
            date=date,
            article=article,
            paragraphs_en=paragraphs_en,
            terms=terms,
        )
        if source:
            if not translated.get("cover") and source.get("cover_image"):
                translated["cover"] = source["cover_image"]
            if not translated.get("images") and isinstance(source.get("images"), list):
                translated["images"] = source["images"]
        translated["label"] = label
        translated["comparison_label"] = label
        translated["comparison_base_url"] = model_base_url
        results.append(translated)

    payload = {
        "date": date,
        "article_id": article_id,
        "url": article.get("url"),
        "en_title": article.get("en_title"),
        "cn_title": article.get("cn_title"),
        "created_at_cn": now_cn(),
        "models": compare_models,
        "source_paragraph_count": len(paragraphs_en),
        "results": results,
    }
    compare_path = day_dir / "comparisons" / f"{article_id:02d}.json"
    write_json(compare_path, payload)

    article["comparison_status"] = "done"
    article["comparison_models"] = [m["model"] for m in compare_models]
    article["comparison_updated_at_cn"] = payload["created_at_cn"]
    write_json(index_path, index)

    print(f"API_COMPARE_DONE: date={date}, article=#{article_id}, models={','.join(article['comparison_models'])}")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/translate_compare_api.py YYYY-MM-DD ARTICLE_ID", file=sys.stderr)
        return 2
    return run(sys.argv[1], int(sys.argv[2]))


if __name__ == "__main__":
    raise SystemExit(main())
