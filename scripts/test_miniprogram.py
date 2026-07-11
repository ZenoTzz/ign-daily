#!/usr/bin/env python3
"""Fast structural checks for the native WeChat mini program."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "miniprogram"


class MiniProgramStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = json.loads((ROOT / "app.json").read_text(encoding="utf-8"))

    def test_every_page_has_four_native_files(self) -> None:
        for page in self.app["pages"]:
            for suffix in (".js", ".json", ".wxml", ".wxss"):
                self.assertTrue((ROOT / f"{page}{suffix}").exists(), f"missing {page}{suffix}")

    def test_tab_pages_are_registered(self) -> None:
        pages = set(self.app["pages"])
        for item in self.app["tabBar"]["list"]:
            self.assertIn(item["pagePath"], pages)

    def test_wxml_tags_are_balanced(self) -> None:
        pattern = re.compile(r"<(/?)([A-Za-z][\w-]*)(?:\s[^<>]*?)?(/?)>")
        for path in ROOT.rglob("*.wxml"):
            stack: list[str] = []
            for closing, name, self_closing in pattern.findall(path.read_text(encoding="utf-8")):
                if self_closing:
                    continue
                if closing:
                    self.assertTrue(stack and stack[-1] == name, f"{path}: unexpected </{name}>")
                    stack.pop()
                else:
                    stack.append(name)
            self.assertEqual(stack, [], f"{path}: unclosed tags")

    def test_login_uses_switch_tab_for_tab_page(self) -> None:
        login_js = (ROOT / "pages/login/login.js").read_text(encoding="utf-8")
        self.assertNotIn("redirectTo({ url: '/pages/index/index'", login_js)


if __name__ == "__main__":
    unittest.main()
