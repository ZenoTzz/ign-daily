#!/usr/bin/env python3
"""Append API usage records for the public dashboard.

This module is deliberately best-effort: usage logging must never break the
translation pipeline. Callers should use ``record_deepseek_usage_safe``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR


CST = timezone(timedelta(hours=8))
USAGE_DIR = DATA_DIR / "usage" / "deepseek"
INDEX_PATH = USAGE_DIR / "index.json"
CONFIG_PATH = DATA_DIR / "automation-config.json"
PRICING_USD_PER_MILLION = {
    "deepseek-v4-flash": {
        "prompt_cache_hit_tokens": 0.0028,
        "prompt_cache_miss_tokens": 0.14,
        "completion_tokens": 0.28,
    },
    "deepseek-v4-pro": {
        "prompt_cache_hit_tokens": 0.003625,
        "prompt_cache_miss_tokens": 0.435,
        "completion_tokens": 0.87,
    },
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def int_usage(usage: dict[str, Any], key: str) -> int:
    try:
        return int(usage.get(key) or 0)
    except Exception:
        return 0


def normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    prompt = int_usage(usage, "prompt_tokens")
    completion = int_usage(usage, "completion_tokens")
    total = int_usage(usage, "total_tokens") or prompt + completion
    hit = int_usage(usage, "prompt_cache_hit_tokens")
    miss = int_usage(usage, "prompt_cache_miss_tokens")
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
    }


def normalize_model_key(model: str) -> str:
    value = (model or "").lower()
    if "deepseek-v4-pro" in value:
        return "deepseek-v4-pro"
    if "deepseek-v4-flash" in value or "deepseek-chat" in value or "deepseek-reasoner" in value:
        return "deepseek-v4-flash"
    return value


def float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def pricing_from_model_item(item: dict[str, Any]) -> dict[str, float] | None:
    nested = item.get("pricing_usd_per_million") if isinstance(item.get("pricing_usd_per_million"), dict) else {}
    hit = float_or_none(item.get("input_cache_hit_usd_per_million")) or float_or_none(nested.get("prompt_cache_hit_tokens"))
    miss = float_or_none(item.get("input_cache_miss_usd_per_million")) or float_or_none(nested.get("prompt_cache_miss_tokens"))
    output = float_or_none(item.get("output_usd_per_million")) or float_or_none(nested.get("completion_tokens"))
    if hit is None or miss is None or output is None:
        return None
    return {
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
        "completion_tokens": output,
    }


def pricing_for_model(model: str) -> dict[str, float] | None:
    config = load_json(CONFIG_PATH, {})
    if isinstance(config, dict):
        for item in config.get("api_models", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("model") or "") == model:
                pricing = pricing_from_model_item(item)
                if pricing:
                    return pricing
    return PRICING_USD_PER_MILLION.get(normalize_model_key(model))


def estimate_cost_usd(model: str, usage: dict[str, int]) -> tuple[float | None, dict[str, float] | None]:
    pricing = pricing_for_model(model)
    if not pricing:
        return None, None

    hit = usage.get("prompt_cache_hit_tokens", 0)
    miss = usage.get("prompt_cache_miss_tokens", 0)
    if hit == 0 and miss == 0 and usage.get("prompt_tokens", 0):
        # Some OpenAI-compatible providers omit cache split; estimate input as cache miss.
        miss = usage.get("prompt_tokens", 0)

    cost = (
        hit * pricing["prompt_cache_hit_tokens"]
        + miss * pricing["prompt_cache_miss_tokens"]
        + usage.get("completion_tokens", 0) * pricing["completion_tokens"]
    ) / 1_000_000
    return round(cost, 8), pricing


def record_deepseek_usage(
    *,
    task: str,
    model: str,
    usage: dict[str, Any] | None,
    article_id: int | None = None,
    article_title: str | None = None,
    article_url: str | None = None,
    article_date: str | None = None,
    detail: str | None = None,
) -> None:
    if not usage:
        return
    now = datetime.now(CST)
    usage_date = now.strftime("%Y-%m-%d")
    path = USAGE_DIR / f"{usage_date}.json"
    data = load_json(path, {"date": usage_date, "records": []})
    records = data.get("records")
    if not isinstance(records, list):
        records = []

    normalized = normalize_usage(usage)
    estimated_cost_usd, pricing = estimate_cost_usd(model, normalized)
    records.append({
        "time_cn": now.strftime("%Y-%m-%d %H:%M:%S"),
        "task": task,
        "model": model,
        "article_id": article_id,
        "article_title": article_title or "",
        "article_url": article_url,
        "article_date": article_date,
        "detail": detail or "",
        "estimated_cost_usd": estimated_cost_usd,
        "pricing_usd_per_million": pricing or {},
        **normalized,
    })
    data = {"date": usage_date, "records": records}
    write_json(path, data)

    dates = load_json(INDEX_PATH, [])
    if not isinstance(dates, list):
        dates = []
    if usage_date not in dates:
        dates.append(usage_date)
        dates.sort(reverse=True)
        write_json(INDEX_PATH, dates)


def record_deepseek_usage_safe(**kwargs: Any) -> None:
    try:
        record_deepseek_usage(**kwargs)
    except Exception as exc:
        print(f"[USAGE_LOG_WARN] {exc}")
