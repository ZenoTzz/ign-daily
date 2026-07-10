"""Tests for the GitHub PAT transport used by git_push.py."""
from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

import git_push


class GitPushAuthTest(unittest.TestCase):
    def test_token_is_passed_only_in_environment_config(self) -> None:
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "2"}, clear=True):
            env = git_push.git_auth_env("secret-token", "ZenoTzz")
        self.assertEqual(env["GIT_CONFIG_COUNT"], "3")
        self.assertEqual(env["GIT_CONFIG_KEY_2"], "http.extraHeader")
        expected = base64.b64encode(b"ZenoTzz:secret-token").decode("ascii")
        self.assertEqual(env["GIT_CONFIG_VALUE_2"], f"AUTHORIZATION: Basic {expected}")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")


if __name__ == "__main__":
    unittest.main()
