#!/usr/bin/env python3
"""Long-term style learning with an OpenAI-compatible API.

Nightly learning is deliberately conservative:
- daily runs observe user edits/feedback and write candidate rules;
- candidates are merged into a long-term evidence pool;
- a weekly report is generated for user review;
- STYLE_PROFILE.md changes only when weekly feedback explicitly confirms rules.

This avoids letting the model rewrite the project's style memory from a single
day's samples.
"""
from __future__ import annotations

import hashlib
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
LEARNING_DIR = DATA_DIR / "learning"
DAILY_DIR = LEARNING_DIR / "daily"
WEEKLY_DIR = LEARNING_DIR / "weekly"
EVIDENCE_PATH = LEARNING_DIR / "style-evidence.json"
MAX_EXAMPLES_PER_RULE = 12


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


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(path: Path, max_chars: int = 30000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def slug(text: str, fallback: str = "rule") -> str:
    raw = re.sub(r"\s+", " ", text or "").strip().lower()
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    ascii_part = re.sub(r"[^a-z0-9]+", "_", raw)[:32].strip("_")
    return f"{ascii_part or fallback}_{digest}"


def split_polished_body(value: str) -> list[str]:
    if not value:
        return []
    chunks = [p.strip() for p in re.split(r"\n{2,}", value) if p.strip()]
    if len(chunks) <= 1:
        chunks = [p.strip() for p in value.splitlines() if p.strip()]
    return chunks


def polished_paragraphs(polished: dict[str, Any]) -> list[str]:
    paragraphs = polished.get("paragraphs")
    if isinstance(paragraphs, list):
        items: list[str] = []
        for para in paragraphs:
            if isinstance(para, str):
                text = para
            elif isinstance(para, dict):
                text = str(para.get("cn") or para.get("text") or "")
            else:
                text = ""
            text = text.strip()
            if text:
                items.append(text)
        if items:
            return items
    return split_polished_body(str(polished.get("body") or ""))


def compact_diff(before: str, after: str, max_chars: int = 360) -> dict[str, str]:
    return {
        "before": (before or "").strip()[:max_chars],
        "after": (after or "").strip()[:max_chars],
    }


def collect_user_edit_signals(date: str, limit: int = 12) -> list[dict[str, Any]]:
    day_dir = DATA_DIR / date
    trans_dir = day_dir / "translations"
    polished_dir = day_dir / "polished"
    polish_index = load_json(polished_dir / "_index.json", {}) or {}
    if not polish_index:
        return []

    signals: list[dict[str, Any]] = []
    for id_str, filename in list(polish_index.items())[:limit]:
        try:
            aid = int(id_str)
        except Exception:
            continue
        trans = load_json(trans_dir / f"{aid:02d}.json", {}) or {}
        polished = load_json(polished_dir / filename, {}) or {}
        if not trans or not polished:
            continue
        edits: list[dict[str, str]] = []
        title_after = str(polished.get("title") or "").strip()
        if title_after and title_after != str(trans.get("cn_title") or "").strip():
            edits.append({"field": "title", **compact_diff(str(trans.get("cn_title") or ""), title_after)})
        sub_after = str(polished.get("subtitle") or "").strip()
        sub_before = str(trans.get("subtitle") or trans.get("cn_subtitle") or "").strip()
        if sub_after and sub_after != sub_before:
            edits.append({"field": "subtitle", **compact_diff(sub_before, sub_after)})

        before_paras = [str(p.get("cn") or "") for p in trans.get("paragraphs", []) if isinstance(p, dict)]
        after_paras = polished_paragraphs(polished)
        for idx, (before, after) in enumerate(zip(before_paras, after_paras), start=1):
            if before.strip() != after.strip():
                edits.append({"field": f"paragraph_{idx}", **compact_diff(before, after)})
            if len(edits) >= 8:
                break
        if edits:
            signals.append({
                "type": "user_polish",
                "date": date,
                "article_id": aid,
                "url": trans.get("url"),
                "en_title": trans.get("en_title"),
                "cn_title": trans.get("cn_title"),
                "edits": edits[:8],
            })
    return signals


def collect_feedback_signals(date: str) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    feedback = load_json(DATA_DIR / "learning_log" / f"{date}_feedback.json", {}) or {}
    responses = load_json(DATA_DIR / "learning_log" / f"{date}_response.json", {}) or {}
    daily = load_json(DATA_DIR / "learning_log" / f"{date}.json", {}) or {}
    if not feedback:
        return signals
    known: dict[str, Any] = {}
    for item in daily.get("rules_confirmed", []) + daily.get("observations", []):
        if isinstance(item, dict) and item.get("id"):
            known[str(item["id"])] = item
    for rule_id, text in feedback.items():
        signals.append({
            "type": "user_feedback",
            "date": date,
            "rule_id": rule_id,
            "rule": known.get(rule_id, {}),
            "feedback": text,
            "response": responses.get(rule_id, {}),
        })
    return signals


def build_candidate_messages(date: str, signals: list[dict[str, Any]], current_profile: str, evidence: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是 IGN Daily 的长期风格观察员。你的任务不是重写 STYLE_PROFILE.md，"
        "而是从用户润色和明确反馈中提取可验证的候选规律。"
        "不要从未经用户修改的机器译文中学习。只输出严格 JSON。"
    )
    payload = {
        "project": "IGN Daily",
        "date": date,
        "current_style_profile_excerpt": current_profile[:12000],
        "existing_evidence_summary": {
            k: {
                "title": v.get("title"),
                "status": v.get("status"),
                "days_seen": v.get("days_seen", 0),
                "articles_seen": v.get("articles_seen", 0),
                "contradictions": v.get("contradictions", 0),
            }
            for k, v in list((evidence.get("rules") or {}).items())[:80]
        },
        "signals": signals,
        "task": {
            "instructions": [
                "只根据 signals 中的用户润色或用户反馈提取候选规律。",
                "候选规律必须可执行，不要写空泛审美判断。",
                "如果只是单篇特例，status_suggestion 用 observe。",
                "如果用户明确否定某规律，status_suggestion 用 reject。",
                "如果用户明确同意某规律，status_suggestion 用 confirm。",
                "给每条候选规律一个稳定 id_hint，优先使用英文小写下划线。",
            ],
            "required_json_schema": {
                "candidates": [{
                    "id_hint": "stable_snake_case_id",
                    "title": "候选规律标题",
                    "rule": "可执行的风格规则",
                    "category": "title|subtitle|body|dictionary|punctuation|currency|names|structure|other",
                    "scope": "all|games|movies_tv|reviews|only_when_...",
                    "status_suggestion": "observe|confirm|reject|refine",
                    "confidence": 0.0,
                    "evidence_summary": "为什么这样判断",
                    "examples": [{"date": date, "article_id": 1, "before": "原译", "after": "用户改法"}],
                    "contradiction": "如有冲突写明，没有则空字符串"
                }],
                "notes": ["本次不学习的原因或提醒"],
            },
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def looks_corrupted_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    question_count = stripped.count("?")
    if question_count >= 8:
        return True
    if question_count >= 4 and question_count / max(len(stripped), 1) > 0.18:
        return True
    return False


def candidate_has_corruption(candidate: dict[str, Any]) -> bool:
    fields: list[Any] = [
        candidate.get("title"),
        candidate.get("rule"),
        candidate.get("evidence_summary"),
        candidate.get("contradiction"),
    ]
    examples = candidate.get("examples")
    if isinstance(examples, list):
        for ex in examples:
            if isinstance(ex, dict):
                fields.extend([ex.get("before"), ex.get("after")])
    return any(looks_corrupted_text(value) for value in fields)


def merge_candidates(evidence: dict[str, Any], date: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    evidence.setdefault("version", 1)
    evidence.setdefault("rules", {})
    evidence["updated_at"] = datetime.now(CST).isoformat(timespec="seconds")
    rules: dict[str, Any] = evidence["rules"]
    for cand in candidates:
        if candidate_has_corruption(cand):
            print(f"NIGHTLY_STYLE_CANDIDATE_SKIP: date={date}, reason=corrupted_text, id={cand.get('id_hint') or ''}")
            continue
        title = str(cand.get("title") or cand.get("rule") or "").strip()
        rule_text = str(cand.get("rule") or title).strip()
        if not title or not rule_text:
            continue
        rid = re.sub(r"[^a-z0-9_]+", "_", str(cand.get("id_hint") or "").strip().lower()).strip("_")
        if len(rid) < 4:
            rid = slug(title + rule_text)
        entry = rules.setdefault(rid, {
            "id": rid,
            "title": title,
            "rule": rule_text,
            "category": cand.get("category") or "other",
            "scope": cand.get("scope") or "all",
            "status": "pending",
            "days": [],
            "days_seen": 0,
            "articles_seen": 0,
            "contradictions": 0,
            "examples": [],
            "feedback": [],
            "created_at": datetime.now(CST).isoformat(timespec="seconds"),
        })
        entry["title"] = title
        entry["rule"] = rule_text
        entry["category"] = cand.get("category") or entry.get("category") or "other"
        entry["scope"] = cand.get("scope") or entry.get("scope") or "all"
        entry["last_seen"] = date
        if date not in entry.setdefault("days", []):
            entry["days"].append(date)
        seen_articles = {
            str(ex.get("date")) + "#" + str(ex.get("article_id"))
            for ex in entry.get("examples", [])
            if isinstance(ex, dict)
        }
        for ex in cand.get("examples", []) if isinstance(cand.get("examples"), list) else []:
            key = str(ex.get("date") or date) + "#" + str(ex.get("article_id") or "")
            if key not in seen_articles:
                entry.setdefault("examples", []).append(ex)
                seen_articles.add(key)
        entry["examples"] = entry.get("examples", [])[-MAX_EXAMPLES_PER_RULE:]
        entry["days_seen"] = len(set(entry.get("days", [])))
        entry["articles_seen"] = len(seen_articles)
        if cand.get("contradiction"):
            entry["contradictions"] = int(entry.get("contradictions", 0)) + 1
            entry.setdefault("contradiction_notes", []).append({"date": date, "text": cand.get("contradiction")})
        suggestion = str(cand.get("status_suggestion") or "observe").lower()
        if suggestion == "reject":
            entry["status"] = "rejected"
        elif suggestion == "confirm":
            entry["status"] = "confirmed_by_feedback"
        elif entry.get("status") not in ("confirmed_by_feedback", "confirmed", "rejected"):
            if entry["days_seen"] >= 3 and entry["articles_seen"] >= 5 and not entry.get("contradictions"):
                entry["status"] = "ready_for_review"
            else:
                entry["status"] = "pending"
        entry["confidence"] = max(float(entry.get("confidence") or 0), float(cand.get("confidence") or 0))
        if cand.get("evidence_summary"):
            entry["latest_evidence_summary"] = cand.get("evidence_summary")
    return evidence


def week_id_for(date: str) -> str:
    d = datetime.strptime(date, "%Y-%m-%d").date()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def build_weekly_report(evidence: dict[str, Any], date: str) -> dict[str, Any]:
    week_id = week_id_for(date)
    today = datetime.strptime(date, "%Y-%m-%d").date()
    week_start = today - timedelta(days=today.weekday())
    week_dates = [(week_start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    rules = evidence.get("rules", {})
    candidates = []
    for entry in rules.values():
        if not isinstance(entry, dict):
            continue
        days = set(entry.get("days", []))
        if days.intersection(week_dates) or entry.get("status") in ("ready_for_review", "confirmed_by_feedback"):
            candidates.append(entry)
    candidates.sort(key=lambda r: (
        0 if r.get("status") == "ready_for_review" else 1,
        -int(r.get("days_seen", 0)),
        -int(r.get("articles_seen", 0)),
        str(r.get("title") or ""),
    ))
    report = {
        "week_id": week_id,
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "range": {"start": week_dates[0], "end": week_dates[-1]},
        "summary": {
            "candidate_count": len(candidates),
            "ready_for_review": sum(1 for r in candidates if r.get("status") == "ready_for_review"),
            "confirmed_by_feedback": sum(1 for r in candidates if r.get("status") == "confirmed_by_feedback"),
            "pending": sum(1 for r in candidates if r.get("status") == "pending"),
        },
        "candidates": candidates[:40],
        "instructions_for_user": [
            "采纳：表示这条可以进入长期 STYLE_PROFILE.md。",
            "否定：表示这条不是你的偏好，后续不要再提。",
            "限定：说明只适用于某类文章，例如影视新闻/评测/标题。",
            "暂缓：继续观察，不写入正式规则。",
        ],
    }
    write_json(WEEKLY_DIR / f"{week_id}.json", report)
    index = load_json(WEEKLY_DIR / "_index.json", {"weeks": []}) or {"weeks": []}
    if week_id not in index.setdefault("weeks", []):
        index["weeks"].append(week_id)
        index["weeks"] = sorted(index["weeks"])
    write_json(WEEKLY_DIR / "_index.json", index)
    return report


def load_weekly_feedback(week_id: str) -> dict[str, Any]:
    return load_json(WEEKLY_DIR / f"{week_id}_feedback.json", {}) or {}


def classify_feedback(text: str) -> str:
    t = text or ""
    reject_words = ("否定", "不要", "不对", "不适用", "错误", "别学", "不是规律")
    confirm_words = ("采纳", "同意", "确认", "以后都", "按这个", "进入规则")
    refine_words = ("限定", "只适用", "改成", "补充", "但是", "除非")
    if any(w in t for w in reject_words):
        return "rejected"
    if any(w in t for w in refine_words):
        return "confirmed_with_scope"
    if any(w in t for w in confirm_words):
        return "confirmed"
    return "pending"


def apply_weekly_feedback(evidence: dict[str, Any], week_id: str) -> bool:
    feedback = load_weekly_feedback(week_id)
    if not feedback:
        return False
    changed = False
    rules = evidence.setdefault("rules", {})
    for rid, value in feedback.items():
        if rid not in rules:
            continue
        text = str(value.get("text") if isinstance(value, dict) else value).strip()
        if not text:
            continue
        status = classify_feedback(text)
        entry = rules[rid]
        entry.setdefault("feedback", []).append({
            "week_id": week_id,
            "text": text,
            "classified_as": status,
            "created_at": datetime.now(CST).isoformat(timespec="seconds"),
        })
        if status == "rejected":
            entry["status"] = "rejected"
        elif status in ("confirmed", "confirmed_with_scope"):
            entry["status"] = "confirmed"
            if status == "confirmed_with_scope":
                entry["scope_note"] = text
        changed = True
    return changed


def render_confirmed_profile(current_profile: str, evidence: dict[str, Any]) -> str:
    confirmed = [
        r for r in (evidence.get("rules") or {}).values()
        if isinstance(r, dict) and r.get("status") == "confirmed"
    ]
    confirmed.sort(key=lambda r: (str(r.get("category") or ""), str(r.get("title") or "")))
    if not confirmed:
        return current_profile

    lines = [
        "## API 长期学习确认规则",
        "",
        "以下规则来自每周学习报告，并经过用户批注确认。API 每日观察不得绕过这些规则。",
        "",
    ]
    for r in confirmed:
        evidence_bits = []
        if r.get("days_seen"):
            evidence_bits.append(f"跨 {r.get('days_seen')} 天")
        if r.get("articles_seen"):
            evidence_bits.append(f"{r.get('articles_seen')} 篇样本")
        suffix = f"（{'，'.join(evidence_bits)}）" if evidence_bits else ""
        scope = r.get("scope_note") or r.get("scope") or "all"
        lines.append(f"- **{r.get('title')}**{suffix}")
        lines.append(f"  - 规则：{r.get('rule')}")
        lines.append(f"  - 适用范围：{scope}")
    block = "\n".join(lines).rstrip() + "\n"

    marker = "## API 长期学习确认规则"
    if marker in current_profile:
        prefix = current_profile[:current_profile.index(marker)].rstrip()
        return prefix + "\n\n" + block
    return current_profile.rstrip() + "\n\n---\n\n" + block


def source_fingerprint(date: str) -> str:
    day_dir = DATA_DIR / date
    chunks: list[bytes] = []
    for rel in [
        day_dir / "polished" / "_index.json",
        day_dir / "feedback.json",
        DATA_DIR / "learning" / "weekly" / f"{week_id_for(date)}_feedback.json",
    ]:
        if rel.exists():
            chunks.append(str(rel.relative_to(DATA_DIR)).encode("utf-8"))
            chunks.append(rel.read_bytes())
    index = load_json(day_dir / "polished" / "_index.json", {}) or {}
    if isinstance(index, dict):
        for filename in sorted(str(v) for v in index.values()):
            path = day_dir / "polished" / filename
            if path.exists():
                chunks.append(filename.encode("utf-8"))
                chunks.append(path.read_bytes())
    return hashlib.sha1(b"\n".join(chunks)).hexdigest()


def dates_needing_observation(scan_days: int) -> list[str]:
    today = default_date()
    available = sorted(
        [p.name for p in DATA_DIR.glob("20??-??-??") if p.is_dir()],
        reverse=True,
    )
    selected: list[str] = []
    for date in available[:max(scan_days, 1)]:
        day_dir = DATA_DIR / date
        if not ((day_dir / "polished" / "_index.json").exists() or (day_dir / "feedback.json").exists()):
            continue
        current_hash = source_fingerprint(date)
        daily = load_json(DAILY_DIR / f"{date}.json", {}) or {}
        if date == today or daily.get("source_hash") != current_hash:
            selected.append(date)
    return list(reversed(selected))


def text_excerpt(value: str, max_chars: int = 1200) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:max_chars]


def parse_candidate_json_with_repair(
    api_key: str,
    model: str,
    base_url: str,
    raw: str,
    original_error: Exception,
    date: str,
) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None, str | None]:
    print(f"NIGHTLY_STYLE_JSON_REPAIR: date={date}, error={type(original_error).__name__}: {original_error}")
    repair_messages = [
        {
            "role": "system",
            "content": (
                "You repair malformed JSON from a style-learning observer. "
                "Return valid JSON only. Do not add markdown. The root object must contain "
                "a candidates array and a notes array. Preserve useful candidate content; "
                "drop incomplete trailing objects if they cannot be repaired."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "date": date,
                    "parse_error": str(original_error),
                    "required_shape": {"candidates": [], "notes": []},
                    "malformed_output": raw[:12000],
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        repair_raw, repair_usage = call_deepseek_response(
            api_key,
            model,
            base_url,
            repair_messages,
            max_tokens=int(os.environ.get("NIGHTLY_STYLE_REPAIR_MAX_TOKENS", "2500")),
        )
        record_deepseek_usage_safe(
            task="nightly_observe_json_repair",
            model=model,
            usage=repair_usage,
            article_date=date,
            detail=f"raw_chars={len(raw)}",
        )
        return extract_json(repair_raw), repair_raw, repair_usage, None
    except Exception as repair_error:
        print(f"NIGHTLY_STYLE_JSON_REPAIR_FAILED: date={date}, error={type(repair_error).__name__}: {repair_error}")
        return None, locals().get("repair_raw", ""), locals().get("repair_usage"), str(repair_error)


def run(date: str) -> int:
    load_env_file()
    api_key = (os.environ.get("TRANSLATOR_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        print("NIGHTLY_STYLE_API_SKIP: TRANSLATOR_API_KEY/DEEPSEEK_API_KEY is not set")
        return 0
    model = (os.environ.get("NIGHTLY_STYLE_MODEL") or os.environ.get("TRANSLATOR_MODEL") or "").strip() or DEFAULT_MODEL
    base_url = (os.environ.get("TRANSLATOR_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "").strip() or DEFAULT_BASE_URL

    profile_path = REPO_ROOT / "STYLE_PROFILE.md"
    current_profile = read_text(profile_path, 30000)
    evidence = load_json(EVIDENCE_PATH, {"version": 1, "rules": {}}) or {"version": 1, "rules": {}}

    week_id = week_id_for(date)
    if apply_weekly_feedback(evidence, week_id):
        new_profile = render_confirmed_profile(current_profile, evidence)
        profile_path.write_text(new_profile.rstrip() + "\n", encoding="utf-8")

    signals = collect_user_edit_signals(date) + collect_feedback_signals(date)
    if signals:
        raw, usage = call_deepseek_response(
            api_key,
            model,
            base_url,
            build_candidate_messages(date, signals, current_profile, evidence),
            max_tokens=int(os.environ.get("NIGHTLY_STYLE_MAX_TOKENS", "5000")),
        )
        record_deepseek_usage_safe(
            task="nightly_observe",
            model=model,
            usage=usage,
            article_date=date,
            detail=f"signals={len(signals)}",
        )
        repaired = False
        try:
            result = extract_json(raw)
        except Exception as parse_error:
            result, repair_raw, _repair_usage, repair_error = parse_candidate_json_with_repair(
                api_key,
                model,
                base_url,
                raw,
                parse_error,
                date,
            )
            repaired = result is not None
            if result is None:
                write_json(DAILY_DIR / f"{date}.json", {
                    "date": date,
                    "model": model,
                    "status": "skipped",
                    "reason": "json_parse_failed",
                    "source_hash": source_fingerprint(date),
                    "signal_count": len(signals),
                    "candidate_count": 0,
                    "signals": signals,
                    "candidates": [],
                    "notes": [
                        "API returned malformed JSON; automatic repair did not produce valid JSON.",
                    ],
                    "parse_error": str(parse_error),
                    "repair_error": repair_error,
                    "raw_excerpt": text_excerpt(raw),
                    "repair_excerpt": text_excerpt(repair_raw),
                    "updated_at": datetime.now(CST).isoformat(timespec="seconds"),
                })
                print(f"NIGHTLY_STYLE_OBSERVE_SKIP: date={date}, reason=json_parse_failed")
            else:
                print(f"NIGHTLY_STYLE_JSON_REPAIR_DONE: date={date}")
        if result is not None:
            candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
            evidence = merge_candidates(evidence, date, candidates)
            write_json(DAILY_DIR / f"{date}.json", {
                "date": date,
                "model": model,
                "status": "observed",
                "source_hash": source_fingerprint(date),
                "signal_count": len(signals),
                "candidate_count": len(candidates),
                "signals": signals,
                "candidates": candidates,
                "notes": result.get("notes") if isinstance(result.get("notes"), list) else [],
                "repaired_json": repaired,
                "updated_at": datetime.now(CST).isoformat(timespec="seconds"),
            })
            print(f"NIGHTLY_STYLE_OBSERVE_DONE: date={date}, signals={len(signals)}, candidates={len(candidates)}")
    else:
        print(f"NIGHTLY_STYLE_OBSERVE_SKIP: no user edits/feedback for {date}")
        write_json(DAILY_DIR / f"{date}.json", {
            "date": date,
            "model": model,
            "source_hash": source_fingerprint(date),
            "signal_count": 0,
            "candidate_count": 0,
            "signals": [],
            "candidates": [],
            "notes": [],
            "updated_at": datetime.now(CST).isoformat(timespec="seconds"),
        })

    write_json(EVIDENCE_PATH, evidence)
    report = build_weekly_report(evidence, date)
    print(f"NIGHTLY_STYLE_WEEKLY_REPORT_READY: {report['week_id']} candidates={len(report['candidates'])}")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1]:
        return run(sys.argv[1])
    scan_days = int(os.environ.get("NIGHTLY_STYLE_SCAN_DAYS", "45"))
    dates = dates_needing_observation(scan_days)
    if not dates:
        dates = [default_date()]
    rc = 0
    for date in dates:
        rc = max(rc, run(date))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
