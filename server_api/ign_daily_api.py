#!/usr/bin/env python3
"""Private API for IGN Daily.

The API keeps secrets on the server. Clients authenticate against this service
and never need a GitHub PAT or translator key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import signal
import sqlite3
import stat
import sys
import subprocess
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from translation_quality import QUALITY_GATE_VERSION, validate_translation_quality

try:
    import fcntl
except ImportError:  # Windows development and unit tests
    fcntl = None


CST = timezone(timedelta(hours=8))
DEFAULT_APP_DIR = Path(os.environ.get("IGN_DAILY_REPO_PATH", "/srv/ign-daily")).resolve()
DEFAULT_API_DIR = Path(os.environ.get("IGN_DAILY_API_DIR", "/srv/ign-daily-api")).resolve()


def load_env_files(paths: list[Path]) -> None:
    """Load deployment settings before deriving any module-level configuration.

    Uvicorn imports this module before FastAPI starts.  Reading the two private
    env files here prevents values such as storage mode and CORS origins from
    being silently ignored until the next process restart.
    """
    for path in paths:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env_files([DEFAULT_APP_DIR / ".env", DEFAULT_API_DIR / ".env"])

APP_DIR = Path(os.environ.get("IGN_DAILY_REPO_PATH", DEFAULT_APP_DIR)).resolve()
API_DIR = Path(os.environ.get("IGN_DAILY_API_DIR", DEFAULT_API_DIR)).resolve()
# A custom repo/API path can itself be declared in the default env files. Read
# the resolved locations once more, without overriding process-level settings.
load_env_files([APP_DIR / ".env", API_DIR / ".env"])
# Production serves this module from /srv/ign-daily-api; shared checkers remain
# in the separately deployed site scripts directory. Tests use the source tree.
_scripts_dir = APP_DIR / "scripts"
if not (_scripts_dir / "check_source_alignment.py").is_file():
    _scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
from check_source_alignment import expected_paragraphs

DB_PATH = Path(os.environ.get("IGN_DAILY_API_DB", API_DIR / "auth.sqlite3")).resolve()
WRITE_LOCK_PATH = Path(os.environ.get("IGN_DAILY_WRITE_LOCK", "/var/lock/ign-daily-write.lock"))
SESSION_COOKIE = "ign_daily_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
PBKDF2_ROUNDS = 210_000
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 8
GITHUB_OWNER = os.environ.get("IGN_DAILY_GITHUB_OWNER", "ZenoTzz")
GITHUB_REPO = os.environ.get("IGN_DAILY_GITHUB_REPO", "ign-daily")
GITHUB_BRANCH = os.environ.get("IGN_DAILY_GITHUB_BRANCH", "main")
STORAGE_MODE = os.environ.get("IGN_DAILY_STORAGE_MODE", "local").strip().lower()
WECHAT_APPID = os.environ.get("IGN_DAILY_WECHAT_APPID", "").strip()
WECHAT_APP_SECRET = os.environ.get("IGN_DAILY_WECHAT_APP_SECRET", "").strip()
WECHAT_BIND_TTL_SECONDS = 10 * 60
WECHAT_JOB_TEMPLATE_ID = os.environ.get("IGN_DAILY_WECHAT_JOB_TEMPLATE_ID", "").strip()
_WECHAT_ACCESS_TOKEN: dict[str, Any] = {"value": "", "expires_at": 0}
MAX_TRANSLATION_JOB_ARTICLES = 2


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class WeChatLoginRequest(BaseModel):
    code: str = Field(min_length=4, max_length=256)


class WeChatBindRequest(BaseModel):
    bind_token: str = Field(min_length=20, max_length=256)
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class WeChatSubscriptionRequest(BaseModel):
    template_id: str = Field(min_length=8, max_length=256)


class DictCandidateRequest(BaseModel):
    category: str = "terms"
    en: str = Field(min_length=1, max_length=240)
    cn: str = Field(min_length=1, max_length=240)
    note: str = Field(default="", max_length=1000)


class DictCandidateReviewRequest(BaseModel):
    cn: str | None = Field(default=None, min_length=1, max_length=240)
    category: str | None = None
    note: str | None = Field(default=None, max_length=1000)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class UpdateAccountRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_username: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    new_password: str | None = Field(default=None, min_length=12, max_length=200)


class TranslationRequest(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    ids: list[int] = Field(min_length=1, max_length=100)
    trigger_workflow: bool | None = None
    expected_urls: dict[str, str] | None = None


class ManualApproveRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    expected_revision: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    article_id: int = Field(ge=1)


class FilteredRestoreRequest(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    url: str = Field(min_length=1, max_length=2000)
    trigger_workflow: bool = False


class PolishWriteRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    expected_revision: str | None = Field(...)
    title: str = Field(max_length=2000)
    subtitle: str = Field(max_length=10000)
    summary: str = Field(max_length=20000)
    body: str = Field(max_length=2000000)


class PolishDeleteRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    expected_revision: str = Field(min_length=1)


class DictTermUpdateRequest(BaseModel):
    original_category: str
    original_en: str
    expected_entry: Any = Field(...)
    category: str
    en: str = Field(min_length=1, max_length=240)
    cn: str = Field(min_length=1, max_length=240)
    note: str | None = None
    source: str | None = Field(default=None, max_length=240)


class DictTermRequest(BaseModel):
    category: str = "terms"
    en: str = Field(min_length=1, max_length=240)
    cn: str = Field(min_length=1, max_length=240)
    source: str = "user"
    note: str = ""


class DictReplaceRequest(BaseModel):
    expected_revision: str = Field(min_length=1)
    dictionary: dict[str, Any]
    message: str = "dict: update via private API"


class WorkflowRequest(BaseModel):
    workflow: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class JobCreate(BaseModel):
    kind: str
    date: str | None = None
    ids: list[int] = Field(default_factory=list)
    message: str = ""


class CodexJobProgressRequest(BaseModel):
    status: str | None = None
    message: str = ""
    progress: int | None = Field(default=None, ge=0, le=100)
    article_id: int | None = Field(default=None, ge=1)
    step: str | None = None
    step_label: str | None = None


class CodexJobCompleteRequest(BaseModel):
    message: str = "Codex batch completed"


class CodexJobFailRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class FileWriteRequest(BaseModel):
    expected_absent: bool = False
    content: str
    message: str = "update via private API"
    sha: str | None = None


class FileDeleteRequest(BaseModel):
    message: str = "delete via private API"
    sha: str | None = None


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    API_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ROUNDS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32), b"\0" * 16)


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT UNIQUE NOT NULL,
              password_hash TEXT NOT NULL,
              created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              date TEXT,
              ids_json TEXT NOT NULL,
              message TEXT NOT NULL DEFAULT '',
              progress INTEGER NOT NULL DEFAULT 0,
              created_by TEXT,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              finished_at INTEGER,
              log_path TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_attempts (
              client_key TEXT PRIMARY KEY,
              failed_count INTEGER NOT NULL,
              last_failed_at INTEGER NOT NULL,
              blocked_until INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS wechat_bindings (
              openid TEXT PRIMARY KEY,
              user_id INTEGER NOT NULL,
              unionid TEXT,
              created_at INTEGER NOT NULL,
              last_login_at INTEGER NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS wechat_bind_challenges (
              token_hash TEXT PRIMARY KEY,
              openid TEXT NOT NULL,
              unionid TEXT,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS wechat_subscriptions (
              openid TEXT NOT NULL,
              template_id TEXT NOT NULL,
              credits INTEGER NOT NULL DEFAULT 0,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(openid, template_id)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS wechat_notification_log (
              event_key TEXT PRIMARY KEY,
              openid TEXT NOT NULL,
              template_id TEXT NOT NULL,
              status TEXT NOT NULL,
              detail TEXT,
              created_at INTEGER NOT NULL
            )"""
        )
        if "urls_json" not in {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}:
            conn.execute("ALTER TABLE jobs ADD COLUMN urls_json TEXT NOT NULL DEFAULT '{}'")
        conn.execute("""CREATE TABLE IF NOT EXISTS local_workers (
            id TEXT PRIMARY KEY, pid INTEGER, identity TEXT, job_ids TEXT NOT NULL,
            started_at INTEGER NOT NULL, log_path TEXT NOT NULL, status TEXT NOT NULL
        )""")
        user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        admin_password = os.environ.get("IGN_DAILY_ADMIN_PASSWORD", "")
        admin_user = os.environ.get("IGN_DAILY_ADMIN_USER", "admin")
        if user_count == 0 and admin_password:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (admin_user, hash_password(admin_password), int(time.time())),
            )
        conn.commit()


def now_cn() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise HTTPException(status_code=404, detail=f"Missing file: {path.relative_to(APP_DIR)}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {path.relative_to(APP_DIR)}: {exc}") from exc


def validate_article_date(date: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
        raise HTTPException(status_code=400, detail="Invalid date")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date") from exc
    return date


def resolve_translation_trigger(requested: bool | None) -> bool:
    """Native clients omit the override; legacy explicit booleans still work."""
    if requested is not None:
        return requested
    config = read_json(APP_DIR / "data" / "automation-config.json", {})
    return isinstance(config, dict) and config.get("fulltext_translator") == "api"


def public_translation_file_status(date: str, article_id: int) -> dict[str, Any]:
    """Report whether Nginx can traverse and read a public translation file."""
    padded = f"{int(article_id):02d}"
    relative = f"data/{date}/translations/{padded}.json"
    target = APP_DIR / relative
    if not target.exists():
        return {"status": "missing", "path": relative}
    data_root = (APP_DIR / "data").resolve()
    try:
        resolved = target.resolve()
        if data_root not in resolved.parents or not resolved.is_file():
            return {"status": "invalid", "path": relative}
        if not (resolved.stat().st_mode & stat.S_IROTH):
            return {"status": "permission_denied", "path": relative}
        current = resolved.parent
        while True:
            if not (current.stat().st_mode & stat.S_IXOTH):
                return {"status": "permission_denied", "path": relative}
            if current == data_root:
                break
            current = current.parent
    except OSError:
        return {"status": "permission_denied", "path": relative}
    return {"status": "available", "path": relative}


def json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def restored_article_from_filtered(item: dict[str, Any], article_id: int) -> dict[str, Any]:
    title = str(item.get("title") or "").strip()
    pub_date = str(item.get("pubDate_cst") or item.get("pub_date") or "").strip()
    return {
        "id": article_id,
        "category": "游戏新闻",
        "emoji": "🎮",
        "en_title": title,
        "cn_title": title,
        "summary": "",
        "url": item.get("url"),
        "publish_time_cn": pub_date,
        "pub_date": pub_date,
        "cover_image": "",
        "translation_status": "none",
    }


def article_urls(date: str | None, ids: list[int]) -> dict[str, str]:
    if not date:
        return {}
    index = read_json(APP_DIR / "data" / date / "index.json", {})
    return {str(a["id"]): a["url"] for a in index.get("articles", [])
            if isinstance(a, dict) and str(a.get("id")) in {str(i) for i in ids} and a.get("url")}


def job_expected_url(row: sqlite3.Row, article_id: int) -> str | None:
    return json.loads(row["urls_json"] or "{}").get(str(article_id))


def create_job(kind: str, date: str | None, ids: list[int], user: str, message: str = "") -> str:
    job_id = f"{kind}-{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, kind, status, date, ids_json, message, progress, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, kind, "queued", date, json.dumps(ids), message, 5, user, now, now),
        )
        conn.execute("UPDATE jobs SET urls_json = ? WHERE id = ?", (json.dumps(article_urls(date, ids)), job_id))
        conn.commit()
    return job_id


