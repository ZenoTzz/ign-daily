#!/usr/bin/env python3
"""Update STYLE_PROFILE.md with an OpenAI-compatible API.

This job learns only from completed translations and optional polished user
edits. It does not edit article data or code.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio, env_paths
from prompt_blocks import nightly_user_payload
from translate_titles_deepseek import call_deepseek_response, extract_json
from usage_logger import record_deepseek_usage_safe


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


def load_env_file() -> None:
    for path in env_paths():
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def default_date() -> str:
    now = datetime.now(CST)
    today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d") if now < today_0800 else (now + timedelta(days=1)).strftime("%Y-%m-%d")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def read_text(path: Path, max_chars: int = 20000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_samples(date: str, limit: int = 8) -> list[dict[str, Any]]:
    day_dir = DATA_DIR / date
    index_path = day_dir / "index.json"
    if not index_path.exists():
        return []
    index = load_json(index_path)
    by_id = {int(a.get("id")): a for a in index.get("articles", []) if a.get("id")}
    samples: list[dict[str, Any]] = []
    for trans_path in sorted((day_dir / "translations").glob("*.json"))[:limit]:
        try:
            trans = load_json(trans_path)
        except Exception:
            continue
        aid = int(trans.get("id") or trans_path.stem)
        polished_path = next(iter((day_dir / "polished").glob(f"{aid:02d}_*.json")), None)
        polished = load_json(polished_path) if polished_path and polished_path.exists() else {}
        paragraphs = trans.get("paragraphs") if isinstance(trans.get("paragraphs"), list) else []
        samples.append({
            "id": aid,
            "url": trans.get("url") or by_id.get(aid, {}).get("url"),
            "en_title": trans.get("en_title") or by_id.get(aid, {}).get("en_title"),
            "cn_title": trans.get("cn_title") or by_id.get(aid, {}).get("cn_title"),
            "opus_summary": trans.get("opus_summary") or by_id.get(aid, {}).get("summary"),
            "paragraph_pairs": paragraphs[:4],
            "polished_user_version": polished if polished else None,
        })
    return samples


def build_messages(date: str, current_profile: str, samples: list[dict[str, Any]]) -> list[dict[str, str]]:
    system = (
        "你是 IGN Daily 的夜间风格学习编辑。只根据今日已完成译文和用户润色样本，"
        "更新 STYLE_PROFILE.md。不要改代码，不要改文章数据，不要凭空发明术语。"
        "输出严格 JSON。"
    )
    user = nightly_user_payload(date, current_profile, samples)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def run(date: str) -> int:
    load_env_file()
    api_key = (os.environ.get("TRANSLATOR_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        print("NIGHTLY_STYLE_API_SKIP: TRANSLATOR_API_KEY/DEEPSEEK_API_KEY is not set")
        return 0
    model = (os.environ.get("NIGHTLY_STYLE_MODEL") or os.environ.get("TRANSLATOR_MODEL") or "").strip() or DEFAULT_MODEL
    base_url = (os.environ.get("TRANSLATOR_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL

    profile_path = REPO_ROOT / "STYLE_PROFILE.md"
    current = read_text(profile_path, 24000)
    samples = collect_samples(date)
    if not samples:
        print(f"NIGHTLY_STYLE_API_SKIP: no completed translations for {date}")
        return 0

    raw, usage = call_deepseek_response(api_key, model, base_url, build_messages(date, current, samples), max_tokens=5000)
    record_deepseek_usage_safe(
        task="nightly",
        model=model,
        usage=usage,
        article_date=date,
        detail=f"samples={len(samples)}",
    )
    result = extract_json(raw)
    new_profile = str(result.get("style_profile_md") or "").strip()
    if len(new_profile) < 300 or "STYLE_PROFILE" not in new_profile[:400]:
        raise RuntimeError("model returned invalid STYLE_PROFILE.md")
    new_profile = re.sub(r"\n{4,}", "\n\n\n", new_profile).rstrip() + "\n"
    profile_path.write_text(new_profile, encoding="utf-8")
    write_json(DATA_DIR / "learning_log" / f"{date}_api_style.json", {
        "date": date,
        "model": model,
        "sample_count": len(samples),
        "learning_notes": result.get("learning_notes") if isinstance(result.get("learning_notes"), list) else [],
        "updated_at": datetime.now(CST).isoformat(timespec="seconds"),
    })
    print(f"NIGHTLY_STYLE_API_DONE: date={date}, samples={len(samples)}")
    return 0


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else default_date()
    return run(target)


if __name__ == "__main__":
    raise SystemExit(main())
