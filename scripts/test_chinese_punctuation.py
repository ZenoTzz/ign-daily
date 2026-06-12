#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chinese_punctuation import disallowed_double_quotes, normalize_chinese_quotes, normalize_translation_quotes


class ChinesePunctuationTests(unittest.TestCase):
    def test_normalizes_curly_and_straight_quotes(self) -> None:
        self.assertEqual(
            normalize_chinese_quotes('\u201c心理惊悚\u201d和"内心冲突"'),
            "\u300c心理惊悚\u300d和\u300c内心冲突\u300d",
        )

    def test_normalizes_only_chinese_translation_fields(self) -> None:
        data = {
            "en_title": '"Quoted English title"',
            "cn_title": '\u201c中文标题\u201d',
            "paragraphs": [{"en": '"English"', "cn": '"中文"'}],
        }
        normalize_translation_quotes(data)
        self.assertEqual(data["en_title"], '"Quoted English title"')
        self.assertEqual(data["cn_title"], "\u300c中文标题\u300d")
        self.assertEqual(data["paragraphs"][0]["en"], '"English"')
        self.assertEqual(data["paragraphs"][0]["cn"], "\u300c中文\u300d")

    def test_reports_all_disallowed_double_quote_forms(self) -> None:
        self.assertEqual(
            disallowed_double_quotes('"\u201c\u201d\uff02'),
            ['"', "\u201c", "\u201d", "\uff02"],
        )


if __name__ == "__main__":
    unittest.main()
