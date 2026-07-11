"""Quality gates and alignment helpers for learning v2.

Mechanical diff code may create evidence, but it must never promote a rule.
This module keeps that boundary deterministic and testable.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

EVIDENCE_ONLY = "observed"
REVIEW_READY = "ready_for_review"


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def align_paragraphs(before: list[str], after: list[str]) -> list[dict[str, Any]]:
    """Align paragraphs without shifting every later paragraph after an insert/delete."""
    left = [normalize_text(x) for x in before]
    right = [normalize_text(x) for x in after]
    matcher = SequenceMatcher(a=left, b=right, autojunk=False)
    changes: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append({
            "operation": tag,
            "before_range": [i1, i2],
            "after_range": [j1, j2],
            "before": left[i1:i2],
            "after": right[j1:j2],
        })
    return changes


def candidate_quality(en: str, cn: str, *, source_text: str = "", origin: str = "heuristic") -> dict[str, Any]:
    """Return a conservative verdict for a possible dictionary mapping."""
    en = normalize_text(en).strip(" -—:;,.!?\"'“”‘’[]()")
    cn = normalize_text(cn).strip("《》 ")
    reasons: list[str] = []
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'.-]*", en)
    sentence_markers = {"of", "the", "ahead", "showcase", "developer", "says", "new", "data", "after", "before"}
    lower_words = {w.lower() for w in words}

    if not en or not cn:
        reasons.append("empty_mapping")
    if en.casefold() == cn.casefold():
        reasons.append("identity_mapping")
    if len(en) > 60 or len(words) > 6:
        reasons.append("phrase_too_long")
    if len(words) >= 4 and len(lower_words & sentence_markers) >= 2:
        reasons.append("headline_fragment")
    if origin == "headline_pair" and not source_text:
        reasons.append("missing_source_context")
    if source_text and en.casefold() not in normalize_text(source_text).casefold():
        reasons.append("not_found_in_source")

    hard_reject = {"empty_mapping", "identity_mapping", "phrase_too_long", "headline_fragment", "not_found_in_source"}
    accepted_as_evidence = not any(reason in hard_reject for reason in reasons)
    return {
        "accepted_as_evidence": accepted_as_evidence,
        "status": EVIDENCE_ONLY if accepted_as_evidence else "quarantined",
        "reasons": reasons,
        "requires_semantic_review": True,
    }


def promotion_status(*, days_seen: int, articles_seen: int, contradictions: int = 0,
                     semantic_review: str = "pending", user_confirmed: bool = False) -> str:
    """State machine: evidence never self-promotes without semantic review."""
    if user_confirmed:
        return "confirmed"
    if semantic_review == "rejected" or contradictions:
        return "rejected" if semantic_review == "rejected" else "observed"
    if semantic_review != "approved":
        return "observed"
    if days_seen >= 2 and articles_seen >= 3:
        return REVIEW_READY
    return "observed"

