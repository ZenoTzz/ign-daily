"""Short runtime transactions shared with the API; never wrap model calls."""
from __future__ import annotations
import contextlib
import copy
import functools
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
try:
    import fcntl
except ImportError:  # Offline Windows tooling only; production runs Linux.
    fcntl = None

_guard = threading.RLock()
_local = threading.local()

class RuntimeConflict(RuntimeError):
    """The input changed during computation. Keep the newer server content."""

def lock_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    default = "/var/lock/ign-daily-write.lock" if str(root).startswith("/srv/") else str(Path(tempfile.gettempdir()) / ("ign-daily-write-" + hashlib.sha256(str(root).encode()).hexdigest()[:12] + ".lock"))
    return Path(os.environ.get("IGN_DAILY_WRITE_LOCK", os.environ.get("IGN_DAILY_WRITE_LOCK_PATH", default)))

@contextlib.contextmanager
def write_lock():
    with _guard:
        if getattr(_local, "fd", None) is not None:
            yield
            return
        inherited = os.environ.get("IGN_DAILY_WRITE_LOCK_FD")
        if inherited:
            fd = int(inherited)
            # Only trust an actually inherited descriptor for this lock inode.
            if os.fstat(fd).st_ino != lock_path().stat().st_ino or os.fstat(fd).st_dev != lock_path().stat().st_dev:
                raise RuntimeError("Invalid inherited runtime lock")
            _local.fd = fd
            try: yield
            finally: _local.fd = None
            return
        path = lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stream:
            if fcntl: fcntl.flock(stream, fcntl.LOCK_EX)
            _local.fd = stream.fileno()
            try: yield
            finally:
                _local.fd = None
                if fcntl: fcntl.flock(stream, fcntl.LOCK_UN)

def locked(func):
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        with write_lock(): return func(*args, **kwargs)
    return wrapped

def subprocess_lock_kwargs():
    fd = getattr(_local, "fd", None)
    if fd is None: raise RuntimeError("A short runtime lock is required")
    return {"pass_fds": (fd,), "env": {**os.environ, "IGN_DAILY_WRITE_LOCK_FD": str(fd)}}

def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else copy.deepcopy(default)

def file_revision(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def article_snapshot(data_dir: Path, date: str, article: dict):
    with write_lock():
        current = read_json(data_dir / date / "index.json", {})
        row = next((a for a in current.get("articles", []) if a.get("id") == article.get("id")), None)
        if row != article: raise RuntimeConflict("Article changed before work started")
        return {"article": copy.deepcopy(article), **{kind: file_revision(data_dir / date / kind / f"{int(article['id']):02d}.json") for kind in ("translations", "sources")}}

@contextlib.contextmanager
def article_transaction(data_dir: Path, date: str, article: dict, index: dict, req: dict, snapshot=None):
    with write_lock():
        current = read_json(data_dir / date / "index.json", {})
        row = next((a for a in current.get("articles", []) if a.get("id") == article.get("id")), None)
        baseline = snapshot["article"] if snapshot else article
        if row != baseline or not row or row.get("url") != article.get("url"):
            raise RuntimeConflict("Article identity or contents changed; reload before retrying")
        if snapshot:
            for kind in ("translations", "sources"):
                if file_revision(data_dir / date / kind / f"{int(article['id']):02d}.json") != snapshot[kind]:
                    raise RuntimeConflict(f"Article {kind} changed; newer content retained")
        # Preserve all unrelated article edits and requests submitted during the model call.
        index.clear(); index.update(current)
        index["articles"] = [article if a.get("id") == article["id"] else a for a in index.get("articles", [])]
        req.clear(); req.update(read_json(data_dir / date / "requests.json", {"date": date, "requested_ids": [], "requested_articles": []}))
        paths = [data_dir / date / name for name in ("index.json", "requests.json", "translation_failures.json")]
        paths += [data_dir / date / "translations" / f"{int(article['id']):02d}.json", data_dir / "index-list.json"]
        before = {p: p.read_bytes() if p.exists() else None for p in paths}
        try: yield
        except BaseException:
            for path, content in before.items():
                if content is None: path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
            raise
