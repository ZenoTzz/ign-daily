#!/usr/bin/env python3
"""Fetch and verify exchange rates before translation.

The translator must not trust a single free API blindly. This script reads
several independent JSON sources, converts them to CNY-per-currency rates, and
writes exchange_rates.json only when the sources broadly agree.
"""
from __future__ import annotations

import json
import os
import statistics
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from common_paths import configure_utf8_stdio, exchange_rates_path


configure_utf8_stdio()

OUT = exchange_rates_path()
CST = timezone(timedelta(hours=8))

SOURCES = [
    {
        "name": "open-er-api",
        "url": "https://open.er-api.com/v6/latest/USD",
        "kind": "rates_upper",
    },
    {
        "name": "exchangerate-api-v4",
        "url": "https://api.exchangerate-api.com/v4/latest/USD",
        "kind": "rates_upper",
    },
    {
        "name": "frankfurter",
        "url": "https://api.frankfurter.app/latest?from=USD&to=CNY,EUR,JPY,GBP,KRW",
        "kind": "rates_upper",
    },
    {
        "name": "currency-api-jsdelivr",
        "url": "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
        "kind": "usd_lower",
    },
]

REQUIRED_KEYS = ("USD", "EUR", "JPY_100", "GBP")
OPTIONAL_KEYS = ("KRW_100",)
SANITY_RANGES = {
    "USD": (5.0, 9.0),
    "EUR": (5.0, 12.0),
    "JPY_100": (3.0, 8.0),
    "GBP": (6.0, 14.0),
    "KRW_100": (0.3, 0.8),
}
MAX_CROSS_SOURCE_DEVIATION = 0.02
MAX_PREVIOUS_DEVIATION = 0.10


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_rates(payload: dict[str, Any], kind: str) -> dict[str, float]:
    if kind == "rates_upper":
        rates = payload.get("rates") or {}
        lookup = {
            "CNY": rates.get("CNY"),
            "EUR": rates.get("EUR"),
            "JPY": rates.get("JPY"),
            "GBP": rates.get("GBP"),
            "KRW": rates.get("KRW"),
        }
    elif kind == "usd_lower":
        rates = payload.get("usd") or {}
        lookup = {
            "CNY": rates.get("cny"),
            "EUR": rates.get("eur"),
            "JPY": rates.get("jpy"),
            "GBP": rates.get("gbp"),
            "KRW": rates.get("krw"),
        }
    else:
        raise ValueError(f"unknown source kind: {kind}")

    cny_per_usd = float(lookup["CNY"])
    normalized = {
        "USD": cny_per_usd,
        "EUR": cny_per_usd / float(lookup["EUR"]),
        "JPY_100": cny_per_usd / float(lookup["JPY"]) * 100,
        "GBP": cny_per_usd / float(lookup["GBP"]),
    }
    if lookup.get("KRW"):
        normalized["KRW_100"] = cny_per_usd / float(lookup["KRW"]) * 100
    return normalized


def collect_sources() -> list[dict[str, Any]]:
    results = []
    errors = []
    for source in SOURCES:
        try:
            payload = fetch_json(source["url"])
            rates = normalize_rates(payload, source["kind"])
            results.append({
                "name": source["name"],
                "url": source["url"],
                "rates_to_cny": rates,
            })
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")
            print(f"[warn] {source['name']}: {exc}")
    if len(results) < 2:
        raise RuntimeError("exchange-rate verification needs at least 2 working sources; " + "; ".join(errors))
    return results


def load_previous() -> dict[str, float]:
    if not OUT.exists():
        return {}
    try:
        data = json.loads(OUT.read_text(encoding="utf-8-sig"))
        rates = data.get("rates_to_cny") or {}
        return {key: float(value) for key, value in rates.items()}
    except Exception:
        return {}


def assert_sane(key: str, value: float) -> None:
    low, high = SANITY_RANGES[key]
    if not (low <= value <= high):
        raise RuntimeError(f"{key}={value:.6f} is outside sane range {low}-{high}")


def verified_median(sources: list[dict[str, Any]], previous: dict[str, float]) -> tuple[dict[str, float], dict[str, Any]]:
    verified: dict[str, float] = {}
    checks: dict[str, Any] = {}

    for key in (*REQUIRED_KEYS, *OPTIONAL_KEYS):
        values = [
            float(source["rates_to_cny"][key])
            for source in sources
            if key in source.get("rates_to_cny", {})
        ]
        if key in REQUIRED_KEYS and len(values) < 2:
            raise RuntimeError(f"{key} has fewer than 2 source values")
        if not values:
            continue

        median = statistics.median(values)
        assert_sane(key, median)
        max_deviation = max(abs(value - median) / median for value in values)
        if max_deviation > MAX_CROSS_SOURCE_DEVIATION:
            raise RuntimeError(
                f"{key} sources disagree too much: median={median:.6f}, "
                f"max_deviation={max_deviation:.2%}, values={values}"
            )

        previous_value = previous.get(key)
        previous_deviation = None
        if previous_value:
            previous_deviation = abs(median - previous_value) / previous_value
            if previous_deviation > MAX_PREVIOUS_DEVIATION and os.environ.get("ALLOW_EXCHANGE_RATE_JUMP") != "1":
                raise RuntimeError(
                    f"{key} changed {previous_deviation:.2%} from previous trusted value "
                    f"{previous_value:.6f} to {median:.6f}; set ALLOW_EXCHANGE_RATE_JUMP=1 to override"
                )

        verified[key] = round(median, 2)
        checks[key] = {
            "source_count": len(values),
            "median_raw": round(median, 6),
            "max_cross_source_deviation": round(max_deviation, 6),
            "previous_deviation": None if previous_deviation is None else round(previous_deviation, 6),
        }

    return verified, checks


def main() -> int:
    sources = collect_sources()
    previous = load_previous()
    rates, checks = verified_median(sources, previous)

    out = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S +08:00"),
        "source": "multi-source median",
        "base": "USD",
        "rates_to_cny": rates,
        "validation": {
            "verified": True,
            "required_sources_min": 2,
            "source_count": len(sources),
            "max_cross_source_deviation_allowed": MAX_CROSS_SOURCE_DEVIATION,
            "checks": checks,
            "sources": [
                {
                    "name": source["name"],
                    "url": source["url"],
                    "rates_to_cny": {
                        key: round(value, 6)
                        for key, value in source["rates_to_cny"].items()
                    },
                }
                for source in sources
            ],
        },
        "note": "CNY reference rates verified by multiple sources. Translation code must recalculate CNY amounts from this file.",
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] verified exchange rates from {len(sources)} sources: {OUT}")
    for key, value in rates.items():
        label = "100 JPY" if key == "JPY_100" else "100 KRW" if key == "KRW_100" else f"1 {key}"
        print(f"  {label} = {value} CNY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
