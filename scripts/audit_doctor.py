#!/usr/bin/env python3
"""Model-assisted diagnosis for deterministic translation audit failures.

The deterministic audit remains the gate. This helper only explains likely
false positives, mainly dictionary-context mistakes, and returns structured
JSON so automation can decide whether to suppress a specific failure.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR, configure_utf8_stdio, env_paths
from translate_titles_deepseek import call_deepseek_response, extract_json
from usage_logger import record_deepseek_usage_safe

configure_utf8_stdio()


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


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def issue_term(issue: dict[str, Any]) -> str:
    if issue.get("en"):
        return str(issue["en"])
    detail = str(issue.get("detail") or "")
    m = re.search(r"source contains '([^']+)'", detail)
    return m.group(1) if m else ""


def context_for_term(term: str, paragraphs_en: list[str], max_chars: int = 360) -> str:
    if not term:
        return ""
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)
    text = "\n\n".join(paragraphs_en)
    match = pattern.search(text)
    if not match:
        loose = re.search(re.escape(term), text, re.I)
        match = loose
    if not match:
        return ""
    start = max(0, match.start() - max_chars // 2)
    end = min(len(text), match.end() + max_chars // 2)
    return text[start:end].replace("\n", " ").strip()


def deterministic_false_positive(issue: dict[str, Any], context: str, article: dict[str, Any]) -> str:
    term = issue_term(issue)
    category = str(article.get("category") or "")
    lower_context = context.lower()
    if issue.get("type") != "dictionary":
        return ""
    if term == "Doom" and re.search(r"(?i)\b(?:dr\.?\s+doom|doctor\s+doom|doomsday)\b", context):
        return "Doom is used as Marvel Doctor Doom or inside Doomsday, not the game Doom."
    if term == "Blur" and "blurb" in lower_context:
        return "Blur is only part of the common word blurb."
    if term == "Tangled" and "entangled" in lower_context:
        return "Tangled is only part of the common word entangled."
    if term == "Variety" and re.search(r"(?<![A-Za-z0-9])variety(?![A-Za-z0-9])", context) and "Variety" not in context:
        return "variety is used as a common noun, not the media outlet Variety."
    if term == "The Guardian" and "guardian of light" in lower_context:
        return "Guardian appears inside a different game title, not the newspaper The Guardian."
    if "\u5f71\u89c6" in category and term in {"Doom"}:
        return "Movie/TV article context should not force a game dictionary entry."
    return ""


def build_messages(article: dict[str, Any], issues: list[dict[str, Any]], contexts: dict[str, str]) -> list[dict[str, str]]:
    payload = {
        "task": "Diagnose deterministic translation audit failures. Decide whether each issue is a true failure or a false positive.",
        "rules": [
            "Only return false_positive when the required dictionary term is clearly the wrong sense or wrong category.",
            "Do not waive paragraph count, JSON shape, missing translation, or currency conversion issues.",
            "Return strict JSON only.",
        ],
        "article": {
            "id": article.get("id"),
            "category": article.get("category"),
            "en_title": article.get("en_title"),
            "cn_title": article.get("cn_title"),
            "url": article.get("url"),
        },
        "issues": issues,
        "source_contexts": contexts,
        "schema": {
            "verdict": "false_positive|repairable|needs_human",
            "confidence": "low|medium|high",
            "false_positive_terms": ["English term strings to suppress"],
            "reason": "short explanation",
        },
    }
    return [
        {"role": "system", "content": "You are an audit doctor for Chinese IGN article translations. Output strict JSON only."},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def diagnose(
    *,
    article: dict[str, Any],
    paragraphs_en: list[str],
    issues: list[dict[str, Any]],
    api_key: str = "",
    model: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    dictionary_issues = [issue for issue in issues if issue.get("type") == "dictionary"]
    if not dictionary_issues or len(dictionary_issues) != len(issues):
        return {"verdict": "needs_human", "confidence": "high", "false_positive_terms": [], "reason": "Non-dictionary audit issues require hard validation or human review."}

    contexts = {issue_term(issue): context_for_term(issue_term(issue), paragraphs_en) for issue in dictionary_issues}
    deterministic_reasons = []
    false_terms = []
    for issue in dictionary_issues:
        term = issue_term(issue)
        reason = deterministic_false_positive(issue, contexts.get(term, ""), article)
        if reason:
            false_terms.append(term)
            deterministic_reasons.append(reason)

    if len(false_terms) == len(dictionary_issues):
        return {
            "verdict": "false_positive",
            "confidence": "high",
            "false_positive_terms": false_terms,
            "reason": " ".join(deterministic_reasons),
            "doctor": "deterministic",
        }

    if not api_key or os.environ.get("AUDIT_DOCTOR_API", "1") == "0":
        return {"verdict": "needs_human", "confidence": "medium", "false_positive_terms": false_terms, "reason": "Dictionary issue was not covered by deterministic doctor and API doctor is unavailable."}

    doctor_model = model or os.environ.get("TRANSLATOR_MODEL") or "deepseek-v4-flash"
    try:
        raw, usage = call_deepseek_response(
            api_key,
            doctor_model,
            base_url or os.environ.get("TRANSLATOR_BASE_URL") or "https://api.deepseek.com",
            build_messages(article, dictionary_issues, contexts),
            max_tokens=900,
        )
        record_deepseek_usage_safe(
            task="audit_doctor",
            model=doctor_model,
            usage=usage,
            article_id=article.get("id"),
            article_title=article.get("cn_title") or article.get("en_title"),
            article_url=article.get("url"),
            article_date=str(article.get("publish_time_cn") or "")[:10],
        )
        result = extract_json(raw)
    except Exception as exc:
        return {
            "verdict": "needs_human",
            "confidence": "medium",
            "false_positive_terms": false_terms,
            "reason": f"API doctor failed: {exc}",
            "doctor": "api",
        }
    verdict = str(result.get("verdict") or "needs_human")
    if verdict not in {"false_positive", "repairable", "needs_human"}:
        verdict = "needs_human"
    terms = result.get("false_positive_terms")
    if not isinstance(terms, list):
        terms = []
    return {
        "verdict": verdict,
        "confidence": str(result.get("confidence") or "low"),
        "false_positive_terms": [str(x) for x in terms],
        "reason": str(result.get("reason") or ""),
        "doctor": "api",
    }


def main() -> int:
    load_env_file()
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/audit_doctor.py YYYY-MM-DD ID", file=sys.stderr)
        return 2
    date, aid_s = sys.argv[1], sys.argv[2]
    aid = int(aid_s)
    index = load_json(DATA_DIR / date / "index.json")
    article = next((a for a in index.get("articles", []) if int(a.get("id", -1)) == aid), None)
    if not article:
        raise SystemExit(f"article not found: {date} #{aid}")
    source = load_json(DATA_DIR / date / "sources" / f"{aid:02d}.json")
    failures = load_json(DATA_DIR / date / "translation_failures.json")
    failure = failures.get("items", {}).get(str(aid), {})
    body = str(source.get("body_en") or "")
    paragraphs = [p.strip() for p in re.split(r"\n{1,}", body) if p.strip()]
    result = diagnose(
        article=article,
        paragraphs_en=paragraphs,
        issues=failure.get("audit_issues") or [],
        api_key=os.environ.get("TRANSLATOR_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "",
        model=os.environ.get("TRANSLATOR_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
        base_url=os.environ.get("TRANSLATOR_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