def create_or_reuse_translation_jobs(
    date: str,
    ids: list[int],
    user: str,
    message: str = "",
) -> tuple[list[str], list[str], list[str]]:
    """Atomically reuse active article jobs and create jobs only for uncovered IDs."""
    selected_ids = list(dict.fromkeys(int(article_id) for article_id in ids))
    selected_urls = article_urls(date, selected_ids)
    now = int(time.time())
    reused_job_ids: list[str] = []
    created_job_ids: list[str] = []
    covered_ids: set[int] = set()

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT id, ids_json, urls_json
            FROM jobs
            WHERE kind = 'translation' AND date = ? AND status IN ('queued', 'running')
            ORDER BY created_at, id
            """,
            (date,),
        ).fetchall()
        selected_set = set(selected_ids)
        for row in rows:
            try:
                active_ids = {int(value) for value in json.loads(row["ids_json"])}
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            saved_urls = json.loads(row["urls_json"] or "{}")
            overlap = {aid for aid in active_ids & selected_set
                       if not saved_urls.get(str(aid)) or saved_urls[str(aid)] == selected_urls.get(str(aid))}
            if not overlap:
                continue
            reused_job_ids.append(row["id"])
            covered_ids.update(overlap)

        uncovered_ids = [article_id for article_id in selected_ids if article_id not in covered_ids]
        for offset in range(0, len(uncovered_ids), MAX_TRANSLATION_JOB_ARTICLES):
            batch_ids = uncovered_ids[offset : offset + MAX_TRANSLATION_JOB_ARTICLES]
            job_id = f"translation-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO jobs (id, kind, status, date, ids_json, message, progress, created_by, created_at, updated_at)
                VALUES (?, 'translation', 'queued', ?, ?, ?, 5, ?, ?, ?)
                """,
                (job_id, date, json.dumps(batch_ids), message, user, now, now),
            )
            conn.execute("UPDATE jobs SET urls_json = ? WHERE id = ?", (json.dumps({str(i): selected_urls[str(i)] for i in batch_ids if str(i) in selected_urls}), job_id))
            created_job_ids.append(job_id)
        conn.commit()

    return created_job_ids + reused_job_ids, created_job_ids, reused_job_ids


def update_job(job_id: str, status: str, message: str | None = None, progress: int | None = None) -> None:
    fields = ["status = ?", "updated_at = ?"]
    values: list[Any] = [status, int(time.time())]
    if message is not None:
        fields.append("message = ?")
        values.append(message)
    if progress is not None:
        fields.append("progress = ?")
        values.append(max(0, min(100, int(progress))))
    if status in {"done", "failed"}:
        fields.append("finished_at = ?")
        values.append(int(time.time()))
    values.append(job_id)
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()


def read_job_progress_data(job_id: str) -> dict[str, Any]:
    path = APP_DIR / "data" / "job-progress" / f"{job_id}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_job_progress(job_id: str) -> dict[str, Any]:
    data = read_job_progress_data(job_id)
    return data.get("articles", {}) if isinstance(data, dict) else {}


def clamp_progress(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(100, int(value)))
    except Exception:
        return default


STAGE_REMAINING_SECONDS: dict[str, tuple[int, int]] = {
    "source": (10 * 60, 25 * 60),
    "extract": (8 * 60, 22 * 60),
    "model": (8 * 60, 20 * 60),
    "parse": (4 * 60, 10 * 60),
    "audit": (3 * 60, 8 * 60),
    "repair": (8 * 60, 25 * 60),
    "write": (60, 3 * 60),
}
DEFAULT_ARTICLE_SECONDS = (8 * 60, 20 * 60)


def stable_translation_estimate(status: str, step: str | None, remaining_articles: int = 1) -> dict[str, Any]:
    """Return a broad estimate that only changes with workflow stage."""
    if status in {"done", "failed"}:
        return {"estimate_kind": "complete", "eta_min_seconds": 0, "eta_max_seconds": 0, "eta_seconds": 0}
    if status == "queued" or step == "queued":
        return {"estimate_kind": "scheduled", "eta_min_seconds": None, "eta_max_seconds": None, "eta_seconds": None}
    count = max(1, int(remaining_articles or 1))
    current_min, current_max = STAGE_REMAINING_SECONDS.get(str(step or ""), DEFAULT_ARTICLE_SECONDS)
    future_count = max(0, count - 1)
    minimum = current_min + future_count * DEFAULT_ARTICLE_SECONDS[0]
    maximum = current_max + future_count * DEFAULT_ARTICLE_SECONDS[1]
    return {
        "estimate_kind": "uncertain" if step == "repair" else "range",
        "eta_min_seconds": minimum,
        "eta_max_seconds": maximum,
        "eta_seconds": int((minimum + maximum) / 2),
    }


def translation_completion_errors(date: str, article_id: int, *, require_index: bool = True, document: dict[str, Any] | None = None, expected_url: str | None = None) -> list[str]:
    day = APP_DIR / "data" / date
    try:
        document = document if document is not None else read_json(day / "translations" / f"{article_id:02d}.json", {})
        index = read_json(day / "index.json", {})
    except HTTPException:
        return ["Translation or index JSON is invalid"]
    if not isinstance(index, dict):
        return ["Article index is invalid"]
    articles = index.get("articles", [])
    if not isinstance(articles, list):
        return ["Article index articles must be a list"]
    item = next((a for a in articles if isinstance(a, dict) and str(a.get("id")) == str(article_id)), {})
    if not isinstance(document, dict) or not document:
        return ["Translation file is missing or invalid"]
    errors = validate_translation_quality(document)
    if expected_url is not None and item.get("url") != expected_url:
        errors.append("Article identity changed since job submission")
    if not item.get("url") or document.get("url") != item.get("url"):
        errors.append("Translation URL does not match article")
    if not document.get("paragraphs"):
        errors.append("Translation paragraphs are empty")
    if require_index and (item.get("translation_status") != "done" or
                          item.get("translation_path") != f"translations/{article_id:02d}.json"):
        errors.append("Article index is not published")
    try:
        source = read_json(day / "sources" / f"{article_id:02d}.json", {})
    except HTTPException:
        return errors + ["Source JSON is invalid"]
    if not isinstance(source, dict) or not source.get("paragraphs_en") or source.get("url") != item.get("url"):
        errors.append("Matching source cache is missing")
    else:
        expected = expected_paragraphs(source)
        paragraphs = document.get("paragraphs", [])
        if not expected or not isinstance(paragraphs, list) or [x.get("en") if isinstance(x, dict) else None for x in paragraphs] != expected:
            errors.append("Translation does not align with source paragraphs")
        elif any(not str(x.get("cn") or "").strip() for x in paragraphs):
            errors.append("Chinese paragraphs are missing")
    return errors


def infer_translation_job(row: sqlite3.Row) -> dict[str, Any]:
    ids = json.loads(row["ids_json"] or "[]")
    date = row["date"]
    status = row["status"]
    message = row["message"]
    progress = int(row["progress"] or 0)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    done = 0
    failed = 0
    progress_sum = 0
    current_item: dict[str, Any] | None = None
    if date and ids:
        failures = read_json(APP_DIR / "data" / date / "translation_failures.json", {"items": {}})
        failure_items = failures.get("items", {}) if isinstance(failures, dict) else {}
        progress_data = read_job_progress_data(row["id"])
        progress_items = progress_data.get("articles", {}) if isinstance(progress_data, dict) else {}
        for article_id in ids:
            progress_item = progress_items.get(str(int(article_id))) or {}
            padded = f"{int(article_id):02d}"
            translation_path = APP_DIR / "data" / date / "translations" / f"{padded}.json"
            failure = failure_items.get(str(article_id))
            if failure:
                failed += 1
                progress_sum += 100
                errors.append({
                    "id": int(article_id),
                    "status": "failed",
                    "step": progress_item.get("step", "failed"),
                    "step_label": progress_item.get("step_label", "质检未通过"),
                    "progress": 100,
                    "reason": failure.get("reason", progress_item.get("message", "Translation needs review")),
                    "message": progress_item.get("message", "质检未通过，需复核"),
                    "draft": translation_path.exists(),
                    "updated_at": progress_item.get("updated_at"),
                    "started_at": progress_item.get("started_at"),
                    "eta_seconds": 0,
                })
                continue
            if translation_path.exists() and not translation_completion_errors(date, int(article_id), expected_url=job_expected_url(row, int(article_id))):
                done += 1
                progress_sum += 100
                results.append({
                    "id": int(article_id),
                    "status": "done",
                    "step": progress_item.get("step", "done"),
                    "step_label": progress_item.get("step_label", "已写入译文"),
                    "progress": 100,
                    "message": progress_item.get("message", "翻译完成"),
                    "updated_at": progress_item.get("updated_at"),
                    "started_at": progress_item.get("started_at"),
                    "eta_seconds": 0,
                })
                continue
            item_progress = clamp_progress(progress_item.get("progress"), 5 if status == "queued" else progress or 10)
            result_item = {
                "id": int(article_id),
                "status": "failed" if status in {"done", "failed"} else ("queued" if status == "queued" else "running"),
                "step": progress_item.get("step", "queued" if status == "queued" else "model"),
                "step_label": progress_item.get("step_label", "排队等待" if status == "queued" else "模型翻译/质检中"),
                "progress": item_progress,
                "message": progress_item.get("message", message or "正在翻译"),
                "updated_at": progress_item.get("updated_at"),
                "started_at": progress_item.get("started_at"),
            }
            result_item.update(stable_translation_estimate(result_item["status"], result_item["step"], 1))
            progress_sum += item_progress
            if result_item["status"] not in {"done", "failed"}:
                if current_item is None or int(result_item.get("updated_at") or 0) >= int(current_item.get("updated_at") or 0):
                    current_item = result_item
            results.append({
                **result_item,
            })
    total = len(ids)
    if total:
        article_progress = int(progress_sum / total) if progress_sum else 0
        progress = max(progress, min(95, article_progress))
        if done + failed == total:
            status = "failed" if failed else "done"
            progress = 100
            message = "翻译失败" if status == "failed" else "翻译完成"
        elif row["status"] == "done":
            status = "failed"
            message = "译文文件或发布状态不完整，需要复核"
            progress = 100
        elif row["status"] in {"queued", "running"}:
            # Reading a job must not claim it.  A queued job only becomes
            # running through the explicit Codex claim/progress endpoints.
            status = row["status"]
            if current_item:
                current_label = current_item.get("step_label") or current_item.get("message") or "正在翻译"
                message = f"#{current_item.get('id')} {current_label}"
            else:
                message = message or "正在翻译"
    remaining_articles = max(0, total - done - failed)
    estimate = stable_translation_estimate(
        status,
        current_item.get("step") if current_item else ("queued" if status == "queued" else None),
        remaining_articles,
    )
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": status,
        "date": date,
        "ids": ids,
        "message": message,
        "progress": progress,
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
        "total_count": total,
        "done_count": done,
        "failed_count": failed,
        "current_article_id": current_item.get("id") if current_item else None,
        "current_step": current_item.get("step") if current_item else None,
        "current_step_label": current_item.get("step_label") if current_item else None,
        **estimate,
        "results": results,
        "errors": errors,
    }


