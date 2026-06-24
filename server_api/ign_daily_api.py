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
import secrets
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


CST = timezone(timedelta(hours=8))
APP_DIR = Path(os.environ.get("IGN_DAILY_REPO_PATH", "/srv/ign-daily")).resolve()
API_DIR = Path(os.environ.get("IGN_DAILY_API_DIR", "/srv/ign-daily-api")).resolve()
DB_PATH = Path(os.environ.get("IGN_DAILY_API_DB", API_DIR / "auth.sqlite3")).resolve()
ENV_PATHS = [APP_DIR / ".env", API_DIR / ".env"]
SESSION_COOKIE = "ign_daily_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
PBKDF2_ROUNDS = 210_000
GITHUB_OWNER = os.environ.get("IGN_DAILY_GITHUB_OWNER", "ZenoTzz")
GITHUB_REPO = os.environ.get("IGN_DAILY_GITHUB_REPO", "ign-daily")
GITHUB_BRANCH = os.environ.get("IGN_DAILY_GITHUB_BRANCH", "main")
STORAGE_MODE = os.environ.get("IGN_DAILY_STORAGE_MODE", "local").strip().lower()


def load_env_files() -> None:
    for path in ENV_PATHS:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_files()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class TranslationRequest(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    ids: list[int] = Field(min_length=1)
    trigger_workflow: bool = True


class DictTermRequest(BaseModel):
    category: str = "terms"
    en: str = Field(min_length=1, max_length=240)
    cn: str = Field(min_length=1, max_length=240)
    source: str = "user"
    note: str = ""


class DictReplaceRequest(BaseModel):
    dictionary: dict[str, Any]
    message: str = "dict: update via private API"


class WorkflowRequest(BaseModel):
    workflow: str
    inputs: dict[str, Any] = Field(default_factory=dict)


def db() -> sqlite3.Connection:
    API_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


def json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def safe_repo_path(path: str) -> Path:
    target = (APP_DIR / path).resolve()
    if APP_DIR not in target.parents and target != APP_DIR:
        raise HTTPException(status_code=400, detail="Invalid repository path")
    return target


def write_project_file(path: str, content: str, message: str = "") -> Any:
    if STORAGE_MODE == "github":
        return gh_put_file(path, content, message)
    target = safe_repo_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "mode": "local", "message": message}


def run_local_job(command: list[str]) -> None:
    subprocess.Popen(
        command,
        cwd=APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


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


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time_cn": now_cn(), "app_dir": str(APP_DIR), "storage_mode": STORAGE_MODE}


@app.post("/auth/login")
def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (payload.username,)).fetchone()
        if not row or not verify_password(payload.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, row["id"], now, now + SESSION_TTL_SECONDS),
        )
        conn.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("IGN_DAILY_COOKIE_SECURE", "0") == "1",
    )
    return {"ok": True, "token": token, "user": {"username": payload.username}}


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
    return {"ok": True, "user": {"username": user["username"]}}


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


@app.get("/articles")
def articles(date: str, user: sqlite3.Row = Depends(current_user)) -> Any:
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


@app.get("/articles/{date}/{article_id}")
def article(date: str, article_id: int, user: sqlite3.Row = Depends(current_user)) -> Any:
    padded = f"{article_id:02d}"
    translation = APP_DIR / "data" / date / "translations" / f"{padded}.json"
    if translation.exists():
        return read_json(translation)
    index = read_json(APP_DIR / "data" / date / "index.json")
    for item in index.get("articles", []):
        if int(item.get("id", -1)) == article_id:
            return item
    raise HTTPException(status_code=404, detail="Article not found")


@app.get("/dict")
def get_dict(user: sqlite3.Row = Depends(current_user)) -> Any:
    return read_json(APP_DIR / "data" / "dict.json")


@app.put("/dict")
def replace_dict(payload: DictReplaceRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    write_project_file("data/dict.json", json_text(payload.dictionary), payload.message)
    sync_from_github()
    return {"ok": True, "message": payload.message}


@app.post("/dict/terms")
def add_dict_term(payload: DictTermRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
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


@app.post("/translations/request")
def request_translation(payload: TranslationRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    index = read_json(APP_DIR / "data" / payload.date / "index.json")
    by_id = {int(a.get("id")): a for a in index.get("articles", []) if str(a.get("id", "")).isdigit()}
    selected = [by_id[i] for i in payload.ids if i in by_id]
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
    write_project_file(path, json_text(updated), f"request translation for {payload.date}: {','.join(map(str, payload.ids))}")
    if payload.trigger_workflow:
        if STORAGE_MODE == "github":
            gh_dispatch_workflow("api-translation.yml", {})
        else:
            run_local_job(["/srv/ign-daily-ops/run-api-translation.sh"])
    sync_from_github()
    return {"ok": True, "date": payload.date, "requested_ids": merged_ids, "triggered": payload.trigger_workflow}


@app.post("/workflows/dispatch")
def dispatch_workflow(payload: WorkflowRequest, user: sqlite3.Row = Depends(current_user)) -> dict[str, Any]:
    allowed = {"api-translation.yml", "hourly-rss.yml", "exchange-rates.yml", "deepseek-usage.yml"}
    if payload.workflow not in allowed:
        raise HTTPException(status_code=400, detail="Workflow is not allowed")
    if STORAGE_MODE == "github":
        gh_dispatch_workflow(payload.workflow, payload.inputs)
    else:
        local = {
            "api-translation.yml": "/srv/ign-daily-ops/run-api-translation.sh",
            "hourly-rss.yml": "/srv/ign-daily-ops/run-rss.sh",
            "exchange-rates.yml": "/srv/ign-daily-ops/run-exchange.sh",
            "deepseek-usage.yml": "/srv/ign-daily-ops/run-balance.sh",
        }
        run_local_job([local[payload.workflow]])
    return {"ok": True, "workflow": payload.workflow}
