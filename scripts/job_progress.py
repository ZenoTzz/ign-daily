"""Lightweight per-article progress reporting for server-side jobs."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from common_paths import DATA_DIR


STEP_LABELS = {
    "queued": "排队等待",
    "source": "抓取正文",
    "extract": "解析段落",
    "model": "模型翻译",
    "parse": "整理译文",
    "audit": "质量检查",
    "repair": "修复问题",
    "write": "写入文件",
    "done": "已写入译文",
    "failed": "翻译失败",
}


def current_job_id() -> str:
    return (os.environ.get("IGN_DAILY_JOB_ID") or "").strip()


def progress_path(job_id: str) -> Path:
    return DATA_DIR / "job-progress" / f"{job_id}.json"


def load_progress(job_id: str) -> dict[str, Any]:
    path = progress_path(job_id)
    if not path.exists():
        return {"job_id": job_id, "articles": {}, "updated_at": int(time.time())}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"job_id": job_id, "articles": {}, "updated_at": int(time.time())}


def save_progress(job_id: str, data: dict[str, Any]) -> None:
    path = progress_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def set_article_step(
    article_id: int | str,
    *,
    date: str,
    step: str,
    progress: int,
    status: str = "running",
    message: str = "",
    job_id: str | None = None,
) -> None:
    jid = job_id or current_job_id()
    if not jid:
        return
    aid = str(int(article_id))
    data = load_progress(jid)
    item = data.setdefault("articles", {}).setdefault(aid, {})
    item.update(
        {
            "id": int(article_id),
            "date": date,
            "status": status,
            "step": step,
            "step_label": STEP_LABELS.get(step, step),
            "progress": max(0, min(100, int(progress))),
            "message": message or STEP_LABELS.get(step, step),
            "updated_at": int(time.time()),
        }
    )
    data["updated_at"] = int(time.time())
    save_progress(jid, data)
