#!/usr/bin/env python3
"""Currency normalization helpers for translation outputs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common_paths import exchange_rates_path


DEFAULT_RATES_TO_CNY = {
    "USD": 6.77,
    "EUR": 7.85,
    "GBP": 9.09,
    "JPY_100": 4.23,
    "KRW_100": 0.45,
}

AMOUNT_RE = r"\d+(?:,\d{3})*(?:\.\d+)?"
CURRENCY_RE = re.compile(rf"({AMOUNT_RE})\s*(万|亿)?\s*(美元|欧元|英镑|日元)")
RANGE_CURRENCY_RE = re.compile(rf"(?<![\d.,])({AMOUNT_RE})\s*至\s*({AMOUNT_RE})\s*(万|亿)?\s*(美元|欧元|英镑|日元)(?:[（(]\s*约合人民币[^）)]*[）)])?")
SINGLE_CURRENCY_WITH_CONVERSION_RE = re.compile(rf"(?<![\d.,])({AMOUNT_RE})\s*(万|亿)?\s*(美元|欧元|英镑|日元)(?:[（(]\s*约合人民币[^）)]*[）)])?")
SYMBOL_PREFIX_RE = re.compile(rf"(?i)(US\$|\$|€|£)\s*({AMOUNT_RE})\s*(万|亿)?")
CODE_SUFFIX_RE = re.compile(rf"(?i)({AMOUNT_RE})\s*(万|亿)?\s*(USD|EUR|GBP|JPY)\b")


def load_rates() -> dict[str, float]:
    path = exchange_rates_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            rates = data.get("rates_to_cny", {})
            if isinstance(rates, dict):
                merged = DEFAULT_RATES_TO_CNY.copy()
                for key, value in rates.items():
                    try:
                        merged[key] = float(value)
                    except Exception:
                        pass
                return merged
        except Exception:
            pass
    return DEFAULT_RATES_TO_CNY.copy()


def parse_amount(amount: str, chinese_unit: str | None = "") -> float:
    value = float(str(amount).replace(",", ""))
    if chinese_unit == "万":
        value *= 10_000
    elif chinese_unit == "亿":
        value *= 100_000_000
    return value


def cny_value(amount: str, chinese_unit: str | None, currency: str, rates: dict[str, float]) -> float | None:
    try:
        value = parse_amount(amount, chinese_unit)
    except Exception:
        return None
    key = {"美元": "USD", "欧元": "EUR", "英镑": "GBP", "日元": "JPY_100"}.get(currency)
    if not key or key not in rates:
        return None
    if currency == "日元":
        return value / 100 * rates[key]
    return value * rates[key]


def format_cny(value: float | None) -> str:
    if value is None:
        return "?元"
    if value >= 100_000_000:
        return f"{round(value / 100_000_000):.0f}亿元"
    if value >= 10_000:
        return f"{round(value / 10_000):.0f}万元"
    return f"{round(value):.0f}元"


def format_cny_range(low: float | None, high: float | None) -> str:
    first = format_cny(low)
    second = format_cny(high)
    match_first = re.fullmatch(r"([0-9?]+)(亿元|万元|元)", first)
    match_second = re.fullmatch(r"([0-9?]+)(亿元|万元|元)", second)
    if match_first and match_second and match_first.group(2) == match_second.group(2):
        return f"{match_first.group(1)}至{match_second.group(1)}{match_first.group(2)}"
    return f"{first}至{second}"


def normalize_currency_symbols(text: str) -> str:
    def repl_prefix(match: re.Match[str]) -> str:
        symbol = match.group(1)
        amount = match.group(2)
        unit = match.group(3) or ""
        currency = {"$": "美元", "US$": "美元", "€": "欧元", "£": "英镑"}[symbol.upper() if symbol.upper() == "US$" else symbol]
        return f"{amount}{unit}{currency}"

    def repl_suffix(match: re.Match[str]) -> str:
        amount = match.group(1)
        unit = match.group(2) or ""
        code = match.group(3).upper()
        currency = {"USD": "美元", "EUR": "欧元", "GBP": "英镑", "JPY": "日元"}[code]
        return f"{amount}{unit}{currency}"

    text = SYMBOL_PREFIX_RE.sub(repl_prefix, text)
    text = CODE_SUFFIX_RE.sub(repl_suffix, text)
    return text


def normalize_currency_text(text: str, *, rates: dict[str, float] | None = None) -> str:
    if not text:
        return text
    rates = rates or load_rates()
    text = normalize_currency_symbols(str(text))

    def repl_range(match: re.Match[str]) -> str:
        amount_low, amount_high = match.group(1), match.group(2)
        unit, currency = match.group(3) or "", match.group(4)
        low = cny_value(amount_low, unit, currency, rates)
        high = cny_value(amount_high, unit, currency, rates)
        return f"{amount_low}至{amount_high}{unit}{currency}(约合人民币{format_cny_range(low, high)})"

    def repl_single_with_conversion(match: re.Match[str]) -> str:
        if match.start() >= 2 and text[match.start() - 1] == "至" and re.match(r"[\d.]", text[match.start() - 2]):
            return match.group(0)
        amount, unit, currency = match.group(1), match.group(2) or "", match.group(3)
        cny = cny_value(amount, unit, currency, rates)
        return f"{amount}{unit}{currency}(约合人民币{format_cny(cny)})"

    text = RANGE_CURRENCY_RE.sub(repl_range, text)
    text = SINGLE_CURRENCY_WITH_CONVERSION_RE.sub(repl_single_with_conversion, text)

    def repl(match: re.Match[str]) -> str:
        amount, unit, currency = match.group(1), match.group(2) or "", match.group(3)
        tail = text[match.end():match.end() + 32]
        if "约合" in tail and "人民币" in tail:
            return match.group(0)
        cny = cny_value(amount, unit, currency, rates)
        return f"{amount}{unit}{currency}(约合人民币{format_cny(cny)})"

    return CURRENCY_RE.sub(repl, text)


def normalize_translation_currency(data: dict[str, Any]) -> dict[str, Any]:
    rates = load_rates()
    for key in ("cn_title", "subtitle", "opus_summary"):
        if isinstance(data.get(key), str):
            data[key] = normalize_currency_text(data[key], rates=rates)
    for para in data.get("paragraphs", []):
        if isinstance(para, dict) and isinstance(para.get("cn"), str):
            para["cn"] = normalize_currency_text(para["cn"], rates=rates)
    return data


def find_missing_currency(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    text = normalize_currency_symbols(str(text))
    issues = []
    for match in CURRENCY_RE.finditer(text):
        tail = text[match.end():match.end() + 32]
        if "约合" not in tail or "人民币" not in tail:
            issues.append((match.group(0), text[max(0, match.start() - 16):match.end() + 32]))
    return issues
