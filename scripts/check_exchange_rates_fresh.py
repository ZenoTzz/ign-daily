#!/usr/bin/env python3
"""Fail if exchange_rates.json is missing, incomplete, or stale."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from common_paths import configure_utf8_stdio, exchange_rates_path


configure_utf8_stdio()
CST = timezone(timedelta(hours=8))
REQUIRED_KEYS = ("USD", "EUR", "JPY_100", "GBP", "KRW_100")


def parse_updated_at(value: str) -> datetime:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S +08:00"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(f"unsupported updated_at format: {text!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-hours", type=float, default=24)
    args = parser.parse_args()

    path = exchange_rates_path()
    if not path.exists():
        raise SystemExit(f"EXCHANGE_RATES_STALE: missing {path}")

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rates = data.get("rates_to_cny") or {}
    missing = [key for key in REQUIRED_KEYS if key not in rates]
    if missing:
        raise SystemExit(f"EXCHANGE_RATES_STALE: missing rates {', '.join(missing)}")
    for key in REQUIRED_KEYS:
        try:
            value = float(rates[key])
        except Exception as exc:
            raise SystemExit(f"EXCHANGE_RATES_STALE: invalid {key}={rates.get(key)!r}: {exc}")
        if value <= 0:
            raise SystemExit(f"EXCHANGE_RATES_STALE: non-positive {key}={value}")

    updated_at = parse_updated_at(str(data.get("updated_at") or ""))
    age = datetime.now(CST) - updated_at.astimezone(CST)
    if age > timedelta(hours=args.max_age_hours):
        raise SystemExit(
            "EXCHANGE_RATES_STALE: "
            f"updated_at={updated_at.astimezone(CST).isoformat(timespec='seconds')} "
            f"age_hours={age.total_seconds() / 3600:.2f} max={args.max_age_hours}"
        )
    print(
        "EXCHANGE_RATES_FRESH: "
        f"updated_at={updated_at.astimezone(CST).isoformat(timespec='seconds')} "
        f"USD={float(rates['USD']):.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
