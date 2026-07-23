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


def _number_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _NUMBER_RE.finditer(text or ""):
        token = match.group(0).replace(",", "")
        digits = re.sub(r"\D", "", token)
        if "%" in token or "." in token or len(digits) >= 2:
            tokens.add(token)
    # Chinese translations commonly express English "million" values with
    # 亿/万 units. Include equivalent absolute and million-scale forms so a
    # faithful locked translation such as 120 million -> 1.2亿 is accepted.
    for match in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*亿", text or ""):
        value = float(match.group(1).replace(",", ""))
        tokens.add(f"{value * 100:g}")
        tokens.add(f"{value * 100_000_000:g}")
    for match in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*万", text or ""):
        value = float(match.group(1).replace(",", ""))
        tokens.add(f"{value * 10_000:g}")
        tokens.add(f"{value / 100:g}")
    return tokens


def deterministic_review_errors(data: dict[str, Any]) -> list[str]:
    """Catch high-confidence omissions before trusting the semantic review."""
    errors: list[str] = []
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
