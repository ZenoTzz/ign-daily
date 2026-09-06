"""Dependency-free regression tests for private API path and write guards."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch


MODULE_PATH = Path(__file__).with_name("ign_daily_api.py")
if str(MODULE_PATH.parent) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH.parent))


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
        "IGN_DAILY_WRITE_LOCK": str(api_dir / "write.lock"),
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

    def test_browser_login_never_returns_bearer_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            module.init_db()
            with module.db() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    ("admin", module.hash_password("correct-password"), 1),
                )
                conn.commit()
            response = types.SimpleNamespace(set_cookie=Mock())
            payload = types.SimpleNamespace(username="admin", password="correct-password")

            result = module.browser_login(payload, types.SimpleNamespace(client=None), response)

            self.assertEqual(result, {"ok": True, "user": {"username": "admin"}})
            response.set_cookie.assert_called_once()

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
            reviewed_at = "2026-07-10T10:00:00+00:00"
            translation.write_text(json.dumps({
                "url": "https://example.com/article",
                "translator": "codex",
                "translator_provider": "openai",
                "translator_model": "gpt-5.6-sol",
                "reasoning_effort": "low",
                "reviewer_model": "gpt-5.6-sol",
                "reviewed_at": reviewed_at,
                "prompt_version": "codex-fulltext-v2",
                "quality_gate_version": 1,
                "quality_review": {
                    "status": "passed",
                    "reviewer_model": "gpt-5.6-sol",
                    "reviewed_at": reviewed_at,
                    "checks": {
                        "source_coverage": True,
                        "quote_attribution": True,
                        "numeric_facts": True,
                    },
                },
                "paragraphs": [{"en": "A complete source paragraph.", "cn": "完整的译文段落。"}],
            }), encoding="utf-8")
            (repo / "data" / "2026-07-10" / "index.json").write_text(json.dumps({
                "articles": [{
                    "id": 1,
                    "url": "https://example.com/article",
                    "translation_status": "done",
                    "translation_path": "translations/01.json",
                }]
            }), encoding="utf-8")
            source = repo / "data/2026-07-10/sources/01.json"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"url": "https://example.com/article", "paragraphs_en": ["A complete source paragraph."]}))
            result = module.codex_complete_job(job_id, payload, {"username": "tester"})
            self.assertTrue(result["ok"])
            self.assertEqual(result["job"]["status"], "done")

    def test_translation_requests_are_split_into_two_article_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            day = repo / "data" / "2026-07-18"
            day.mkdir(parents=True)
            api_dir.mkdir()
            articles = [
                {"id": article_id, "url": f"https://example.com/{article_id}", "en_title": str(article_id)}
                for article_id in range(1, 6)
            ]
            (day / "index.json").write_text(json.dumps({"articles": articles}), encoding="utf-8")
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            module.init_db()
            payload = types.SimpleNamespace(date="2026-07-18", ids=[1, 2, 3, 4, 5], trigger_workflow=False)

            result = module.request_translation(payload, {"username": "tester"})

            self.assertEqual(result["job_batch_size"], 2)
            self.assertEqual(len(result["job_ids"]), 3)
            with module.db() as conn:
                rows = conn.execute("SELECT ids_json FROM jobs ORDER BY created_at, id").fetchall()
            self.assertEqual(sorted(len(json.loads(row["ids_json"])) for row in rows), [1, 2, 2])

    def test_repeated_translation_request_reuses_active_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            day = repo / "data" / "2026-07-28"
            day.mkdir(parents=True)
            api_dir.mkdir()
            (day / "index.json").write_text(json.dumps({
                "articles": [{"id": 38, "url": "https://example.com/38", "en_title": "38"}]
            }), encoding="utf-8")
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            module.init_db()
            payload = types.SimpleNamespace(date="2026-07-28", ids=[38], trigger_workflow=False)

            first = module.request_translation(payload, {"username": "tester"})
            second = module.request_translation(payload, {"username": "tester"})

            self.assertEqual(second["job_ids"], first["job_ids"])
            self.assertEqual(second["created_job_ids"], [])
            self.assertEqual(second["reused_job_ids"], first["job_ids"])
            self.assertTrue(second["deduplicated"])
            with module.db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            self.assertEqual(count, 1)

    def test_translation_request_only_creates_jobs_for_uncovered_articles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            day = repo / "data" / "2026-07-28"
            day.mkdir(parents=True)
            api_dir.mkdir()
            (day / "index.json").write_text(json.dumps({
                "articles": [
                    {"id": 37, "url": "https://example.com/37", "en_title": "37"},
                    {"id": 38, "url": "https://example.com/38", "en_title": "38"},
                ]
            }), encoding="utf-8")
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            module.init_db()
            module.request_translation(
                types.SimpleNamespace(date="2026-07-28", ids=[38], trigger_workflow=False),
                {"username": "tester"},
            )

            result = module.request_translation(
                types.SimpleNamespace(date="2026-07-28", ids=[37, 38], trigger_workflow=False),
                {"username": "tester"},
            )

            self.assertEqual(len(result["created_job_ids"]), 1)
            self.assertEqual(len(result["reused_job_ids"]), 1)
            with module.db() as conn:
                rows = conn.execute("SELECT ids_json FROM jobs ORDER BY created_at, id").fetchall()
            self.assertEqual(sorted(json.loads(row["ids_json"]) for row in rows), [[37], [38]])

    def test_public_translation_status_distinguishes_missing_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            self.assertEqual(
                module.public_translation_file_status("2026-07-18", 1)["status"],
                "missing",
            )
            translation = repo / "data" / "2026-07-18" / "translations" / "01.json"
            translation.parent.mkdir(parents=True)
            translation.write_text("{}\n", encoding="utf-8")
            if os.name != "nt":
                os.chmod(translation, 0o600)
                self.assertEqual(
                    module.public_translation_file_status("2026-07-18", 1)["status"],
                    "permission_denied",
                )
            os.chmod(translation, 0o644)
            self.assertEqual(
                module.public_translation_file_status("2026-07-18", 1)["status"],
                "available",
            )
            with self.assertRaises(FakeHTTPException) as raised:
                module.translation_file_status("../invalid", 1)
            self.assertEqual(raised.exception.status_code, 400)

    def test_reading_job_does_not_claim_queued_translation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
            module.init_db()
            job_id = module.create_job("translation", "2026-07-14", [2], "tester", "已加入翻译队列")

            job = module.serialize_job(module.load_job_row(job_id))

            self.assertEqual(job["status"], "queued")
            self.assertEqual(job["current_step"], "queued")
            self.assertEqual(job["estimate_kind"], "scheduled")
            self.assertIsNone(job["eta_seconds"])
            self.assertEqual(module.load_job_row(job_id)["status"], "queued")

    def test_translation_estimate_is_stage_stable_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})

            first = module.stable_translation_estimate("running", "model", 2)
            second = module.stable_translation_estimate("running", "model", 2)
            repair = module.stable_translation_estimate("running", "repair", 1)

            self.assertEqual(first, second)
            self.assertEqual(first["eta_min_seconds"], 16 * 60)
            self.assertEqual(first["eta_max_seconds"], 40 * 60)
            self.assertEqual(repair["estimate_kind"], "uncertain")

    def test_wechat_binding_tables_and_session_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {
                "IGN_DAILY_STORAGE_MODE": "local",
                "IGN_DAILY_ADMIN_USER": "admin",
                "IGN_DAILY_ADMIN_PASSWORD": "a-secure-test-password",
            })
            module.init_db()
            with module.db() as conn:
                tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    ("wechat-admin", module.hash_password("a-secure-test-password"), 1),
                )
                conn.commit()
                user_id = conn.execute("SELECT id FROM users WHERE username='wechat-admin'").fetchone()["id"]
            self.assertIn("wechat_bindings", tables)
            self.assertIn("wechat_bind_challenges", tables)
            token = module.issue_session(user_id)
            self.assertEqual(module.auth_from_token(token)["username"], "wechat-admin")

    def test_wechat_code_exchange_never_returns_session_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir, {
                "IGN_DAILY_WECHAT_APPID": "wx-test",
                "IGN_DAILY_WECHAT_APP_SECRET": "secret-test",
            })
            response = Mock()
            response.read.return_value = b'{"openid":"openid-1","unionid":"union-1","session_key":"private"}'
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch.object(module.urllib.request, "urlopen", return_value=response):
                identity = module.exchange_wechat_code("temporary-code")
            self.assertEqual(identity, {"openid": "openid-1", "unionid": "union-1"})

    def test_wechat_job_message_matches_configured_template_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            api_dir = root / "api"
            repo.mkdir()
            api_dir.mkdir()
            module = load_api(repo, api_dir)
            data = module.wechat_job_message_data({
                "ids": [1, 2, 3],
                "done_count": 2,
                "failed_count": 1,
                "created_at": 1_784_064_000,
                "finished_at": 1_784_067_600,
            })
            self.assertEqual(set(data), {"time1", "time2", "thing3", "thing12", "thing11"})
            self.assertEqual(data["thing3"]["value"], "IGN Daily 翻译任务")
            self.assertEqual(data["thing12"]["value"], "完成 2 篇，待复核 1 篇")
            self.assertEqual(data["thing11"]["value"], "请进入任务页查看译文")


class MobileReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo, api_dir = root / "repo", root / "api"
        self.day = self.repo / "data" / "2026-09-06"
        self.day.mkdir(parents=True)
        api_dir.mkdir()
        self.api = load_api(self.repo, api_dir, {"IGN_DAILY_STORAGE_MODE": "local"})
        self.api.init_db()
        self.user = {"username": "tester"}
        self.api.write_project_file("data/dict.json", '{}')
        self.api.write_project_file("data/2026-09-06/index.json", json.dumps({"articles": [
            {"id": i, "url": f"https://example.com/{i}"} for i in range(1, 9)
        ]}))

    def test_article_routes_reject_traversal_invalid_dates_and_nonpositive_ids(self):
        for date in ("..", "../data", "%2e%2e", "2026-02-30", "2026-13-01", "2026-9-06"):
            for route in (lambda: self.api.articles(date, self.user),
                          lambda: self.api.article(date, 1, self.user),
                          lambda: self.api.translation_file_status(date, 1)):
                with self.subTest(date=date), self.assertRaises(FakeHTTPException) as error:
                    route()
                self.assertEqual(error.exception.status_code, 400)
        for article_id in (0, -1):
            with self.assertRaises(FakeHTTPException):
                self.api.article("2026-09-06", article_id, self.user)
            with self.assertRaises(FakeHTTPException):
                self.api.request_translation(types.SimpleNamespace(
                    date="2026-09-06", ids=[article_id], trigger_workflow=None), self.user)
        self.assertEqual(self.api.validate_article_date("2024-02-29"), "2024-02-29")

    def test_expected_translation_urls_reject_renumbered_selection_without_side_effects(self):
        original = self.api.read_json(self.day / "index.json")
        original["articles"][0]["url"], original["articles"][1]["url"] = (
            original["articles"][1]["url"], original["articles"][0]["url"])
        self.api.write_project_file("data/2026-09-06/index.json", json.dumps(original))
        self.api.run_local_job = Mock()
        payload = types.SimpleNamespace(date="2026-09-06", ids=[1, 2], trigger_workflow=True,
                                        expected_urls={"1": "https://example.com/1", "2": "https://example.com/2"})
        with self.assertRaises(FakeHTTPException) as error:
            self.api.request_translation(payload, self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse((self.day / "requests.json").exists())
        with self.api.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)
        self.api.run_local_job.assert_not_called()

    def test_expected_translation_urls_accept_matching_map_and_reject_missing_identity(self):
        for ids, expected in (([1, 2], {"1": "https://example.com/1"}),
                              ([99], {"99": "https://example.com/99"}), ([1], {})):
            with self.subTest(ids=ids, expected=expected), self.assertRaises(FakeHTTPException) as error:
                self.api.request_translation(types.SimpleNamespace(
                    date="2026-09-06", ids=ids, trigger_workflow=False, expected_urls=expected), self.user)
            self.assertEqual(error.exception.status_code, 409)
        self.assertFalse((self.day / "requests.json").exists())
        result = self.api.request_translation(types.SimpleNamespace(
            date="2026-09-06", ids=[1, 2], trigger_workflow=False,
            expected_urls={"1": "https://example.com/1", "2": "https://example.com/2"}), self.user)
        self.assertEqual(result["requested_ids"], [1, 2])
        requested = self.api.read_json(self.day / "requests.json")
        self.assertEqual({item["url"] for item in requested["requested_articles"]},
                         {"https://example.com/1", "https://example.com/2"})

    def test_expected_translation_urls_reject_missing_day_as_conflict(self):
        with self.assertRaises(FakeHTTPException) as error:
            self.api.request_translation(types.SimpleNamespace(
                date="2026-09-05", ids=[1], trigger_workflow=False,
                expected_urls={"1": "https://example.com/1"}), self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertFalse((self.repo / "data/2026-09-05/requests.json").exists())

    def test_execution_defaults_follow_live_owner_and_reused_job_does_not_dispatch(self):
        self.api.run_local_job = Mock()
        for owner, expected in (("api", True), ("codex", False), ("openclaw", False)):
            self.api.write_project_file("data/automation-config.json", json.dumps({"fulltext_translator": owner}))
            self.assertEqual(self.api.resolve_translation_trigger(None), expected)
            self.assertTrue(self.api.resolve_translation_trigger(True))
            self.assertFalse(self.api.resolve_translation_trigger(False))
        self.api.write_project_file("data/automation-config.json", '{"fulltext_translator":"api"}')
        payload = types.SimpleNamespace(date="2026-09-06", ids=[1], trigger_workflow=None)
        first = self.api.request_translation(payload, self.user)
        second = self.api.request_translation(payload, self.user)
        self.assertTrue(first["triggered"])
        self.assertFalse(second["triggered"])
        self.assertEqual(first["job_ids"], second["job_ids"])
        self.api.run_local_job.assert_called_once()

    def test_concurrent_term_and_request_additions_preserve_every_update(self):
        read_json = self.api.read_json
        def slow_read(path, *args):
            value = read_json(path, *args)
            if path.name in {"dict.json", "requests.json"}:
                time.sleep(0.01)  # Expose stale snapshots if the lock starts only at write.
            return value
        self.api.read_json = slow_read
        gate = threading.Barrier(8)
        def add(i):
            gate.wait(timeout=5)
            self.api.add_dict_term(types.SimpleNamespace(
                category="terms", en=f"term{i}", cn=f"译名{i}", source="user", note=""), self.user)
            return self.api.request_translation(types.SimpleNamespace(
                date="2026-09-06", ids=[i], trigger_workflow=False), self.user)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(add, range(1, 9)))
        self.assertEqual(len(read_json(self.repo / "data/dict.json")["terms"]), 8)
        self.assertEqual(read_json(self.day / "requests.json")["requested_ids"], list(range(1, 9)))
        self.assertEqual(len({job for result in results for job in result["job_ids"]}), 8)

    def test_candidate_reads_writes_and_job_creation_hold_same_external_lock(self):
        api = self.api
        original_read, original_write = api.read_json, api.write_local_file
        original_jobs = api.create_or_reuse_translation_jobs
        def assert_external_lock():
            self.assertTrue(getattr(api._RUNTIME_LOCK_STATE, "held", False))
            if api.fcntl:
                with api.WRITE_LOCK_PATH.open("a+") as handle:
                    with self.assertRaises(BlockingIOError):
                        api.fcntl.flock(handle.fileno(), api.fcntl.LOCK_EX | api.fcntl.LOCK_NB)
        def checked_read(*args):
            assert_external_lock()
            return original_read(*args)
        def checked_write(*args):
            assert_external_lock()
            return original_write(*args)
        def checked_jobs(*args):
            assert_external_lock()
            return original_jobs(*args)
        with patch.object(api, "read_json", checked_read), patch.object(api, "write_local_file", checked_write), patch.object(api, "create_or_reuse_translation_jobs", checked_jobs):
            candidate = api.submit_dict_candidate(types.SimpleNamespace(
                category="terms", en="test", cn="测试", note=""), self.user)["candidate"]
            api.approve_dict_candidate(candidate["id"], types.SimpleNamespace(category=None, cn=None, note=None), self.user)
            api.reject_dict_candidate(candidate["id"], self.user)
            api.request_translation(types.SimpleNamespace(date="2026-09-06", ids=[1], trigger_workflow=False), self.user)

    def test_delete_checks_revision_and_unlinks_under_one_lock(self):
        path = "data/dict.json"
        target = self.repo / path
        stale = self.api.content_sha(target.read_text())
        self.api.write_project_file(path, '{"terms":{}}')
        with self.assertRaises(FakeHTTPException) as error:
            self.api.delete_project_file(path, types.SimpleNamespace(sha=stale, message="test"), self.user)
        self.assertEqual(error.exception.status_code, 409)
        self.assertTrue(target.exists())
        original_unlink = Path.unlink
        def checked_unlink(target_path, *args, **kwargs):
            self.assertTrue(getattr(self.api._RUNTIME_LOCK_STATE, "held", False))
            return original_unlink(target_path, *args, **kwargs)
        with patch.object(Path, "unlink", checked_unlink):
            self.api.delete_project_file(path, types.SimpleNamespace(
                sha=self.api.content_sha(target.read_text()), message="test"), self.user)
        self.assertFalse(target.exists())


class NativePolishTest(unittest.TestCase):
    setUp = MobileReadinessTest.setUp

    def payload(self, revision=None, **overrides):
        values = dict(url="https://example.com/1", expected_revision=revision,
                      title="润色标题", subtitle="副标题", summary="摘要", body="第一段\n\n第二段")
        values.update(overrides)
        return types.SimpleNamespace(**values)

    def test_prefill_uses_matching_translation_and_existing_indexed_draft(self):
        self.api.write_project_file("data/2026-09-06/translations/01.json", json.dumps({
            "url": "https://example.com/1", "cn_title": "译文标题", "subtitle": "译文副标题",
            "opus_summary": "译文摘要", "paragraphs": [{"en": "English", "cn": "中文段落"}, "下一段"]
        }))
        result = self.api.get_article_polish("2026-09-06", 1, self.user)
        self.assertFalse(result["exists"])
        self.assertIsNone(result["revision"])
        self.assertEqual(result["draft"], dict(title="译文标题", subtitle="译文副标题", summary="译文摘要", body="中文段落\n\n下一段"))
        saved = self.api.put_article_polish("2026-09-06", 1, self.payload(), self.user)
        self.assertEqual(self.api.get_article_polish("2026-09-06", 1, self.user), saved)

    def test_legacy_body_cn_prefill_preserves_an_explicitly_empty_saved_body(self):
        self.api.write_project_file("data/2026-09-06/translations/01.json", json.dumps({
            "url": "https://example.com/1", "cn_title": "旧格式译文", "body_cn": "旧格式正文"
        }))
        result = self.api.get_article_polish("2026-09-06", 1, self.user)
        self.assertEqual(result["draft"]["body"], "旧格式正文")
        self.api.write_project_file("data/2026-09-06/polished/01_legacy.json", json.dumps({
            "url": "https://example.com/1", "body_cn": "旧格式润色正文"
        }))
        self.api.write_project_file("data/2026-09-06/polished/_index.json", '{"1":"01_legacy.json"}')
        existing = self.api.get_article_polish("2026-09-06", 1, self.user)
        self.assertEqual(existing["draft"]["body"], "旧格式润色正文")
        saved = self.api.put_article_polish("2026-09-06", 1, self.payload(existing["revision"], body=""), self.user)
        self.assertEqual(saved["draft"]["body"], "")
        self.assertEqual(self.api.get_article_polish("2026-09-06", 1, self.user)["draft"]["body"], "")
        document = self.api.read_json(self.day / "polished/01_legacy.json")
        self.assertEqual(document["body_cn"], "旧格式润色正文")
        self.assertEqual(document["paragraphs"], [])

    def test_create_edit_preserve_metadata_and_other_index_entries(self):
        self.api.write_project_file("data/2026-09-06/polished/_index.json", '{"2":"02_other.json","_meta":{"source":"web"}}')
        first = self.api.put_article_polish("2026-09-06", 1, self.payload(), self.user)
        mapping = self.api.read_json(self.day / "polished/_index.json")
        path = self.day / "polished" / mapping["1"]
        doc = self.api.read_json(path)
        self.assertEqual(doc["paragraphs"], ["第一段", "第二段"])
        self.assertEqual(doc["url"], "https://example.com/1")
        self.assertEqual(doc["id"], 1)
        self.assertTrue(mapping["1"].startswith("01_"))
        doc["external_document_id"] = "preserve-this"
        self.api.write_project_file(str(path.relative_to(self.repo)), json.dumps(doc))
        current = self.api.get_article_polish("2026-09-06", 1, self.user)
        saved = self.api.put_article_polish("2026-09-06", 1, self.payload(current["revision"], title="", body="修改后\r\n第二行", summary="", subtitle=""), self.user)
        self.assertNotEqual(saved["revision"], first["revision"])
        self.assertEqual(saved["draft"]["title"], "")
        self.assertEqual(self.api.get_article_polish("2026-09-06", 1, self.user), saved)
        self.assertEqual(self.api.read_json(path)["external_document_id"], "preserve-this")
        self.assertEqual(self.api.read_json(path)["paragraphs"], ["修改后", "第二行"])
        updated_index = self.api.read_json(self.day / "polished/_index.json")
        self.assertEqual(updated_index["1"], mapping["1"])
        self.assertEqual(updated_index["2"], "02_other.json")
        self.assertEqual(updated_index["_meta"], {"source": "web"})

    def test_stale_revision_and_null_create_conflict_leave_draft_unchanged(self):
        first = self.api.put_article_polish("2026-09-06", 1, self.payload(), self.user)
        second = self.api.put_article_polish("2026-09-06", 1, self.payload(first["revision"], title="最新版本"), self.user)
        for revision in (None, first["revision"], "unknown"):
            with self.assertRaises(FakeHTTPException) as error:
                self.api.put_article_polish("2026-09-06", 1, self.payload(revision), self.user)
            self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.api.get_article_polish("2026-09-06", 1, self.user), second)

    def test_simultaneous_creates_have_one_winner(self):
        gate = threading.Barrier(2)
        def create(title):
            gate.wait(timeout=5)
            try:
                return self.api.put_article_polish("2026-09-06", 1, self.payload(title=title), self.user)
            except FakeHTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, ["first", "second"]))
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertIn(409, results)
        self.assertEqual(len(list((self.day / "polished").glob("01_*.json"))), 1)

    def test_url_drift_and_unrelated_indexed_document_never_overwrite_old_draft(self):
        old = {"url": "https://example.com/old", "title": "unrelated private draft"}
        self.api.write_project_file("data/2026-09-06/polished/01_untitled.json", json.dumps(old))
        self.api.write_project_file("data/2026-09-06/polished/_index.json", '{"1":"01_untitled.json"}')
        self.api.write_project_file("data/2026-09-06/translations/01.json", json.dumps(old))
        draft = self.api.get_article_polish("2026-09-06", 1, self.user)
        self.assertFalse(draft["exists"])
        self.assertNotIn("unrelated", str(draft))
        with self.assertRaises(FakeHTTPException) as error:
            self.api.put_article_polish("2026-09-06", 1, self.payload(url="https://example.com/old"), self.user)
        self.assertEqual(error.exception.status_code, 409)
        saved = self.api.put_article_polish("2026-09-06", 1, self.payload(), self.user)
        self.assertTrue(saved["exists"])
        self.assertEqual(self.api.read_json(self.day / "polished/01_untitled.json"), old)
        self.assertNotEqual(self.api.read_json(self.day / "polished/_index.json")["1"], "01_untitled.json")

    def test_unsafe_index_paths_fail_before_read_or_write(self):
        for name in ("../index.json", "../../dict.json", "/tmp/secret.json", "..\\secret.json", "_index.json", ".hidden.json"):
            self.api.write_project_file("data/2026-09-06/polished/_index.json", json.dumps({"1": name}))
            for action in (lambda: self.api.get_article_polish("2026-09-06", 1, self.user),
                           lambda: self.api.put_article_polish("2026-09-06", 1, self.payload(), self.user)):
                with self.subTest(name=name), self.assertRaises(FakeHTTPException) as error:
                    action()
                self.assertEqual(error.exception.status_code, 400)

    def test_polish_endpoints_reject_nonlocal_storage_and_invalid_identity(self):
        for date, article_id in (("2026-02-30", 1), ("2026-09-06", 0),
                                 ("../data", 1), ("%2e%2e", 1), ("2026-09-06", -1)):
            for action in (lambda: self.api.get_article_polish(date, article_id, self.user),
                           lambda: self.api.put_article_polish(date, article_id, self.payload(), self.user)):
                with self.subTest(date=date, article_id=article_id), self.assertRaises(FakeHTTPException) as error:
                    action()
                self.assertEqual(error.exception.status_code, 400)
        self.api.STORAGE_MODE = "github"
        for action in (lambda: self.api.get_article_polish("2026-09-06", 1, self.user),
                       lambda: self.api.put_article_polish("2026-09-06", 1, self.payload(), self.user)):
            with self.assertRaises(FakeHTTPException) as error:
                action()
            self.assertEqual(error.exception.status_code, 501)


if __name__ == "__main__":
    unittest.main()
