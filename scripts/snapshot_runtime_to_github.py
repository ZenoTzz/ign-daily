#!/usr/bin/env python3
"""Commit a conservative runtime-data snapshot without deploying code.

The server data directory is authoritative. This job clones a disposable
GitHub worktree, copies only explicitly allowed runtime content into it, and
pushes a data-only commit. It never deletes historical files from the mirror.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from common_paths import REPO_ROOT, env_paths
from git_push import git_auth_env, load_env

try:
    import fcntl
except ImportError:  # Windows unit tests never run the server snapshot itself.
    fcntl = None


DATE_DIR_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
ROOT_FILES = {
    "dict.json",
    "index-list.json",
    "site-compliance.json",
}
RUNTIME_DIRS: set[str] = set()
LOCK_PATH = Path(os.environ.get("IGN_DAILY_WRITE_LOCK", "/var/lock/ign-daily-write.lock"))


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, check=check)


@contextmanager
def write_lock(timeout_seconds: int = 120):
    if fcntl is None:
        yield
        return
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("runtime write lock remained busy")
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def copy_runtime_snapshot(source: Path, destination: Path) -> list[str]:
    copied: list[str] = []
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(ROOT_FILES):
        item = source / name
        if item.is_file():
            shutil.copy2(item, destination / name)
            copied.append(name)
    for item in sorted(source.iterdir() if source.exists() else []):
        if not item.is_dir() or (not DATE_DIR_RE.fullmatch(item.name) and item.name not in RUNTIME_DIRS):
            continue
        shutil.copytree(item, destination / item.name, dirs_exist_ok=True)
        copied.append(item.name + "/")
    return copied


def clone_with_retries(url: str, branch: str, checkout: Path, reference: Path | None = None) -> None:
    command = ["git", "clone", "--depth", "1", "--branch", branch]
    if reference and reference.is_dir():
        command.extend(["--reference-if-able", str(reference)])
    command.extend([url, str(checkout)])
    last_error = 1
    for attempt in range(3):
        shutil.rmtree(checkout, ignore_errors=True)
        result = run(command, check=False)
        last_error = result.returncode
        if last_error == 0:
            return
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"runtime snapshot clone failed after 3 attempts: {last_error}")


def snapshot(app_dir: Path, *, dry_run: bool = False) -> bool:
    data_dir = app_dir / "data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"runtime data directory is missing: {data_dir}")

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="ign-daily-snapshot-dry-") as temporary:
            with write_lock():
                copied = copy_runtime_snapshot(data_dir, Path(temporary) / "data")
            if not copied:
                raise RuntimeError("snapshot whitelist matched no runtime content")
            print(f"RUNTIME_SNAPSHOT changed=0 dry_run=1 copied={len(copied)}")
            return False

    settings = load_env(next((path for path in env_paths() if path.exists()), env_paths()[0]))
    token = settings.get("GITHUB_PAT_IGN_DAILY") or os.environ.get("GITHUB_PAT_IGN_DAILY", "")
    owner = settings.get("GITHUB_USER_IGN_DAILY") or os.environ.get("GITHUB_USER_IGN_DAILY", "ZenoTzz")
    repo = os.environ.get("IGN_DAILY_GITHUB_REPO", "ign-daily")
    branch = os.environ.get("IGN_DAILY_GITHUB_BRANCH", "main")
    if not token:
        raise RuntimeError("GITHUB_PAT_IGN_DAILY is required for runtime snapshots")

    repository_url = f"https://github.com/{owner}/{repo}.git"
    auth_env = git_auth_env(token, owner)
    last_error = 1
    with tempfile.TemporaryDirectory(prefix="ign-daily-snapshot-") as temporary:
        for attempt in range(3):
            # Always retry from a fresh clone of the latest remote branch. A
            # pull --rebase after copying runtime files can refuse to run when
            # Git detects a dirty worktree, and reusing that checkout makes all
            # later retries fail for the same reason.
            checkout = Path(temporary) / f"repo-{attempt + 1}"
            clone_with_retries(repository_url, branch, checkout, app_dir / ".git")
            with write_lock():
                copied = copy_runtime_snapshot(data_dir, checkout / "data")
            if not copied:
                raise RuntimeError("snapshot whitelist matched no runtime content")
            run(["git", "add", "--", "data"], cwd=checkout)
            changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=checkout).returncode != 0
            if not changed:
                print(f"RUNTIME_SNAPSHOT changed=0 dry_run=0 copied={len(copied)}")
                return False
            run(["git", "config", "user.name", "IGN Daily Server Snapshot"], cwd=checkout)
            run(["git", "config", "user.email", "ign-daily-snapshot@users.noreply.github.com"], cwd=checkout)
            run(["git", "commit", "-m", f"data: runtime snapshot {time.strftime('%Y-%m-%d')}"] , cwd=checkout)
            push = run(
                ["git", "-c", "credential.helper=", "push", "origin", f"HEAD:{branch}"],
                cwd=checkout,
                env=auth_env,
                check=False,
            )
            last_error = push.returncode
            if last_error == 0:
                print(f"RUNTIME_SNAPSHOT_OK copied={len(copied)}")
                return True
            time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"runtime snapshot push failed after 3 fresh-clone attempts: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=REPO_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    snapshot(args.app_dir.resolve(), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
