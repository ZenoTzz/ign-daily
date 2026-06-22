#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from platform_names import normalize_platform_names_in_translation, normalize_platform_text


class PlatformNameTests(unittest.TestCase):
    def test_normalizes_xbox_brand_spelling(self) -> None:
        self.assertEqual(normalize_platform_text("Xbox宣布登陆Xbox Series"), "XBOX宣布登陆XBOX Series")
        self.assertEqual(normalize_platform_text("xbox Game Pass"), "XBOX Game Pass")
        self.assertEqual(normalize_platform_text("XBOX One"), "XBOX One")

    def test_only_normalizes_chinese_facing_translation_fields(self) -> None:
        data = {
            "en_title": "Xbox Announces New Xbox Game",
            "url": "https://example.com/xbox-news",
            "cn_title": "Xbox新作公布",
            "summary": "Xbox Game Pass将加入新游戏。",
            "paragraphs": [
                {"en": "Xbox news", "cn": "Xbox Series版确认。"},
            ],
            "translated_terms": {"Xbox Game Pass": "Xbox Game Pass"},
        }

        normalize_platform_names_in_translation(data)

        self.assertEqual(data["en_title"], "Xbox Announces New Xbox Game")
        self.assertEqual(data["url"], "https://example.com/xbox-news")
        self.assertEqual(data["cn_title"], "XBOX新作公布")
        self.assertEqual(data["summary"], "XBOX Game Pass将加入新游戏。")
        self.assertEqual(data["paragraphs"][0]["en"], "Xbox news")
        self.assertEqual(data["paragraphs"][0]["cn"], "XBOX Series版确认。")
        self.assertEqual(data["translated_terms"]["Xbox Game Pass"], "XBOX Game Pass")


if __name__ == "__main__":
    unittest.main()
