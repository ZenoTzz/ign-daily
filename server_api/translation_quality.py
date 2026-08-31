"""Hard completion gate for newly produced full-text translations."""
from __future__ import annotations

import re
from typing import Any


QUALITY_GATE_VERSION = 1
REQUIRED_METADATA = (
    "translator",
    "translator_provider",
    "translator_model",
    "reasoning_effort",
    "reviewer_model",
    "reviewed_at",
    "prompt_version",
)
REQUIRED_REVIEW_CHECKS = (
    "source_coverage",
    "quote_attribution",
    "numeric_facts",
)

_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?%?")
_DIRECT_QUOTE_RE = re.compile(r'(?:"[^"\n]{8,}"|“[^”\n]{8,}”)')
_QUOTE_ATTRIBUTION_RE = re.compile(
    r"\b(?:said|says|told|wrote|added|replied|explained|according to)\b",
    re.IGNORECASE,
)
_REPEATED_QUESTION_MARK_RE = re.compile(r"\?{3,}")
_MOJIBAKE_RE = re.compile(r"(?:Ã.|Â.|â[€ž™œ]|ï¿½|ðŸ|[\u0080-\u009f])")


def _visible_translation_text(data: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key in ("cn_title", "subtitle", "opus_summary"):
        value = data.get(key)
        if isinstance(value, str) and value:
            fields.append((key, value))
    paragraphs = data.get("paragraphs")
    if isinstance(paragraphs, list):
        for position, item in enumerate(paragraphs, start=1):
            if isinstance(item, dict):
                value = item.get("cn")
                if isinstance(value, str) and value:
                    fields.append((f"paragraph {position}", value))
    return fields


def _encoding_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field, text in _visible_translation_text(data):
        if _REPEATED_QUESTION_MARK_RE.search(text):
            errors.append(f"{field} contains repeated question marks and may be encoding-damaged")
        if "\ufffd" in text:
            errors.append(f"{field} contains the Unicode replacement character")
        if _MOJIBAKE_RE.search(text):
            errors.append(f"{field} contains likely mojibake")
    return errors


def _number_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _NUMBER_RE.finditer(text or ""):
        token = match.group(0).replace(",", "")
        digits = re.sub(r"\D", "", token)
        if "%" in token:
            tokens.add(token)
            continue

        suffix = (text or "")[match.end():]
        multiplier = 1.0
        unit_match = re.match(r"\s*(billion|million|thousand)\b", suffix, re.IGNORECASE)
        if unit_match:
            multiplier = {
                "billion": 1_000_000_000.0,
                "million": 1_000_000.0,
                "thousand": 1_000.0,
            }[unit_match.group(1).lower()]
        elif re.match(r"\s*亿", suffix):
            multiplier = 100_000_000.0
        elif re.match(r"\s*万", suffix):
            multiplier = 10_000.0
        elif re.match(r"\s*[Kk]\b", suffix):
            # Product names commonly retain the compact suffix, for example
            # Warhammer 40,000 -> 战锤40K.
            multiplier = 1_000.0

        if multiplier != 1.0:
            tokens.add(f"{float(token) * multiplier:g}")
        elif "." in token or len(digits) >= 2:
            tokens.add(token)
    return tokens


def deterministic_review_errors(data: dict[str, Any]) -> list[str]:
    """Catch high-confidence omissions before trusting the semantic review."""
    errors = _encoding_errors(data)
    paragraphs = data.get("paragraphs")
    if not isinstance(paragraphs, list):
        return ["paragraphs must be a list"]
    for position, item in enumerate(paragraphs, start=1):
        if not isinstance(item, dict):
            errors.append(f"paragraph {position} is not an object")
            continue
        english = str(item.get("en") or "").strip()
        chinese = str(item.get("cn") or "").strip()
        if english and len(english) >= 120 and len(chinese) < max(18, int(len(english) * 0.16)):
            errors.append(f"paragraph {position} is suspiciously short and may omit source content")
        missing_numbers = sorted(_number_tokens(english) - _number_tokens(chinese))
        if missing_numbers:
            errors.append(
                f"paragraph {position} is missing numeric fact(s): {', '.join(missing_numbers)}"
            )
        if _DIRECT_QUOTE_RE.search(english) and _QUOTE_ATTRIBUTION_RE.search(english) and not (
            ("「" in chinese and "」" in chinese) or ("『" in chinese and "』" in chinese)
        ):
            errors.append(f"paragraph {position} contains a direct quote without Chinese quote marks")
    return errors


def validate_translation_quality(data: dict[str, Any]) -> list[str]:
    """Return blocking errors for the versioned completion contract."""
    errors = [
        f"missing metadata: {key}"
        for key in REQUIRED_METADATA
        if not str(data.get(key) or "").strip()
    ]
    if data.get("quality_gate_version") != QUALITY_GATE_VERSION:
        errors.append(f"quality_gate_version must be {QUALITY_GATE_VERSION}")
    review = data.get("quality_review")
    if not isinstance(review, dict):
        errors.append("missing quality_review")
    else:
        if review.get("status") != "passed":
            errors.append("quality_review.status must be passed")
        checks = review.get("checks")
        if not isinstance(checks, dict):
            errors.append("quality_review.checks must be an object")
        else:
            for key in REQUIRED_REVIEW_CHECKS:
                if checks.get(key) is not True:
                    errors.append(f"quality_review check not passed: {key}")
        if str(review.get("reviewer_model") or "").strip() != str(data.get("reviewer_model") or "").strip():
            errors.append("quality_review.reviewer_model must match reviewer_model")
        if str(review.get("reviewed_at") or "").strip() != str(data.get("reviewed_at") or "").strip():
            errors.append("quality_review.reviewed_at must match reviewed_at")
    errors.extend(deterministic_review_errors(data))
    return errors
