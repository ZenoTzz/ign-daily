#!/usr/bin/env python3
"""Small client for Codex-owned translation jobs.

This script intentionally does not call a translation model. It lets a Codex
run claim jobs from the server, inspect the article payload, and write status
back while Codex performs the actual translation work in the workspace.

Environment:
  IGN_DAILY_API_BASE   Defaults to https://igndaily.site/api
  IGN_DAILY_API_TOKEN  Bearer token from the server login response
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE = "https://igndaily.site/api"


def api_base() -> str:
    return (os.environ.get("IGN_DAILY_API_BASE") or DEFAULT_BASE).rstrip("/")


def api_token() -> str:
    token = (os.environ.get("IGN_DAILY_API_TOKEN") or "").strip()
    if not token:
        raise SystemExit("IGN_DAILY_API_TOKEN is required")
    return token


def request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base()}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {api_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ign-daily-codex-job-client",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    pending = sub.add_parser("pending")
    pending.add_argument("--limit", type=int, default=5)

    claim = sub.add_parser("claim")
    claim.add_argument("job_id")

    progress = sub.add_parser("progress")
    progress.add_argument("job_id")
    progress.add_argument("--article-id", type=int)
    progress.add_argument("--status", default="running")
    progress.add_argument("--step", default="codex")
    progress.add_argument("--step-label", default="Codex processing")
    progress.add_argument("--progress", type=int, default=10)
    progress.add_argument("--message", default="")

    complete = sub.add_parser("complete")
    complete.add_argument("job_id")
    complete.add_argument("--message", default="Codex batch completed")

    fail = sub.add_parser("fail")
    fail.add_argument("job_id")
    fail.add_argument("--message", required=True)

    args = parser.parse_args()
    if args.cmd == "pending":
        query = urllib.parse.urlencode({"limit": args.limit})
        print_json(request(f"/codex/jobs/pending?{query}"))
    elif args.cmd == "claim":
        print_json(request(f"/codex/jobs/{urllib.parse.quote(args.job_id)}/claim", method="POST", payload={}))
    elif args.cmd == "progress":
        print_json(
            request(
                f"/codex/jobs/{urllib.parse.quote(args.job_id)}/progress",
                method="POST",
                payload={
                    "article_id": args.article_id,
                    "status": args.status,
                    "step": args.step,
                    "step_label": args.step_label,
                    "progress": args.progress,
                    "message": args.message,
                },
            )
        )
    elif args.cmd == "complete":
        print_json(
            request(
                f"/codex/jobs/{urllib.parse.quote(args.job_id)}/complete",
                method="POST",
                payload={"message": args.message},
            )
        )
    elif args.cmd == "fail":
        print_json(
            request(
                f"/codex/jobs/{urllib.parse.quote(args.job_id)}/fail",
                method="POST",
                payload={"message": args.message},
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
