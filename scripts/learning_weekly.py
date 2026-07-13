"""Shared weekly-learning report and lifecycle helpers.

Weekly files are snapshots of changes, not copies of the entire evidence pool.
Historical evidence is preserved; inactive observations are only moved out of
the active context by changing their status and recording an archive reason.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CST = timezone(timedelta(hours=8))
ACTIVE_REVIEW_STATUSES = {"observed", "pending", "ready_for_review"}
CONFIRMED_STATUSES = {"confirmed", "confirmed_by_feedback"}
ARCHIVED_STATUSES = {"archived_observation", "archived_stale", "rejected"}
STALE_AFTER_DAYS = 28


def parse_day(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def week_id_for(day_text: str) -> str:
    day = datetime.strptime(day_text, "%Y-%m-%d").date()
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_dates_for(day_text: str) -> list[str]:
    day = datetime.strptime(day_text, "%Y-%m-%d").date()
    start = day - timedelta(days=day.weekday())
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


def event_dates(entry: dict[str, Any]) -> set[str]:
    dates = {str(item)[:10] for item in entry.get("days", []) if item}
    for feedback in entry.get("feedback", []):
        if isinstance(feedback, dict) and feedback.get("created_at"):
            dates.add(str(feedback["created_at"])[:10])
    for key in ("created_at", "updated_at", "confirmed_at", "last_seen"):
        if entry.get(key):
            dates.add(str(entry[key])[:10])
    return dates


def compact_rule(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the UI/report projection, without duplicating the full evidence."""
    examples = entry.get("examples") if isinstance(entry.get("examples"), list) else []
    return {
        "id": entry.get("id"),
        "title": entry.get("title") or entry.get("id") or "未命名规则",
        "rule": entry.get("rule") or "",
        "category": entry.get("category") or "style",
        "scope": entry.get("scope") or "all",
        "status": entry.get("status") or "observed",
        "type": entry.get("type") or "style_rule",
        "days_seen": int(entry.get("days_seen", 0) or 0),
        "articles_seen": int(entry.get("articles_seen", 0) or 0),
        "contradictions": int(entry.get("contradictions", 0) or 0),
        "last_seen": entry.get("last_seen") or "",
        "semantic_rationale": entry.get("semantic_rationale") or entry.get("latest_evidence_summary") or "",
        "misuse_risk": entry.get("misuse_risk") or "",
        "examples": examples[-3:],
    }


def apply_lifecycle(evidence: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Archive stale, unconfirmed observations while retaining all evidence."""
    anchor = datetime.strptime(as_of, "%Y-%m-%d").date()
    archived: list[dict[str, Any]] = []
    for entry in evidence.get("rules", {}).values():
        if not isinstance(entry, dict) or entry.get("type") == "dictionary_candidate":
            continue
        status = str(entry.get("status") or "observed")
        last_seen = parse_day(entry.get("last_seen"))
        if status not in ACTIVE_REVIEW_STATUSES or not last_seen:
            continue
        age = (anchor - last_seen).days
        if age <= STALE_AFTER_DAYS:
            continue
        previous = status
        entry["status"] = "archived_stale"
        entry["archived_at"] = datetime.now(CST).isoformat(timespec="seconds")
        entry["archive_reason"] = f"{age} days without new supporting evidence"
        entry["previous_status"] = previous
        archived.append(compact_rule(entry))
    if archived:
        evidence["updated_at"] = datetime.now(CST).isoformat(timespec="seconds")
    return archived


def confirmed_this_week(entry: dict[str, Any], week_dates: set[str]) -> bool:
    for feedback in entry.get("feedback", []):
        if not isinstance(feedback, dict):
            continue
        if str(feedback.get("created_at") or "")[:10] in week_dates and feedback.get("classified_as") == "confirmed":
            return True
    return str(entry.get("confirmed_at") or "")[:10] in week_dates


def build_report(evidence: dict[str, Any], anchor_date: str, archived: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    week_dates = week_dates_for(anchor_date)
    week_set = set(week_dates)
    decisions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    confirmed_changes: list[dict[str, Any]] = []
    dictionary_candidates: list[dict[str, Any]] = []

    for entry in evidence.get("rules", {}).values():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "observed")
        active_this_week = bool(event_dates(entry).intersection(week_set))
        projection = compact_rule(entry)
        if entry.get("type") == "dictionary_candidate":
            if active_this_week and status not in ARCHIVED_STATUSES:
                dictionary_candidates.append(projection)
            continue
        if status == "ready_for_review":
            decisions.append(projection)
        if int(entry.get("contradictions", 0) or 0) > 0 and active_this_week and status not in ARCHIVED_STATUSES:
            conflicts.append(projection)
        if status in {"observed", "pending"} and active_this_week:
            observations.append(projection)
        if status in CONFIRMED_STATUSES and confirmed_this_week(entry, week_set):
            confirmed_changes.append(projection)

    decisions.sort(key=lambda item: (-item["days_seen"], -item["articles_seen"], item["title"]))
    observations.sort(key=lambda item: (item["last_seen"], item["title"]), reverse=True)
    report = {
        "schema_version": 3,
        "week_id": week_id_for(anchor_date),
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "range": {"start": week_dates[0], "end": week_dates[-1]},
        "summary": {
            "ready_for_review": len(decisions),
            "conflicts": len(conflicts),
            "dictionary_candidates": len(dictionary_candidates),
            "observing": len(observations),
            "confirmed_this_week": len(confirmed_changes),
            "archived_this_week": len(archived or []),
        },
        "decisions": decisions[:40],
        "conflicts": conflicts[:20],
        "observations": observations[:20],
        "confirmed_changes": confirmed_changes[:20],
        "dictionary_candidates": dictionary_candidates[:20],
        "archived_changes": (archived or [])[:40],
        # Compatibility for the existing homepage and older clients.
        "candidates": decisions[:40],
        "confirmed_rules": confirmed_changes[:20],
    }
    return report


def build_active_rules(evidence: dict[str, Any]) -> dict[str, Any]:
    rules = [compact_rule(entry) for entry in evidence.get("rules", {}).values()
             if isinstance(entry, dict) and entry.get("status") in CONFIRMED_STATUSES
             and entry.get("type") != "dictionary_candidate"]
    rules.sort(key=lambda item: (item["category"], item["title"]))
    return {"generated_at": datetime.now(CST).isoformat(timespec="seconds"), "count": len(rules), "rules": rules}


def build_observation_pool(evidence: dict[str, Any]) -> dict[str, Any]:
    active = []
    archived = []
    for entry in evidence.get("rules", {}).values():
        if not isinstance(entry, dict) or entry.get("type") == "dictionary_candidate":
            continue
        projection = compact_rule(entry)
        if entry.get("status") in {"observed", "pending"}:
            active.append(projection)
        elif entry.get("status") in ARCHIVED_STATUSES:
            projection["archive_reason"] = entry.get("archive_reason") or ""
            archived.append(projection)
    active.sort(key=lambda item: item["last_seen"], reverse=True)
    archived.sort(key=lambda item: item["last_seen"], reverse=True)
    return {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "active": active,
        "archived": archived,
        "summary": {"active": len(active), "archived": len(archived)},
    }


def report_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "week_id": report.get("week_id"),
        "range": report.get("range", {}),
        "generated_at": report.get("generated_at"),
        "summary": report.get("summary", {}),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

