from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendAuthContractTest(unittest.TestCase):
    def test_browser_actions_do_not_require_legacy_readable_token(self) -> None:
        app_js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn(
            "ServerAPI.token()",
            app_js,
            "Browser authentication uses an HttpOnly cookie; checking the old readable token blocks valid sessions.",
        )


if __name__ == "__main__":
    unittest.main()
