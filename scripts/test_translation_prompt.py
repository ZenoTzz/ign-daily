#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompt_blocks import (
    FULLTEXT_QUALITY_EXAMPLE,
    FULLTEXT_SEMANTIC_INSTRUCTIONS,
    fulltext_user_payload,
    translation_system_prompt,
)
from api_translation_audit import check_translation


class TranslationPromptTests(unittest.TestCase):
    def test_semantic_rules_are_in_fulltext_task(self) -> None:
        payload = fulltext_user_payload(
            article={"id": 1, "en_title": "Example"},
            paragraphs=["Example paragraph."],
            terms={},
        )
        instructions = payload["task"]["instructions"]
        for rule in FULLTEXT_SEMANTIC_INSTRUCTIONS:
            self.assertIn(rule, instructions)

    def test_gen_atlas_regression_example_is_stable_prefix(self) -> None:
        prompt = translation_system_prompt()
        self.assertIn(FULLTEXT_QUALITY_EXAMPLE["source"], prompt)
        self.assertIn("玩家不仅能操控人类主角", prompt)
        self.assertIn("迄今为止的作品都未提供过这种玩法", prompt)
        self.assertNotIn("多年来", FULLTEXT_QUALITY_EXAMPLE["preferred_translation"])

    def test_quality_contract_rejects_literal_translation_strategy(self) -> None:
        joined = "\n".join(FULLTEXT_SEMANTIC_INSTRUCTIONS)
        self.assertIn("禁止逐词映射", joined)
        self.assertIn("明确谁同时执行什么动作", joined)
        self.assertIn("不得增删事实", joined)
        self.assertIn("禁止意译、扩写", joined)
        self.assertIn("采用最小推断", joined)
        self.assertIn("按中文新闻稿重组表达", joined)
        self.assertIn("若读起来像机翻腔", joined)
        self.assertNotIn("直译优先", translation_system_prompt())

    def test_audit_catches_known_gen_atlas_calques(self) -> None:
        issues = check_translation(
            article={"id": 18, "en_title": "Gen Atlas"},
            paragraphs_en=["What exactly will we be doing with the robots?"],
            data={
                "opus_summary": "这是一段用于测试的中文摘要，长度并不重要，因为这里只检查已知机翻句式。",
                "paragraphs": [{
                    "cn": (
                        "我们究竟要与这些机器人做什么仍是个谜。"
                        "这是一项很受玩家期待的选项，而且巨型同伴自身和人类主角都可以操控。"
                    ),
                }],
            },
            required_terms={},
        )
        style_issues = [item for item in issues if item.get("type") == "translation_style_calque"]
        self.assertEqual(len(style_issues), 3)


if __name__ == "__main__":
    unittest.main()