def serialize_job(row: sqlite3.Row) -> dict[str, Any]:
    if row["kind"] == "translation":
        return infer_translation_job(row)
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "date": row["date"],
        "ids": json.loads(row["ids_json"] or "[]"),
        "message": row["message"],
        "progress": int(row["progress"] or 0),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


def load_job_row(job_id: str) -> sqlite3.Row:
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return row


def write_job_progress_item(
    job_id: str,
    *,
    date: str | None,
    article_id: int,
    status: str,
    step: str,
    step_label: str,
    progress: int,
    message: str,
) -> None:
    path = APP_DIR / "data" / "job-progress" / f"{job_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    now = int(time.time())
    data.setdefault("job_id", job_id)
    articles = data.setdefault("articles", {})
    item = articles.setdefault(str(int(article_id)), {})
    item.setdefault("started_at", now)
    clamped = max(0, min(100, int(progress)))
    item.update(
        {
            "id": int(article_id),
            "date": date,
            "status": status,
            "step": step,
            "step_label": step_label,
            "progress": clamped,
            "message": message or step_label,
            "updated_at": now,
        }
    )
    if status in {"done", "failed"} or clamped >= 100:
        item["finished_at"] = now
        item["eta_seconds"] = 0
    data["updated_at"] = now
    write_local_file(path, json_text(data))


def article_payload_for_job(date: str, ids: list[int]) -> list[dict[str, Any]]:
    index = read_json(APP_DIR / "data" / date / "index.json", {"articles": []})
    by_id = {
        int(item.get("id")): item
        for item in index.get("articles", [])
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }
    items: list[dict[str, Any]] = []
    for article_id in ids:
        item = by_id.get(int(article_id))
        if not item:
            continue
        source_path = APP_DIR / "data" / date / "sources" / f"{int(article_id):02d}.json"
        source = read_json(source_path, {}) if source_path.exists() else {}
        items.append(
            {
                "id": int(article_id),
                "date": date,
                "article": item,
                "source": source,
                "translation_path": f"data/{date}/translations/{int(article_id):02d}.json",
            }
        )
    return items


def safe_repo_path(path: str) -> Path:
    """Resolve a user-facing project path limited to editable runtime JSON.

    Browser and mini-program tokens must never be able to read deployment
    secrets or overwrite executable files.  The UI only needs JSON under
    ``data/``; keeping that boundary explicit also blocks encoded traversal.
    """
    normalized = str(path or "").replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or not relative.parts
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.parts[0] != "data"
        or relative.suffix.lower() != ".json"
        or any(part.startswith(".") for part in relative.parts)
    ):
        raise HTTPException(status_code=400, detail="Only data JSON files may be accessed")
    data_root = (APP_DIR / "data").resolve()
    target = (APP_DIR / Path(*relative.parts)).resolve()
    if data_root not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid repository path")
    return target


