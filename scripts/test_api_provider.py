#!/usr/bin/env python3
"""Offline regression tests for provider selection and request payloads."""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from api_provider import chat_completions_endpoint, normalize_reasoning_effort, resolve_api_key  # noqa: E402
from translate_titles_deepseek import call_deepseek_response  # noqa: E402


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }).encode("utf-8")


@contextmanager
def _env(**values):
    old = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class ApiProviderTests(unittest.TestCase):
    def test_endpoint_normalization(self):
        self.assertEqual(
            chat_completions_endpoint("https://api.apikey.fun/v1"),
            "https://api.apikey.fun/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_endpoint("https://api.apikey.fun/v1/"),
            "https://api.apikey.fun/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_endpoint("https://api.apikey.fun/v1/chat/completions"),
            "https://api.apikey.fun/v1/chat/completions",
        )

    def test_exact_reasoning_efforts_keep_xhigh(self):
        for effort in ("none", "low", "medium", "high", "xhigh", "max"):
            self.assertEqual(normalize_reasoning_effort(effort), effort)
        self.assertEqual(normalize_reasoning_effort("disabled"), "none")
        self.assertIsNone(normalize_reasoning_effort("thinking"))

    def test_generic_relay_does_not_reuse_another_provider_key(self):
        with _env(TRANSLATOR_API_KEY=None, DEEPSEEK_API_KEY="deepseek-secret", GEMINI_API_KEY="gemini-secret"):
            self.assertEqual(resolve_api_key("https://api.apikey.fun/v1"), "")

    def test_gpt56_payload_uses_standard_fields(self):
        captured = {}

        def fake_request(url, data=None, **kwargs):
            request = url
            captured.update(
                url=request.full_url,
                payload=json.loads(request.data),
                kwargs=kwargs,
            )
            return _Response()

        with _env(
            TRANSLATOR_REASONING_EFFORT="xhigh",
            TRANSLATOR_THINKING_MODE=None,
            TRANSLATOR_API_TIMEOUT_SECONDS="900",
        ):
            with patch("translate_titles_deepseek.urllib.request.urlopen", side_effect=fake_request):
                call_deepseek_response(
                    "test-key",
                    "gpt-5.6-luna",
                    "https://api.apikey.fun/v1",
                    [{"role": "user", "content": "{}"}],
                    max_tokens=321,
                )
        payload = captured["payload"]
        self.assertEqual(captured["url"], "https://api.apikey.fun/v1/chat/completions")
        self.assertEqual(payload["max_completion_tokens"], 321)
        self.assertEqual(payload["reasoning_effort"], "xhigh")
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("thinking", payload)
        self.assertEqual(captured["kwargs"]["timeout"], 900)

    def test_deepseek_payload_unchanged_shape(self):
        captured = {}

        def fake_request(url, data=None, **kwargs):
            request = url
            captured.update(url=request.full_url, payload=json.loads(request.data))
            return _Response()

        with _env(TRANSLATOR_THINKING_MODE="high", TRANSLATOR_REASONING_EFFORT=None):
            with patch("translate_titles_deepseek.urllib.request.urlopen", side_effect=fake_request):
                call_deepseek_response(
                    "test-key",
                    "deepseek-v4-flash",
                    "https://api.deepseek.com",
                    [{"role": "user", "content": "{}"}],
                    max_tokens=321,
                )
        payload = captured["payload"]
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(payload["max_tokens"], 321)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "high")

    def test_transient_gateway_error_is_retried(self):
        error = urllib.error.HTTPError(
            "https://api.apikey.fun/v1/chat/completions",
            502,
            "Bad Gateway",
            {},
            None,
        )
        with _env(TRANSLATOR_API_MAX_ATTEMPTS="3"):
            with patch(
                "translate_titles_deepseek.urllib.request.urlopen",
                side_effect=[error, _Response()],
            ) as mocked, patch("translate_titles_deepseek.time.sleep") as sleep:
                result, _usage = call_deepseek_response(
                    "test-key",
                    "gpt-5.6-luna",
                    "https://api.apikey.fun/v1",
                    [{"role": "user", "content": "{}"}],
                )
        self.assertEqual(result, "{}")
        self.assertEqual(mocked.call_count, 2)
        sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
