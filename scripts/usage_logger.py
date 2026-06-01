#!/usr/bin/env python3
"""Append DeepSeek API usage records for the public dashboard.

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


def record_deepseek_usage(
    *,
    task: str,
    model: str,
    usage: dict[str, Any] | None,
    article_id: int | None = None,
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
    records.append({
        "time_cn": now.strftime("%Y-%m-%d %H:%M:%S"),
        "task": task,
        "model": model,
        "article_id": article_id,
        "article_url": article_url,
        "article_date": article_date,
        "detail": detail or "",
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
