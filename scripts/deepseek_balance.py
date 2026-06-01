#!/usr/bin/env python3
"""Fetch DeepSeek account balance for the usage dashboard."""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio, env_paths


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
DEFAULT_BASE_URL = "https://api.deepseek.com"
BALANCE_PATH = DATA_DIR / "usage" / "deepseek-balance.json"


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


def write_json(path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_balance(api_key: str, base_url: str) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/user/balance"
    req = urllib.request.Request(
        endpoint,
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    load_env_file()
    api_key = (os.environ.get("TRANSLATOR_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    base_url = (os.environ.get("TRANSLATOR_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL
    if not api_key:
        print("DEEPSEEK_BALANCE_SKIP: TRANSLATOR_API_KEY/DEEPSEEK_API_KEY is not set")
        return 0

    try:
        balance = fetch_balance(api_key, base_url)
        payload = {
            "provider": "deepseek",
            "base_url": base_url,
            "updated_at_cn": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "ok": True,
            "is_available": bool(balance.get("is_available")),
            "balance_infos": balance.get("balance_infos") if isinstance(balance.get("balance_infos"), list) else [],
        }
        write_json(BALANCE_PATH, payload)
        print("DEEPSEEK_BALANCE_OK")
    except Exception as exc:
        payload = {
            "provider": "deepseek",
            "base_url": base_url,
            "updated_at_cn": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
            "ok": False,
            "error": str(exc)[:240],
            "balance_infos": [],
        }
        write_json(BALANCE_PATH, payload)
        print(f"DEEPSEEK_BALANCE_FAILED: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
