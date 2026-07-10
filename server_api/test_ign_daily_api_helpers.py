"""Dependency-free regression tests for private API path and write guards."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).with_name("ign_daily_api.py")


class FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def fake_dependencies() -> dict[str, types.ModuleType]:
    fastapi = types.ModuleType("fastapi")

    class FastAPI:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def add_middleware(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def _route(*_args: object, **_kwargs: object):
            return lambda fn: fn

        get = post = put = delete = on_event = _route

    fastapi.Cookie = lambda **_kwargs: None
    fastapi.Depends = lambda value: value
    fastapi.FastAPI = FastAPI
    fastapi.Header = lambda **_kwargs: None
    fastapi.HTTPException = FakeHTTPException
    fastapi.Request = object
    fastapi.Response = object
    middleware = types.ModuleType("fastapi.middleware")
    cors = types.ModuleType("fastapi.middleware.cors")
    cors.CORSMiddleware = object

    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        pass

    pydantic.BaseModel = BaseModel
    pydantic.Field = lambda default=None, **_kwargs: default
    return {
        "fastapi": fastapi,
        "fastapi.middleware": middleware,
        "fastapi.middleware.cors": cors,
        "pydantic": pydantic,
    }


def load_api(repo: Path, api_dir: Path, extra_env: dict[str, str] | None = None):
    env = {
        "IGN_DAILY_REPO_PATH": str(repo),
        "IGN_DAILY_API_DIR": str(api_dir),
    }
    if extra_env:
        env.update(extra_env)
    dependencies = fake_dependencies()
    with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, dependencies):
        sys.modules.pop("_ign_daily_api_test", None)
        spec = importlib.util.spec_from_file_location("_ign_daily_api_test", MODULE_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


class PrivateApiFileGuardsTest(unittest.TestCase):
    def test_env_file_is_loaded_before_startup_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            (api_dir / ".env").write_text(
                "IGN_DAILY_STORAGE_MODE=github\n"
                "IGN_DAILY_CORS_ORIGINS=https://igndaily.site\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"IGN_DAILY_STORAGE_MODE": ""}, clear=False):
                os.environ.pop("IGN_DAILY_STORAGE_MODE", None)
                module = load_api(repo, api_dir)
            self.assertEqual(module.STORAGE_MODE, "github")

    def test_runtime_json_write_is_atomic_and_revision_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            target = repo / "data" / "state.json"
            module.write_project_file("data/state.json", '{"version": 1}\n')
            revision = module.content_sha(target.read_text(encoding="utf-8"))
            module.write_project_file("data/state.json", '{"version": 2}\n', expected_sha=revision)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"version": 2}\n')
            with self.assertRaises(FakeHTTPException) as raised:
                module.write_project_file("data/state.json", '{"version": 3}\n', expected_sha=revision)
            self.assertEqual(raised.exception.status_code, 409)
            with self.assertRaises(FakeHTTPException) as raised:
                module.write_project_file("data/state.json", "not-json")
            self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"version": 2}\n')
            self.assertFalse(list(target.parent.glob(".*.tmp")))

    def test_file_api_rejects_secrets_and_executable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            for path in (".env", "server_api/ign_daily_api.py", "../data/x.json", "data/notes.txt"):
                with self.subTest(path=path), self.assertRaises(FakeHTTPException) as raised:
                    module.safe_repo_path(path)
                self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(
                module.safe_repo_path("data/2026-07-10/index.json"),
                (repo / "data/2026-07-10/index.json").resolve(),
            )

    def test_github_delete_checks_path_before_calling_github(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "github"})
            github_delete = Mock()
            module.gh_delete_file = github_delete
            payload = types.SimpleNamespace(message="test", sha=None)
            with self.assertRaises(FakeHTTPException) as raised:
                module.delete_project_file(".env", payload, {"username": "tester"})
            self.assertEqual(raised.exception.status_code, 400)
            github_delete.assert_not_called()

    def test_login_failures_are_temporarily_rate_limited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            module.init_db()
            for _ in range(module.LOGIN_MAX_FAILURES):
                module.record_login_failure("127.0.0.1")
            with self.assertRaises(FakeHTTPException) as raised:
                module.enforce_login_rate_limit("127.0.0.1")
            self.assertEqual(raised.exception.status_code, 429)
            module.clear_login_failures("127.0.0.1")
            module.enforce_login_rate_limit("127.0.0.1")

    def test_codex_job_cannot_complete_before_translation_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            module.init_db()
            job_id = module.create_job("translation", "2026-07-10", [1], "tester")
            payload = types.SimpleNamespace(message="done")
            with self.assertRaises(FakeHTTPException) as raised:
                module.codex_complete_job(job_id, payload, {"username": "tester"})
            self.assertEqual(raised.exception.status_code, 409)

            translation = repo / "data" / "2026-07-10" / "translations" / "01.json"
            translation.parent.mkdir(parents=True)
            translation.write_text("{}\n", encoding="utf-8")
            result = module.codex_complete_job(job_id, payload, {"username": "tester"})
            self.assertTrue(result["ok"])
            self.assertEqual(result["job"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