def content_sha(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def validate_json_content(content: str) -> None:
    try:
        json.loads(content.lstrip("\ufeff"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON content: {exc}") from exc


@contextmanager
def _runtime_file_lock(timeout_seconds: float = 30.0) -> Iterator[None]:
    """Serialize API file writes with cron jobs and deployments on Linux."""
    if fcntl is None:
        yield
        return
    try:
        WRITE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = WRITE_LOCK_PATH.open("a+", encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Runtime write lock is unavailable") from exc
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HTTPException(status_code=503, detail="Another server write is still running")
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


_RUNTIME_THREAD_LOCK = threading.RLock()
_RUNTIME_LOCK_STATE = threading.local()


@contextmanager
def runtime_write_lock(timeout_seconds: float = 30.0) -> Iterator[None]:
    """Lock a complete read/modify/write operation; nested writes reuse its flock."""
    if not _RUNTIME_THREAD_LOCK.acquire(timeout=timeout_seconds):
        raise HTTPException(status_code=503, detail="Another server write is still running")
    try:
        if getattr(_RUNTIME_LOCK_STATE, "held", False):
            yield
        else:
            with _runtime_file_lock(timeout_seconds):
                _RUNTIME_LOCK_STATE.held = True
                try:
                    yield
                finally:
                    _RUNTIME_LOCK_STATE.held = False
    finally:
        _RUNTIME_THREAD_LOCK.release()


def write_local_file(target: Path, content: str, expected_sha: str | None = None) -> None:
    """Atomically replace a runtime JSON file and optionally enforce its revision."""
    if expected_sha is not None:
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=409, detail="File changed before it could be saved")
        current = target.read_text(encoding="utf-8-sig")
        if not hmac.compare_digest(content_sha(current), expected_sha):
            raise HTTPException(status_code=409, detail="File changed before it could be saved")
    target.parent.mkdir(parents=True, exist_ok=True)
    data_root = (APP_DIR / "data").resolve()
    resolved_parent = target.parent.resolve()
    if resolved_parent == data_root or data_root in resolved_parent.parents:
        current = resolved_parent
        while True:
            os.chmod(current, 0o755)
            if current == data_root:
                break
            current = current.parent
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        os.chmod(target, 0o644)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def write_project_file(path: str, content: str, message: str = "", expected_sha: str | None = None) -> Any:
    target = safe_repo_path(path)
    validate_json_content(content)
    if STORAGE_MODE == "github":
        return gh_put_file(path, content, message)
    with runtime_write_lock():
        write_local_file(target, content, expected_sha)
    return {"ok": True, "path": path, "mode": "local", "message": message}


def worker_identity(pid: int) -> str | None:
    """Linux boot and process start time prevent signaling a reused PID."""
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else f"{boot}:{fields[19]}"
    except (OSError, IndexError):
        return None


def finish_local_worker(worker_id: str, job_ids: list[str], reason: str) -> None:
    for job_id in job_ids:
        complete = False
        try:
            row = load_job_row(job_id)
            ids = json.loads(row["ids_json"] or "[]")
            with runtime_write_lock():
                complete = bool(ids) and all(not translation_completion_errors(row["date"], int(aid), expected_url=job_expected_url(row, int(aid))) for aid in ids)
        except (HTTPException, OSError, ValueError, TypeError, KeyError, AttributeError):
            # Invalid runtime JSON must terminate the task, not the supervisor.
            complete = False
        update_job(job_id, "done" if complete else "failed", "翻译完成" if complete else reason, 100)
    with db() as conn:
        conn.execute("UPDATE local_workers SET status = 'finished' WHERE id = ?", (worker_id,))
        conn.commit()


def supervise_local_worker(worker_id: str, process: Any = None) -> None:
    with db() as conn:
        worker = conn.execute("SELECT * FROM local_workers WHERE id = ?", (worker_id,)).fetchone()
    job_ids = json.loads(worker["job_ids"])
    timeout = int(os.environ.get("IGN_DAILY_JOB_TIMEOUT_SECONDS", "3600"))
    reason = "后台进程已结束但译文未完成，请查看服务器任务日志后重试"
    while True:
        if process is not None:
            alive = process.poll() is None
        else:
            alive = bool(worker["identity"]) and worker_identity(worker["pid"]) == worker["identity"]
        if not alive:
            if process is not None:
                if process.returncode == 75:
                    reason = "其他后台任务正在运行，请稍后重新提交"
                elif process.returncode == 78:
                    reason = "翻译密钥尚未配置，请配置后重新提交"
                elif process.returncode:
                    reason = "后台翻译执行失败，请查看服务器任务日志后重试"
                try:
                    with Path(worker["log_path"]).open("a", encoding="utf-8") as output:
                        output.write(f"\nWORKER_EXIT_CODE={process.returncode}\n")
                except OSError:
                    pass  # A full log disk must not leave the persisted job running.
            break
        if time.time() - worker["started_at"] >= timeout:
            # An unrecoverable platform identity is never used to signal an unrelated PID.
            if process is not None or (worker["identity"] and worker_identity(worker["pid"]) == worker["identity"]):
                try:
                    os.killpg(worker["pid"], signal.SIGTERM)
                    if process is not None:
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(worker["pid"], signal.SIGKILL)
                            process.wait()
                    else:
                        deadline = time.monotonic() + 10
                        while worker_identity(worker["pid"]) == worker["identity"] and time.monotonic() < deadline:
                            time.sleep(0.1)
                        if worker_identity(worker["pid"]) == worker["identity"]:
                            os.killpg(worker["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            reason = "后台翻译超时，请查看服务器任务日志后重试"
            break
        time.sleep(1)
    finish_local_worker(worker_id, job_ids, reason)


def recover_local_workers() -> None:
    with db() as conn:
        rows = conn.execute("SELECT id FROM local_workers WHERE status = 'running'").fetchall()
    for row in rows:
        threading.Thread(target=supervise_local_worker, args=(row["id"],), daemon=True).start()


def run_local_job(command: list[str], job_id: str | None = None, job_ids: list[str] | None = None) -> None:
    env = os.environ.copy()
    ids = job_ids or ([job_id] if job_id else [])
    if job_id:
        env["IGN_DAILY_JOB_ID"] = job_id
    worker_id = uuid.uuid4().hex
    log_dir = API_DIR / "job-logs"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = log_dir / f"{worker_id}.log"
    descriptor = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    process = None
    try:
        with os.fdopen(descriptor, "wb") as output:
            process = subprocess.Popen(command, cwd=APP_DIR, env=env, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        with db() as conn:
            conn.execute("INSERT INTO local_workers VALUES (?, ?, ?, ?, ?, ?, 'running')",
                         (worker_id, process.pid, worker_identity(process.pid), json.dumps(ids), int(time.time()), str(log_path)))
            for jid in ids:
                conn.execute("UPDATE jobs SET log_path = ? WHERE id = ?", (str(log_path), jid))
            conn.commit()
    except Exception:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        for jid in ids:
            update_job(jid, "failed", "后台进程无法启动，请检查服务器配置后重试", 100)
        raise HTTPException(status_code=503, detail="Background worker could not start")
    threading.Thread(target=supervise_local_worker, args=(worker_id, process), daemon=True).start()


def gh_token() -> str:
    token = (
        os.environ.get("GITHUB_PAT_IGN_DAILY")
        or os.environ.get("GITHUB_TOKEN_IGN_DAILY")
        or os.environ.get("GITHUB_TOKEN")
        or ""
    ).strip()
    if not token:
        raise HTTPException(status_code=503, detail="Server GitHub token is not configured")
    return token


def gh_request(method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {gh_token()}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ign-daily-private-api",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise HTTPException(status_code=502, detail=f"GitHub {method} failed: {exc.code} {detail}") from exc


def gh_contents_url(path: str) -> str:
    quoted = urllib.request.pathname2url(path)
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{quoted}"


def gh_get_file(path: str) -> dict[str, Any] | None:
    url = f"{gh_contents_url(path)}?ref={GITHUB_BRANCH}&t={int(time.time())}"
    try:
        return gh_request("GET", url)
    except HTTPException as exc:
        if "GitHub GET failed: 404" in str(exc.detail):
            return None
        raise


def gh_put_file(path: str, content: str, message: str) -> Any:
    existing = gh_get_file(path)
    payload: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if existing and existing.get("sha"):
        payload["sha"] = existing["sha"]
    return gh_request("PUT", gh_contents_url(path), payload)


def gh_delete_file(path: str, message: str) -> Any:
    existing = gh_get_file(path)
    if not existing or not existing.get("sha"):
        raise HTTPException(status_code=404, detail="File not found")
    payload = {
        "message": message,
        "sha": existing["sha"],
        "branch": GITHUB_BRANCH,
    }
    return gh_request("DELETE", gh_contents_url(path), payload)


def gh_dispatch_workflow(workflow: str, inputs: dict[str, Any] | None = None) -> Any:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow}/dispatches"
    return gh_request("POST", url, {"ref": GITHUB_BRANCH, "inputs": inputs or {}})


def sync_from_github() -> None:
    if STORAGE_MODE != "github":
        return
    if not (APP_DIR / ".git").exists():
        return
    subprocess.run(
        ["/srv/ign-daily-ops/git-sync.sh"],
        cwd=APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )


def auth_from_token(token: str) -> sqlite3.Row:
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
        row = conn.execute(
            """
            SELECT users.id, users.username
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at >= ?
            """,
            (token, int(time.time())),
        ).fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return row


def issue_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now + SESSION_TTL_SECONDS),
        )
        conn.commit()
    return token


def exchange_wechat_code(code: str) -> dict[str, str]:
    if not WECHAT_APPID or not WECHAT_APP_SECRET:
        raise HTTPException(status_code=503, detail="WeChat login is not configured")
    query = urllib.parse.urlencode({
        "appid": WECHAT_APPID,
        "secret": WECHAT_APP_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    })
    try:
        with urllib.request.urlopen(f"https://api.weixin.qq.com/sns/jscode2session?{query}", timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise HTTPException(status_code=502, detail="WeChat login service is unavailable") from exc
    openid = str(payload.get("openid") or "").strip()
    if not openid:
        raise HTTPException(status_code=401, detail="WeChat login code is invalid or expired")
    return {"openid": openid, "unionid": str(payload.get("unionid") or "").strip()}


def wechat_access_token() -> str:
    now = int(time.time())
    if _WECHAT_ACCESS_TOKEN["value"] and int(_WECHAT_ACCESS_TOKEN["expires_at"]) > now + 60:
        return str(_WECHAT_ACCESS_TOKEN["value"])
    if not WECHAT_APPID or not WECHAT_APP_SECRET:
        raise RuntimeError("WeChat login is not configured")
    query = urllib.parse.urlencode({"grant_type": "client_credential", "appid": WECHAT_APPID, "secret": WECHAT_APP_SECRET})
    with urllib.request.urlopen(f"https://api.weixin.qq.com/cgi-bin/token?{query}", timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError(str(payload.get("errmsg") or "WeChat access token failed"))
    _WECHAT_ACCESS_TOKEN.update(value=token, expires_at=now + int(payload.get("expires_in") or 7200))
    return token


def format_wechat_time(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        timestamp = int(time.time())
    return datetime.fromtimestamp(timestamp, CST).strftime("%Y年%m月%d日 %H:%M")


def wechat_job_message_data(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    done_count = int(job.get("done_count") or len(job.get("ids") or []))
    failed_count = int(job.get("failed_count") or 0)
    return {
        "time1": {"value": format_wechat_time(job.get("created_at"))},
        "time2": {"value": format_wechat_time(job.get("finished_at") or job.get("updated_at"))},
        "thing3": {"value": "IGN Daily 翻译任务"},
        "thing12": {"value": f"完成 {done_count} 篇，待复核 {failed_count} 篇"},
        "thing11": {"value": "请进入任务页查看译文"},
    }


def send_job_completion_notification(job: dict[str, Any]) -> bool:
    if not WECHAT_JOB_TEMPLATE_ID:
        return False
    event_key = f"job-complete:{job.get('id')}"
    with db() as conn:
        if conn.execute("SELECT 1 FROM wechat_notification_log WHERE event_key = ?", (event_key,)).fetchone():
            return False
        row = conn.execute(
            """SELECT s.openid FROM wechat_subscriptions s
               WHERE s.template_id = ? AND s.credits > 0 ORDER BY s.updated_at DESC LIMIT 1""",
            (WECHAT_JOB_TEMPLATE_ID,),
        ).fetchone()
    if not row:
        return False
    openid = row["openid"]
    data = wechat_job_message_data(job)
    payload = json.dumps({
        "touser": openid,
        "template_id": WECHAT_JOB_TEMPLATE_ID,
        "page": "pages/jobs/jobs",
        "miniprogram_state": os.environ.get("IGN_DAILY_WECHAT_STATE", "formal"),
        "lang": "zh_CN",
        "data": data,
    }, ensure_ascii=False).encode("utf-8")
    status, detail = "failed", ""
    try:
        request = urllib.request.Request(
            f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={wechat_access_token()}",
            data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            result = json.loads(response.read().decode("utf-8"))
        detail = json.dumps(result, ensure_ascii=False)
        status = "sent" if int(result.get("errcode") or 0) == 0 else "failed"
    except Exception as exc:
        detail = str(exc)[:500]
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO wechat_notification_log (event_key, openid, template_id, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_key, openid, WECHAT_JOB_TEMPLATE_ID, status, detail, int(time.time())),
        )
        if status == "sent":
            conn.execute("UPDATE wechat_subscriptions SET credits = MAX(0, credits - 1), updated_at = ? WHERE openid = ? AND template_id = ?", (int(time.time()), openid, WECHAT_JOB_TEMPLATE_ID))
        conn.commit()
    return status == "sent"


def login_client_key(request: Request) -> str:
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "unknown").strip()
    return host[:200]


def enforce_login_rate_limit(client_key: str) -> None:
    now = int(time.time())
    with db() as conn:
        conn.execute(
            "DELETE FROM login_attempts WHERE last_failed_at < ?",
            (now - LOGIN_WINDOW_SECONDS * 4,),
        )
        row = conn.execute(
            "SELECT blocked_until FROM login_attempts WHERE client_key = ?",
            (client_key,),
        ).fetchone()
        conn.commit()
    if row and int(row["blocked_until"] or 0) > now:
        retry_after = int(row["blocked_until"]) - now
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {retry_after} seconds.",
        )


def record_login_failure(client_key: str) -> None:
    now = int(time.time())
    with db() as conn:
        row = conn.execute(
            "SELECT failed_count, last_failed_at FROM login_attempts WHERE client_key = ?",
            (client_key,),
        ).fetchone()
        if not row or int(row["last_failed_at"] or 0) < now - LOGIN_WINDOW_SECONDS:
            failed_count = 1
        else:
            failed_count = int(row["failed_count"] or 0) + 1
        blocked_until = now + LOGIN_WINDOW_SECONDS if failed_count >= LOGIN_MAX_FAILURES else 0
        conn.execute(
            """
            INSERT INTO login_attempts (client_key, failed_count, last_failed_at, blocked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(client_key) DO UPDATE SET
              failed_count = excluded.failed_count,
              last_failed_at = excluded.last_failed_at,
              blocked_until = excluded.blocked_until
            """,
            (client_key, failed_count, now, blocked_until),
        )
        conn.commit()


def clear_login_failures(client_key: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM login_attempts WHERE client_key = ?", (client_key,))
        conn.commit()


def current_user(
    ign_daily_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None),
) -> sqlite3.Row:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif ign_daily_session:
        token = ign_daily_session
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return auth_from_token(token)


app = FastAPI(
    title="IGN Daily Private API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
allow_origins = [x.strip() for x in os.environ.get("IGN_DAILY_CORS_ORIGINS", "").split(",") if x.strip()]
if allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def startup() -> None:
    init_db()
    recover_local_workers()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time_cn": now_cn(), "app_dir": str(APP_DIR), "storage_mode": STORAGE_MODE}


@app.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    client_key = login_client_key(request)
    enforce_login_rate_limit(client_key)
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (payload.username,)).fetchone()
    password_hash = row["password_hash"] if row else DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, password_hash)
    if not row or not password_valid:
        record_login_failure(client_key)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    with db() as conn:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, row["id"], now, now + SESSION_TTL_SECONDS),
        )
        conn.commit()
    clear_login_failures(client_key)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("IGN_DAILY_COOKIE_SECURE", "0") == "1",
    )
    return {"ok": True, "token": token, "user": {"username": payload.username}}


@app.post("/auth/browser/login")
def browser_login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    """Create the same session without exposing its bearer token to JavaScript."""
    result = login(payload, request, response)
    return {"ok": True, "user": result["user"]}


@app.post("/auth/wechat/login")
def wechat_login(payload: WeChatLoginRequest) -> dict[str, Any]:
    identity = exchange_wechat_code(payload.code)
    now = int(time.time())
    with db() as conn:
        conn.execute("DELETE FROM wechat_bind_challenges WHERE expires_at < ?", (now,))
        binding = conn.execute(
            """SELECT users.id, users.username FROM wechat_bindings
               JOIN users ON users.id = wechat_bindings.user_id
               WHERE wechat_bindings.openid = ?""",
            (identity["openid"],),
        ).fetchone()
        if binding:
            conn.execute("UPDATE wechat_bindings SET last_login_at = ? WHERE openid = ?", (now, identity["openid"]))
            conn.commit()
            return {"ok": True, "bound": True, "token": issue_session(binding["id"]), "user": {"username": binding["username"]}}
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO wechat_bind_challenges (token_hash, openid, unionid, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash, identity["openid"], identity["unionid"] or None, now, now + WECHAT_BIND_TTL_SECONDS),
        )
        conn.commit()
    return {"ok": True, "bound": False, "needs_binding": True, "bind_token": raw_token, "expires_in": WECHAT_BIND_TTL_SECONDS}


@app.post("/auth/wechat/bind")
def wechat_bind(payload: WeChatBindRequest, request: Request) -> dict[str, Any]:
    client_key = login_client_key(request)
    enforce_login_rate_limit(client_key)
    token_hash = hashlib.sha256(payload.bind_token.encode("utf-8")).hexdigest()
    now = int(time.time())
    with db() as conn:
        challenge = conn.execute(
            "SELECT openid, unionid FROM wechat_bind_challenges WHERE token_hash = ? AND expires_at >= ?",
            (token_hash, now),
        ).fetchone()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (payload.username,)).fetchone()
        if not challenge or not user or not verify_password(payload.password, user["password_hash"]):
            verify_password(payload.password, DUMMY_PASSWORD_HASH)
            record_login_failure(client_key)
            raise HTTPException(status_code=401, detail="Binding token or administrator credentials are invalid")
        conn.execute(
            """INSERT INTO wechat_bindings (openid, user_id, unionid, created_at, last_login_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(openid) DO UPDATE SET user_id=excluded.user_id, unionid=excluded.unionid, last_login_at=excluded.last_login_at""",
            (challenge["openid"], user["id"], challenge["unionid"], now, now),
        )
        conn.execute("DELETE FROM wechat_bind_challenges WHERE token_hash = ?", (token_hash,))
        conn.commit()
    clear_login_failures(client_key)
    return {"ok": True, "bound": True, "token": issue_session(user["id"]), "user": {"username": user["username"]}}


