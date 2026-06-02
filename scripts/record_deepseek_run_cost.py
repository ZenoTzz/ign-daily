#!/usr/bin/env python3
"""Record one workflow run's estimated cost and real balance delta."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
USAGE_DIR = DATA_DIR / "usage" / "deepseek"
SNAPSHOT_DIR = DATA_DIR / "usage" / "deepseek-balance-snapshots"
RUNS_PATH = DATA_DIR / "usage" / "deepseek-runs.json"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_cn_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
    except Exception:
        return None


def records_between(start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(USAGE_DIR.glob("20??-??-??.json")):
        data = read_json(path, {})
        for record in data.get("records", []):
            if not isinstance(record, dict):
                continue
            ts = parse_cn_time(str(record.get("time_cn") or ""))
            if start and ts and ts < start:
                continue
            if end and ts and ts > end:
                continue
            rows.append(record)
    return rows


def cost(record: dict[str, Any]) -> float:
    try:
        value = float(record.get("estimated_cost_usd"))
        if value > 0:
            return value
    except Exception:
        pass
    return 0.0


def total_balance(snapshot: dict[str, Any]) -> tuple[float | None, str]:
    try:
        value = snapshot.get("total_balance")
        if value is not None:
            return float(value), str(snapshot.get("currency") or "")
    except Exception:
        pass
    infos = snapshot.get("balance_infos")
    if not isinstance(infos, list):
        return None, ""
    total = 0.0
    currency = ""
    found = False
    for item in infos:
        if not isinstance(item, dict):
            continue
        try:
            total += float(item.get("total_balance"))
            currency = currency or str(item.get("currency") or "")
            found = True
        except Exception:
            continue
    return (total if found else None), currency


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_RUN_ID", "")
    if not run_id:
        print("RUN_COST_SKIP: missing run id")
        return 0

    before = read_json(SNAPSHOT_DIR / f"{run_id}-before.json", {})
    after = read_json(SNAPSHOT_DIR / f"{run_id}-after.json", {})
    before_time = parse_cn_time(str(before.get("updated_at_cn") or ""))
    after_time = parse_cn_time(str(after.get("updated_at_cn") or "")) or datetime.now(CST)
    records = records_between(before_time, after_time)

    before_total, before_currency = total_balance(before)
    after_total, after_currency = total_balance(after)
    actual_delta = None
    if before_total is not None and after_total is not None:
        actual_delta = round(before_total - after_total, 8)

    by_model: dict[str, dict[str, Any]] = {}
    for record in records:
        model = str(record.get("model") or "unknown")
        by_model.setdefault(model, {"calls": 0, "estimated_cost_usd": 0.0, "total_tokens": 0})
        by_model[model]["calls"] += 1
        by_model[model]["estimated_cost_usd"] += cost(record)
        by_model[model]["total_tokens"] += int(record.get("total_tokens") or 0)
    for row in by_model.values():
        row["estimated_cost_usd"] = round(row["estimated_cost_usd"], 8)

    payload = {
        "run_id": run_id,
        "workflow": os.environ.get("GITHUB_WORKFLOW", ""),
        "event": os.environ.get("GITHUB_EVENT_NAME", ""),
        "sha": os.environ.get("GITHUB_SHA", ""),
        "recorded_at_cn": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "start_balance": before_total,
        "end_balance": after_total,
        "currency": after_currency or before_currency,
        "actual_platform_cost": actual_delta,
        "estimated_cost_usd": round(sum(cost(r) for r in records), 8),
        "api_call_count": len(records),
        "total_tokens": sum(int(r.get("total_tokens") or 0) for r in records),
        "by_model": by_model,
        "snapshot_ok": bool(before.get("ok")) and bool(after.get("ok")),
    }

    runs = read_json(RUNS_PATH, [])
    if not isinstance(runs, list):
        runs = []
    runs = [r for r in runs if not (isinstance(r, dict) and r.get("run_id") == run_id)]
    runs.insert(0, payload)
    runs = runs[:200]
    write_json(RUNS_PATH, runs)
    print(f"RUN_COST_RECORDED: run={run_id}, estimated={payload['estimated_cost_usd']}, actual={payload['actual_platform_cost']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
