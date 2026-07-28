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

    def test_translation_submit_has_double_click_guard_and_busy_state(self) -> None:
        app_js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("this.selected.length === 0 || this.translationSubmitting", app_js)
        self.assertIn("finally {\n        this.translationSubmitting = false;", app_js)
        self.assertIn("正在提交…", index_html)
        self.assertIn(":disabled=\"selected.length === 0 || translationSubmitting\"", index_html)


if __name__ == "__main__":
    unittest.main()