@app.get("/wechat/config")
def wechat_config(user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    return {"ok": True, "job_template_id": WECHAT_JOB_TEMPLATE_ID, "enabled": bool(WECHAT_JOB_TEMPLATE_ID and WECHAT_APPID and WECHAT_APP_SECRET)}


@app.post("/wechat/subscriptions")
def register_wechat_subscription(payload: WeChatSubscriptionRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    if not WECHAT_JOB_TEMPLATE_ID or payload.template_id != WECHAT_JOB_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="Subscription template is not configured")
    with db() as conn:
        binding = conn.execute("SELECT openid FROM wechat_bindings WHERE user_id = ? ORDER BY last_login_at DESC LIMIT 1", (user["id"],)).fetchone()
        if not binding:
            raise HTTPException(status_code=409, detail="Bind a WeChat administrator before subscribing")
        conn.execute(
            """INSERT INTO wechat_subscriptions (openid, template_id, credits, updated_at) VALUES (?, ?, 1, ?)
               ON CONFLICT(openid, template_id) DO UPDATE SET credits=credits+1, updated_at=excluded.updated_at""",
            (binding["openid"], payload.template_id, int(time.time())),
        )
        credits = conn.execute("SELECT credits FROM wechat_subscriptions WHERE openid=? AND template_id=?", (binding["openid"], payload.template_id)).fetchone()["credits"]
        conn.commit()
    return {"ok": True, "credits": credits}


@app.post("/auth/logout")
def logout(
    response: Response,
    user: sqlite3.Row = Depends(current_user),
    ign_daily_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    token = authorization.split(" ", 1)[1].strip() if authorization and authorization.lower().startswith("bearer ") else ign_daily_session
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True, "user": {"username": user["username"]}}


@app.get("/auth/me")
def me(user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with db() as conn:
        wechat_bound = conn.execute("SELECT 1 FROM wechat_bindings WHERE user_id = ? LIMIT 1", (user["id"],)).fetchone() is not None
    return {"ok": True, "user": {"username": user["username"], "wechat_bound": wechat_bound}}


@app.post("/auth/change-password")
def change_password(payload: ChangePasswordRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not verify_password(payload.current_password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(payload.new_password), user["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token NOT IN (SELECT token FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1)", (user["id"], user["id"]))
        conn.commit()
    return {"ok": True}


@app.post("/auth/account")
def update_account(payload: UpdateAccountRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    new_username = (payload.new_username or user["username"]).strip()
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not row or not verify_password(payload.current_password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (new_username, user["id"]),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Username already exists")
        password_hash = hash_password(payload.new_password) if payload.new_password else row["password_hash"]
        conn.execute(
            "UPDATE users SET username = ?, password_hash = ? WHERE id = ?",
            (new_username, password_hash, user["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        conn.commit()
    return {"ok": True, "user": {"username": new_username}}


@app.get("/articles")
def articles(date: str, user: sqlite3.Row = Depends(current_user)) -> Any:
    validate_article_date(date)
    data = read_json(APP_DIR / "data" / date / "index.json")
    req = read_json(APP_DIR / "data" / date / "requests.json", {"requested_ids": [], "requested_articles": []})
    failures = read_json(APP_DIR / "data" / date / "translation_failures.json", {"items": {}})
    requested_ids = {int(x) for x in req.get("requested_ids", []) if str(x).isdigit()}
    requested_urls = {x.get("url") for x in req.get("requested_articles", []) if isinstance(x, dict) and x.get("url")}
    for article in data.get("articles", []):
        aid = article.get("id")
        if (aid in requested_ids or article.get("url") in requested_urls) and article.get("translation_status") not in {"done", "needs_review"}:
            article["translation_status"] = "requested"
        failure = failures.get("items", {}).get(str(aid))
        if failure and article.get("translation_status") != "done":
            article["translation_status"] = "needs_review"
            article["translation_error"] = failure.get("reason") or article.get("translation_error")
    return data


@app.get("/dates")
def available_dates(limit: int = 60, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    """Return dates that actually have an index, independent of index-list drift."""
    limit = max(1, min(365, int(limit)))
    data_root = APP_DIR / "data"
    dates = []
    if data_root.exists():
        for child in data_root.iterdir():
            if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name) and (child / "index.json").is_file():
                dates.append(child.name)
    dates.sort(reverse=True)
    return {"ok": True, "dates": dates[:limit], "latest": dates[0] if dates else None}


@app.get("/articles/{date}/{article_id}")
def article(date: str, article_id: int, user: sqlite3.Row = Depends(current_user)) -> Any:
    validate_article_date(date)
    if article_id <= 0:
        raise HTTPException(status_code=400, detail="Article ID must be positive")
    padded = f"{article_id:02d}"
    translation = APP_DIR / "data" / date / "translations" / f"{padded}.json"
    if translation.exists():
        return read_json(translation)
    index = read_json(APP_DIR / "data" / date / "index.json")
    for item in index.get("articles", []):
        if int(item.get("id", -1)) == article_id:
            return item
    raise HTTPException(status_code=404, detail="Article not found")


def polish_article_context(date: str, article_id: int) -> dict[str, Any]:
    validate_article_date(date)
    if article_id <= 0:
        raise HTTPException(status_code=400, detail="Article ID must be positive")
    if STORAGE_MODE != "local":
        raise HTTPException(status_code=501, detail="Polish editing requires local server storage")
    index = read_json(safe_repo_path(f"data/{date}/index.json"))
    item = next((item for item in index.get("articles", [])
                 if isinstance(item, dict) and str(item.get("id")) == str(article_id)), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Article not found")
    if not item.get("url"):
        raise HTTPException(status_code=409, detail="Article has no stable URL")
    return item


def safe_polish_path(date: str, filename: str) -> Path:
    if (not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename
            or filename.startswith(".") or filename == "_index.json" or not filename.endswith(".json")):
        raise HTTPException(status_code=400, detail="Invalid polished filename")
    target = safe_repo_path(f"data/{date}/polished/{filename}")
    if target.parent != APP_DIR / "data" / date / "polished":
        raise HTTPException(status_code=400, detail="Invalid polished path")
    return target


def load_polish_state(date: str, article_id: int, article_url: str) -> tuple[dict[str, Any], Path | None, dict[str, Any] | None, str | None]:
    mapping = read_json(safe_repo_path(f"data/{date}/polished/_index.json"), {})
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=500, detail="Polished index must be an object")
    filename = mapping.get(str(article_id))
    if filename is None:
        return mapping, None, None, None
    target = safe_polish_path(date, filename)
    if not target.is_file():
        return mapping, None, None, None
    content = target.read_text(encoding="utf-8-sig")
    try:
        document = json.loads(content)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid polished document") from exc
    # IDs may be reassigned by RSS. Never expose or overwrite another URL's draft.
    if not isinstance(document, dict) or document.get("url") != article_url:
        return mapping, None, None, None
    return mapping, target, document, content_sha(content)


def polish_draft(document: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    paragraphs = document.get("paragraphs", [])
    paragraph_body = "\n\n".join(
        (item if isinstance(item, str) else str(item.get("cn") or item.get("text") or "")).strip()
        for item in paragraphs if isinstance(item, (str, dict))
    ) if isinstance(paragraphs, list) else ""
    values = {
        "title": document.get("cn_title") or "",
        "subtitle": document.get("cn_subtitle") or document.get("summary") or document.get("opus_summary") or "",
        "summary": document.get("opus_summary") or "",
        "body": document.get("cn_body") or document.get("body_cn") or document.get("content") or paragraph_body,
    }
    # An explicitly saved empty field must remain empty on the next edit.
    draft = {field: str(document[field] if field in document and document[field] is not None
                        else values[field] or fallback.get(field, "")) for field in values}
    if document.get("updated_at"):
        draft["updated_at"] = document["updated_at"]
    return draft


def polish_response(document: dict[str, Any], revision: str | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "exists": revision is not None, "revision": revision,
            "draft": polish_draft(document, fallback)}


@app.get("/articles/{date}/{article_id}/polish")
def get_article_polish(date: str, article_id: int, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        item = polish_article_context(date, article_id)
        _, _, existing, revision = load_polish_state(date, article_id, item["url"])
        translation = read_json(safe_repo_path(f"data/{date}/translations/{article_id:02d}.json"), {})
        if not isinstance(translation, dict) or translation.get("url") != item["url"]:
            translation = {}
        fallback = polish_draft(translation, polish_draft(item))
        return polish_response(existing or {}, revision, fallback)


@app.put("/articles/{date}/{article_id}/polish")
def put_article_polish(date: str, article_id: int, payload: PolishWriteRequest,
                       user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        item = polish_article_context(date, article_id)
        if payload.url != item["url"]:
            raise HTTPException(status_code=409, detail="Article URL changed; reload the article before saving")
        mapping, target, existing, revision = load_polish_state(date, article_id, item["url"])
        if payload.expected_revision != revision:
            raise HTTPException(status_code=409, detail="Polished draft changed; reload before saving")
        if target is None:
            title = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", "_", str(item.get("cn_title") or "untitled")).strip("_")[:60] or "untitled"
            stem = f"{article_id:02d}_{title}"
            target = safe_polish_path(date, f"{stem}.json")
            # Preserve unindexed files and old drafts when IDs or titles have drifted.
            while target.exists():
                target = safe_polish_path(date, f"{stem}_{uuid.uuid4().hex[:12]}.json")
        document = dict(existing or {})
        document.update(
            id=article_id, url=item["url"], cn_title=item.get("cn_title", ""),
            en_title=item.get("en_title", ""), category=item.get("category", ""),
            title=payload.title, subtitle=payload.subtitle, summary=payload.summary, body=payload.body,
            paragraphs=[line.strip() for line in payload.body.replace("\r\n", "\n").split("\n") if line.strip()],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        content = json_text(document)
        write_project_file(str(target.relative_to(APP_DIR)), content, "polish: save native draft")
        mapping[str(article_id)] = target.name
        write_project_file(f"data/{date}/polished/_index.json", json_text(mapping), "polish: update native draft index")
        return polish_response(document, content_sha(content))


@app.delete("/articles/{date}/{article_id}/polish")
def delete_article_polish(date: str, article_id: int, payload: PolishDeleteRequest,
                          user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        item = polish_article_context(date, article_id)
        mapping, target, existing, revision = load_polish_state(date, article_id, item["url"])
        if payload.url != item["url"] or not revision or payload.expected_revision != revision:
            raise HTTPException(status_code=409, detail="Article or polished draft changed; reload before deleting")
        mapping.pop(str(article_id), None)
        # Remove the public reference first; interruption can only leave an unindexed draft.
        write_project_file(f"data/{date}/polished/_index.json", json_text(mapping), "polish: remove draft index")
        if target and target.name not in mapping.values():
            target.unlink()
    return {"ok": True, "exists": False, "revision": None}


@app.get("/translations/file-status")
def translation_file_status(
    date: str,
    article_id: int,
) -> dict[str, Any]:
    validate_article_date(date)
    if article_id <= 0:
        raise HTTPException(status_code=400, detail="Article ID must be positive")
    return {"ok": True, **public_translation_file_status(date, article_id)}


@app.post("/filtered/restore")
def restore_filtered_article(payload: FilteredRestoreRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    date = payload.date
    url = payload.url.strip()
    index_rel = f"data/{date}/index.json"
    filtered_rel = f"data/{date}/filtered_rss.json"
    need_rel = f"data/{date}/need_titles.json"
    history_rel = "data/index-list.json"

    idx = read_json(APP_DIR / index_rel, {"date": date, "articles": [], "total": 0})
    if not isinstance(idx, dict):
        idx = {"date": date, "articles": [], "total": 0}
    idx["date"] = idx.get("date") or date
    articles = idx.setdefault("articles", [])
    if not isinstance(articles, list):
        articles = []
        idx["articles"] = articles

    filtered = read_json(APP_DIR / filtered_rel, [])
    if not isinstance(filtered, list):
        raise HTTPException(status_code=500, detail="filtered_rss.json must be a list")

    existing = next((a for a in articles if isinstance(a, dict) and a.get("url") == url), None)
    filtered_item = next((a for a in filtered if isinstance(a, dict) and a.get("url") == url), None)
    if not existing and not filtered_item:
        raise HTTPException(status_code=404, detail="Filtered article not found")

    filtered_updated = [a for a in filtered if not (isinstance(a, dict) and a.get("url") == url)]
    queued = False
    duplicate = existing is not None
    article_item = existing

    if not article_item:
        max_id = max((int(a.get("id") or 0) for a in articles if isinstance(a, dict) and str(a.get("id", "")).isdigit()), default=0)
        article_item = restored_article_from_filtered(filtered_item or {}, max_id + 1)
        articles.append(article_item)
        articles.sort(
            key=lambda a: str((a if isinstance(a, dict) else {}).get("publish_time_cn") or (a if isinstance(a, dict) else {}).get("pub_date") or ""),
            reverse=True,
        )

        need = read_json(APP_DIR / need_rel, [])
        if not isinstance(need, list):
            need = []
        if not any(isinstance(q, dict) and q.get("url") == url for q in need):
            need.append({
                "id": article_item["id"],
                "url": article_item["url"],
                "en_title": article_item.get("en_title") or "",
                "pub_date": article_item.get("publish_time_cn") or article_item.get("pub_date") or "",
            })
            queued = True
        write_project_file(need_rel, json_text(need), f"rss filter: queue restored title #{article_item['id']}")

    idx["total"] = len(articles)
    history = read_json(APP_DIR / history_rel, [])
    if not isinstance(history, list):
        history = []
    row = next((x for x in history if isinstance(x, dict) and x.get("date") == date), None)
    if row:
        row["total"] = idx["total"]
    else:
        history.append({"date": date, "total": idx["total"], "translated": 0, "translatedTitles": []})
    history.sort(key=lambda x: str((x if isinstance(x, dict) else {}).get("date") or ""), reverse=True)

    write_project_file(index_rel, json_text(idx), f"rss filter: restore article for {date}")
    write_project_file(filtered_rel, json_text(filtered_updated), f"rss filter: remove restored article for {date}")
    write_project_file(history_rel, json_text(history), f"rss filter: update index-list for {date}")

    triggered = False
    if payload.trigger_workflow and queued:
        if STORAGE_MODE == "github":
            gh_dispatch_workflow("api-translation.yml", {})
        else:
            run_local_job(["/srv/ign-daily-ops/run-api-translation.sh"])
        triggered = True
    sync_from_github()
    return {
        "ok": True,
        "date": date,
        "article": article_item,
        "index": idx,
        "filtered": filtered_updated,
        "filtered_count": len(filtered_updated),
        "duplicate": duplicate,
        "queued": queued,
        "triggered": triggered,
    }


@app.get("/dict")
def get_dict(user: sqlite3.Row = Depends(current_user)) -> Any:
    return read_json(APP_DIR / "data" / "dict.json")


@app.get("/files/{path:path}")
def get_project_file(path: str, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    target = safe_repo_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    content = target.read_text(encoding="utf-8-sig")
    sha = hashlib.sha1(content.encode("utf-8")).hexdigest()
    return {"ok": True, "path": path, "content": content, "sha": sha}


@app.put("/files/{path:path}")
def put_project_file(path: str, payload: FileWriteRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        if getattr(payload, "expected_absent", False) and safe_repo_path(path).exists():
            raise HTTPException(status_code=409, detail="File was created by another writer")
        result = write_project_file(path, payload.content, payload.message, payload.sha)
    sync_from_github()
    return {"ok": True, "path": path, "result": result, "sha": content_sha(payload.content)}


@app.delete("/files/{path:path}")
def delete_project_file(path: str, payload: FileDeleteRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    target = safe_repo_path(path)
    if STORAGE_MODE == "github":
        result = gh_delete_file(path, payload.message)
        sync_from_github()
        return {"ok": True, "path": path, "result": result}
    with runtime_write_lock():
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if payload.sha is not None:
            current = target.read_text(encoding="utf-8-sig")
            if not hmac.compare_digest(content_sha(current), payload.sha):
                raise HTTPException(status_code=409, detail="File changed before it could be deleted")
        target.unlink()
    return {"ok": True, "path": path, "message": payload.message}


@app.put("/dict")
def replace_dict(payload: DictReplaceRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    if not getattr(payload, "expected_revision", None):
        raise HTTPException(status_code=409, detail="Dictionary revision is required")
    write_project_file("data/dict.json", json_text(payload.dictionary), payload.message, payload.expected_revision)
    sync_from_github()
    return {"ok": True, "message": payload.message}


@app.put("/dict/terms")
def update_dict_term(payload: DictTermUpdateRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    categories = {"games", "movies_tv", "companies", "people", "media", "terms"}
    if payload.category not in categories or payload.original_category not in categories:
        raise HTTPException(status_code=400, detail="Invalid dictionary category")
    with runtime_write_lock():
        dictionary = read_json(APP_DIR / "data/dict.json")
        original = dictionary.get(payload.original_category, {})
        if payload.original_en not in original or original[payload.original_en] != payload.expected_entry:
            raise HTTPException(status_code=409, detail="Dictionary entry changed; reload before saving")
        destination = dictionary.setdefault(payload.category, {})
        if (payload.category, payload.en) != (payload.original_category, payload.original_en) and payload.en in destination:
            raise HTTPException(status_code=409, detail="Destination dictionary entry already exists")
        entry = dict(original[payload.original_en]) if isinstance(original[payload.original_en], dict) else {}
        entry["cn"] = payload.cn
        if getattr(payload, "source", None) is not None:
            entry["source"] = payload.source
        if payload.note is not None:
            entry["note"] = payload.note
        del original[payload.original_en]
        destination[payload.en] = entry
        dictionary.setdefault("_meta", {})["last_updated"] = datetime.now(CST).strftime("%Y-%m-%d")
        content = json_text(dictionary)
        write_project_file("data/dict.json", content, "dict: edit one entry")
    return {"ok": True, "entry": entry, "revision": content_sha(content)}


@app.post("/dict/terms")
def add_dict_term(payload: DictTermRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        dictionary = read_json(APP_DIR / "data" / "dict.json")
        category = payload.category if payload.category in {"games", "movies_tv", "companies", "people", "media", "terms"} else "terms"
        dictionary.setdefault(category, {})
        entry: dict[str, Any] = {"cn": payload.cn, "source": payload.source or "user"}
        if payload.note:
            entry["note"] = payload.note
        dictionary[category][payload.en] = entry
        dictionary.setdefault("_meta", {})["last_updated"] = datetime.now(CST).strftime("%Y-%m-%d")
        message = f"dict: add {payload.en}"
        write_project_file("data/dict.json", json_text(dictionary), message)
    sync_from_github()
    return {"ok": True, "category": category, "en": payload.en, "message": message}


@app.post("/dict/candidates")
def submit_dict_candidate(payload: DictCandidateRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    """Collect a proposed term without mutating the production dictionary."""
    with runtime_write_lock():
        path = "data/dict_candidates.json"
        target = APP_DIR / path
        document = read_json(target, {"version": 1, "candidates": []})
        category = payload.category if payload.category in {"games", "movies_tv", "companies", "people", "media", "terms"} else "terms"
        en, cn = payload.en.strip(), payload.cn.strip()
        if not en or not cn:
            raise HTTPException(status_code=400, detail="English and Chinese terms are required")
        candidate_id = hashlib.sha1(f"{en.casefold()}\0{cn}\0{category}".encode("utf-8")).hexdigest()[:16]
        candidates = [item for item in document.get("candidates", []) if isinstance(item, dict)]
        existing = next((item for item in candidates if item.get("id") == candidate_id), None)
        if existing:
            return {"ok": True, "candidate": existing, "duplicate": True}
        candidate = {
            "id": candidate_id, "en": en, "cn": cn, "category": category,
            "note": payload.note.strip(), "source": "miniprogram", "status": "pending",
            "submitted_at": datetime.now(timezone.utc).isoformat(), "submitted_by": user["username"],
        }
        candidates.append(candidate)
        document.update(version=1, updated_at=datetime.now(timezone.utc).isoformat(), candidates=candidates)
        write_project_file(path, json_text(document), f"dict: propose {en}")
    sync_from_github()
    return {"ok": True, "candidate": candidate, "duplicate": False}


@app.get("/dict/candidates")
def list_dict_candidates(status: str = "pending", user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    document = read_json(APP_DIR / "data" / "dict_candidates.json", {"version": 1, "candidates": []})
    dictionary = read_json(APP_DIR / "data" / "dict.json", {})
    candidates = [item for item in document.get("candidates", []) if isinstance(item, dict)]
    if status != "all":
        candidates = [item for item in candidates if item.get("status", "pending") == status]
    enriched = []
    for item in candidates:
        matches = []
        for category in {"games", "movies_tv", "companies", "people", "media", "terms"}:
            entry = dictionary.get(category, {}).get(item.get("en"))
            if entry is not None:
                value = entry if isinstance(entry, dict) else {"cn": entry}
                matches.append({"category": category, "cn": value.get("cn", "")})
        enriched.append({**item, "official_matches": matches, "has_conflict": any(match["cn"] != item.get("cn") for match in matches)})
    enriched.sort(key=lambda item: item.get("submitted_at", ""), reverse=True)
    return {"ok": True, "candidates": enriched, "count": len(enriched)}


@app.post("/dict/candidates/{candidate_id}/approve")
def approve_dict_candidate(candidate_id: str, payload: DictCandidateReviewRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        path = "data/dict_candidates.json"
        document = read_json(APP_DIR / path, {"version": 1, "candidates": []})
        candidates = [item for item in document.get("candidates", []) if isinstance(item, dict)]
        candidate = next((item for item in candidates if item.get("id") == candidate_id), None)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        category = payload.category or candidate.get("category", "terms")
        if category not in {"games", "movies_tv", "companies", "people", "media", "terms"}:
            category = "terms"
        cn = (payload.cn or candidate.get("cn", "")).strip()
        dictionary = read_json(APP_DIR / "data" / "dict.json")
        for group in {"games", "movies_tv", "companies", "people", "media", "terms"}:
            if group != category:
                dictionary.get(group, {}).pop(candidate["en"], None)
        entry: dict[str, Any] = {"cn": cn, "source": "user"}
        note = payload.note if payload.note is not None else candidate.get("note", "")
        if note:
            entry["note"] = note
        dictionary.setdefault(category, {})[candidate["en"]] = entry
        dictionary.setdefault("_meta", {})["last_updated"] = datetime.now(CST).strftime("%Y-%m-%d")
        write_project_file("data/dict.json", json_text(dictionary), f"dict: approve {candidate['en']}")
        candidate.update(status="approved", category=category, cn=cn, note=note, reviewed_at=datetime.now(timezone.utc).isoformat(), reviewed_by=user["username"])
        document.update(updated_at=datetime.now(timezone.utc).isoformat(), candidates=candidates)
        write_project_file(path, json_text(document), f"dict: archive approved candidate {candidate['en']}")
    sync_from_github()
    return {"ok": True, "candidate": candidate}


@app.post("/dict/candidates/{candidate_id}/reject")
def reject_dict_candidate(candidate_id: str, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        path = "data/dict_candidates.json"
        document = read_json(APP_DIR / path, {"version": 1, "candidates": []})
        candidates = [item for item in document.get("candidates", []) if isinstance(item, dict)]
        candidate = next((item for item in candidates if item.get("id") == candidate_id), None)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        candidate.update(status="rejected", reviewed_at=datetime.now(timezone.utc).isoformat(), reviewed_by=user["username"])
        document.update(updated_at=datetime.now(timezone.utc).isoformat(), candidates=candidates)
        write_project_file(path, json_text(document), f"dict: reject candidate {candidate['en']}")
    sync_from_github()
    return {"ok": True, "candidate": candidate}


@app.post("/translations/request")
def request_translation(payload: TranslationRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    validate_article_date(payload.date)
    if any(article_id <= 0 for article_id in payload.ids):
        raise HTTPException(status_code=400, detail="Article IDs must be positive")
    should_trigger = resolve_translation_trigger(payload.trigger_workflow)
    with runtime_write_lock():
        expected_urls = getattr(payload, "expected_urls", None)
        index = read_json(APP_DIR / "data" / payload.date / "index.json", {} if expected_urls is not None else None)
        by_id = {int(a.get("id")): a for a in index.get("articles", []) if str(a.get("id", "")).isdigit()}
        requested_ids = list(dict.fromkeys(int(article_id) for article_id in payload.ids))
        if expected_urls is not None and any(
            article_id not in by_id or not expected_urls.get(str(article_id))
            or by_id[article_id].get("url") != expected_urls[str(article_id)]
            for article_id in requested_ids
        ):
            raise HTTPException(status_code=409, detail="Article URLs changed; refresh the selection before submitting")
        selected = [by_id[i] for i in requested_ids if i in by_id]
        if not selected:
            raise HTTPException(status_code=404, detail="No matching articles")

        path = f"data/{payload.date}/requests.json"
        existing = read_json(APP_DIR / path, {"date": payload.date, "requested_ids": [], "requested_articles": []})
        merged_ids = sorted({*(int(x) for x in existing.get("requested_ids", []) if str(x).isdigit()), *[int(a["id"]) for a in selected]})
        merged_articles = {item.get("url"): item for item in existing.get("requested_articles", []) if isinstance(item, dict) and item.get("url")}
        for article_item in selected:
            merged_articles[article_item.get("url")] = {
                "id": article_item.get("id"),
                "url": article_item.get("url"),
                "en_title": article_item.get("en_title"),
                "cn_title": article_item.get("cn_title"),
            }
        updated = {
            "date": payload.date,
            "requested_ids": merged_ids,
            "requested_articles": list(merged_articles.values()),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "requested_by": user["username"],
        }
        write_project_file(path, json_text(updated), f"request translation for {payload.date}: {','.join(map(str, requested_ids))}")
        selected_ids = [int(a["id"]) for a in selected]
        job_ids, created_job_ids, reused_job_ids = create_or_reuse_translation_jobs(
            payload.date,
            selected_ids,
            user["username"],
            "翻译请求已提交",
        )
        job_id = job_ids[0]
    if should_trigger and created_job_ids:
        if STORAGE_MODE == "github":
            gh_dispatch_workflow("api-translation.yml", {})
            for created_job_id in created_job_ids:
                update_job(created_job_id, "running", "已触发 GitHub 翻译流程", 10)
        else:
            for created_job_id in created_job_ids:
                update_job(created_job_id, "running", "服务器正在翻译", 10)
            run_local_job(["/srv/ign-daily-ops/run-api-translation.sh"], created_job_ids[0], created_job_ids)
    else:
        for created_job_id in created_job_ids:
            update_job(created_job_id, "queued", "已加入翻译队列", 5)
    sync_from_github()
    return {
        "ok": True,
        "date": payload.date,
        "requested_ids": merged_ids,
        "job_id": job_id,
        "job_ids": job_ids,
        "created_job_ids": created_job_ids,
        "reused_job_ids": reused_job_ids,
        "deduplicated": bool(reused_job_ids),
        "job_batch_size": MAX_TRANSLATION_JOB_ARTICLES,
        "triggered": should_trigger and bool(created_job_ids),
    }


@app.post("/translations/approve")
def approve_translation(payload: ManualApproveRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    with runtime_write_lock():
        date = validate_article_date(payload.date)
        article_id = int(payload.article_id)
        padded = f"{article_id:02d}"
        trans_rel = f"data/{date}/translations/{padded}.json"
        index_rel = f"data/{date}/index.json"
        fail_rel = f"data/{date}/translation_failures.json"
        trans_path = APP_DIR / trans_rel
        if not trans_path.exists():
            raise HTTPException(status_code=404, detail="Translation draft not found")

        now = datetime.now(timezone.utc).isoformat()
        item = polish_article_context(date, article_id)
        content = trans_path.read_text(encoding="utf-8-sig")
        if payload.url != item["url"] or payload.expected_revision != content_sha(content):
            raise HTTPException(status_code=409, detail="Article or draft changed; reload before approving")
        data = json.loads(content)
        if data.get("url") != payload.url:
            raise HTTPException(status_code=409, detail="Translation URL does not match article")
        data["quality_status"] = "manual_approved"
        data["manual_release_required"] = False
        data["manual_approved_at"] = now
        data["manual_approved_by"] = user["username"]
        data["manual_approved_reason"] = "user approved API audit draft"
        data["manual_approved_issues"] = data.get("audit_issues", [])
        data["reviewer_model"] = "human"
        data["reviewed_at"] = now
        data["quality_gate_version"] = QUALITY_GATE_VERSION
        data["quality_review"] = {
            "status": "passed",
            "reviewer_model": "human",
            "reviewed_at": now,
            "checks": {
                "source_coverage": True,
                "quote_attribution": True,
                "numeric_facts": True,
            },
            "reviewed_by": user["username"],
        }
        data.pop("audit_issues", None)
        data.pop("audit_failed_at", None)
        data.pop("audit_failure_reason", None)
        quality_errors = translation_completion_errors(date, article_id, require_index=False, document=data)
        if quality_errors:
            raise HTTPException(
                status_code=409,
                detail=f"Translation quality gate failed: {'; '.join(quality_errors)}",
            )
        write_project_file(trans_rel, json_text(data), f"manual approve translation #{article_id}")

        idx = read_json(APP_DIR / index_rel)
        for art in idx.get("articles", []):
            if int(art.get("id", -1)) == article_id:
                art["translation_status"] = "done"
                art["translation_path"] = f"translations/{padded}.json"
                art["cn_title"] = data.get("cn_title") or art.get("cn_title")
                art["summary"] = data.get("opus_summary") or data.get("summary") or art.get("summary")
                art["translator"] = data.get("translator") or art.get("translator")
                art["translator_provider"] = data.get("translator_provider") or art.get("translator_provider")
                art["translator_model"] = data.get("translator_model") or art.get("translator_model")
                for meta_key in (
                    "reasoning_effort",
                    "reviewer_model",
                    "reviewed_at",
                    "prompt_version",
                    "quality_gate_version",
                ):
                    art[meta_key] = data.get(meta_key)
                art.pop("translation_error", None)
                art.pop("translation_failed_at", None)
                break
        write_project_file(index_rel, json_text(idx), f"index: manual approve #{article_id}")

        failures = read_json(APP_DIR / fail_rel, {"date": date, "items": {}})
        if isinstance(failures, dict):
            failures.setdefault("items", {}).pop(str(article_id), None)
            failures["updated_at"] = now
            write_project_file(fail_rel, json_text(failures), f"translation failure: clear #{article_id}")

        sync_from_github()
        return {"ok": True, "date": date, "article_id": article_id, "article": data}


@app.get("/jobs")
def list_jobs(kind: str | None = None, limit: int = 10, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    limit = max(1, min(50, int(limit)))
    with db() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"ok": True, "jobs": [serialize_job(row) for row in rows]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    row = load_job_row(job_id)
    return {"ok": True, "job": serialize_job(row)}


@app.get("/codex/jobs/pending")
def codex_pending_jobs(limit: int = 5, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    limit = max(1, min(20, int(limit)))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE kind = 'translation' AND status IN ('queued', 'running')
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    jobs = []
    for row in rows:
        job = serialize_job(row)
        if job.get("date") and job.get("ids"):
            job["items"] = article_payload_for_job(str(job["date"]), [int(x) for x in job["ids"]])
        jobs.append(job)
    return {"ok": True, "jobs": jobs}


@app.post("/codex/jobs/{job_id}/claim")
def codex_claim_job(job_id: str, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    row = load_job_row(job_id)
    if row["kind"] != "translation":
        raise HTTPException(status_code=400, detail="Only translation jobs can be claimed by Codex")
    if row["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail=f"Job is already {row['status']}")
    update_job(job_id, "running", f"Claimed by Codex: {user['username']}", 10)
    claimed = serialize_job(load_job_row(job_id))
    if claimed.get("date") and claimed.get("ids"):
        claimed["items"] = article_payload_for_job(str(claimed["date"]), [int(x) for x in claimed["ids"]])
    return {"ok": True, "job": claimed}


@app.post("/codex/jobs/{job_id}/progress")
def codex_update_job_progress(
    job_id: str,
    payload: CodexJobProgressRequest,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    row = load_job_row(job_id)
    status = payload.status or row["status"] or "running"
    if status not in {"queued", "running", "done", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid job status")
    progress = payload.progress if payload.progress is not None else int(row["progress"] or 0)
    if status == "done":
        return codex_complete_job(job_id, payload, user)
    update_job(job_id, status, payload.message or None, progress)
    if payload.article_id:
        step = payload.step or ("done" if status == "done" else "failed" if status == "failed" else "codex")
        step_label = payload.step_label or payload.message or step
        write_job_progress_item(
            job_id,
            date=row["date"],
            article_id=int(payload.article_id),
            status=status,
            step=step,
            step_label=step_label,
            progress=progress,
            message=payload.message or step_label,
        )
    return {"ok": True, "job": serialize_job(load_job_row(job_id))}


@app.post("/codex/jobs/{job_id}/complete")
def codex_complete_job(
    job_id: str,
    payload: CodexJobCompleteRequest,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    with runtime_write_lock():
        row = load_job_row(job_id)
        if row["kind"] != "translation":
            raise HTTPException(status_code=400, detail="Only translation jobs can be completed by Codex")
        ids = json.loads(row["ids_json"] or "[]")
        if len(ids) > MAX_TRANSLATION_JOB_ARTICLES:
            raise HTTPException(
                status_code=409,
                detail=f"Translation job exceeds hard batch limit of {MAX_TRANSLATION_JOB_ARTICLES} articles",
            )
        missing: list[int] = []
        quality_failures: list[str] = []
        index = read_json(APP_DIR / "data" / str(row["date"]) / "index.json", {"articles": []})
        by_id = {
            int(item.get("id")): item
            for item in index.get("articles", [])
            if isinstance(item, dict) and str(item.get("id", "")).isdigit()
        }
        for article_id in ids:
            article_id = int(article_id)
            path = APP_DIR / "data" / str(row["date"]) / "translations" / f"{article_id:02d}.json"
            if not path.is_file():
                missing.append(article_id)
                continue
            errors = translation_completion_errors(str(row["date"]), article_id, expected_url=job_expected_url(row, article_id))
            if by_id.get(article_id, {}).get("translation_status") != "done":
                errors.append("index translation_status must be done")
            expected_path = f"translations/{article_id:02d}.json"
            if by_id.get(article_id, {}).get("translation_path") != expected_path:
                errors.append(f"index translation_path must be {expected_path}")
            quality_failures.extend(f"#{article_id}: {error}" for error in errors)
        if missing:
            raise HTTPException(
                status_code=409,
                detail=f"Translation files are missing for article ids: {','.join(map(str, missing))}",
            )
        if quality_failures:
            raise HTTPException(
                status_code=409,
                detail=f"Translation quality gate failed: {'; '.join(quality_failures)}",
            )
        for article_id in ids:
            write_job_progress_item(
                job_id,
                date=row["date"],
                article_id=int(article_id),
                status="done",
                step="done",
                step_label="Codex completed",
                progress=100,
                message=payload.message,
            )
        update_job(job_id, "done", payload.message, 100)
    sync_from_github()
    job = serialize_job(load_job_row(job_id))
    try:
        notification_sent = send_job_completion_notification(job)
    except Exception:
        notification_sent = False
    return {"ok": True, "job": job, "notification_sent": notification_sent}


@app.post("/codex/jobs/{job_id}/fail")
def codex_fail_job(
    job_id: str,
    payload: CodexJobFailRequest,
    user: sqlite3.Row = Depends(current_user),
) -> dict[str, Any]:
    update_job(job_id, "failed", payload.message, 100)
    return {"ok": True, "job": serialize_job(load_job_row(job_id))}


@app.post("/workflows/dispatch")
def dispatch_workflow(payload: WorkflowRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    allowed = {"api-translation.yml", "hourly-rss.yml", "exchange-rates.yml", "deepseek-usage.yml", "nightly-style.yml"}
    if payload.workflow not in allowed:
        raise HTTPException(status_code=400, detail="Workflow is not allowed")
    if STORAGE_MODE == "github":
        gh_dispatch_workflow(payload.workflow, payload.inputs)
    else:
        if payload.workflow == "nightly-style.yml":
            return {
                "ok": True,
                "workflow": payload.workflow,
                "mode": "codex",
                "message": "Nightly learning is owned by Codex automation for this server.",
            }
        local = {
            "api-translation.yml": "/srv/ign-daily-ops/run-api-translation.sh",
            "hourly-rss.yml": "/srv/ign-daily-ops/run-rss.sh",
            "exchange-rates.yml": "/srv/ign-daily-ops/run-exchange.sh",
            "deepseek-usage.yml": "/srv/ign-daily-ops/run-balance.sh",
        }
        run_local_job([local[payload.workflow]])
    return {"ok": True, "workflow": payload.workflow}
