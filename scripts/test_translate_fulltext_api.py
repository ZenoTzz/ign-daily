#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import unittest
import copy
import json
import tempfile
import runpy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

from translate_fulltext_api import authoritative_source_paragraphs  # noqa: E402
import translate_fulltext_api as fulltext
from api_translation_prompt import fulltext_user_payload, translation_system_prompt
from translation_quality import validate_translation_quality
from dict_matcher import matched_terms_for_article


class AuthoritativeSourceParagraphTests(unittest.TestCase):
    def test_faithful_prompt_has_no_style_profile_summary_or_self_check(self):
        payload = fulltext_user_payload(article={"id": 1, "en_title": "Example", "summary": "Old summary"}, paragraphs=["First.", "Second."], terms={"Sony": "索尼"})
        self.assertEqual(payload["paragraphs_en"], ["First.", "Second."])
        self.assertEqual(payload["matched_dictionary_terms"], {"Sony": "索尼"})
        self.assertNotIn("style_profile", payload)
        self.assertNotIn("style_self_check", json.dumps(payload))
        self.assertNotIn("opus_summary", payload["task"]["required_json_schema"])
        self.assertNotIn("subtitle", payload["task"]["required_json_schema"])
        self.assertLess(len(translation_system_prompt()), 1000)

    def test_confirmed_matches_are_not_limited_to_sixty(self):
        entries = {f"Game{i}": {"cn": f"游戏{i}", "source": "user"} for i in range(75)}
        entries["Unknown"] = {"cn": "猜测译名", "source": "ai_guess"}
        rows = [(en, item["cn"], "games") for en, item in entries.items()]
        with patch("dict_matcher.load_json", return_value={"games": entries}), patch("dict_matcher.iter_dict_terms", return_value=rows):
            hits = matched_terms_for_article(" ".join(entries), limit=None, confirmed_only=True)
        self.assertEqual(len(hits), 75)
        self.assertNotIn("Unknown", hits)

    def test_paragraph_loss_or_changed_english_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            fulltext.normalize_paragraphs({"paragraphs": [{"en": "Wrong", "cn": "错误"}]}, ["First"])
        with self.assertRaises(ValueError):
            fulltext.normalize_paragraphs({"paragraphs": [{"cn": "第一"}]}, ["First", "Second"])

    def test_normalization_does_not_invent_subtitle_or_currency_conversion(self):
        article = {"id": 1, "url": "https://example.test/a", "en_title": "A"}
        data = fulltext.normalize_translation(article, {"cn_title": "标题", "paragraphs": [{"cn": "PS5游戏售价80美元，仅支持XBOX Series S。"}]}, ["The game costs $80 on Xbox Series S."])
        self.assertEqual(data["subtitle"], "")
        self.assertEqual(data["opus_summary"], "")
        self.assertIn("80美元", data["paragraphs"][0]["cn"])
        self.assertNotIn("人民币", data["paragraphs"][0]["cn"])
        self.assertIn("XBOX Series S", data["paragraphs"][0]["cn"])

    def test_one_generation_is_saved_for_human_review_without_api_repair(self, invalid_json=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = root / "2026-11-03"
            (day / "sources").mkdir(parents=True)
            article = {"id": 1, "url": "https://example.test/a", "en_title": "Sony announced 50 games.", "translation_status": "requested"}
            source = {"url": article["url"], "paragraphs_en": [article["en_title"]]}
            (day / "sources/01.json").write_text(json.dumps(source))
            (day / "index.json").write_text(json.dumps({"articles": [article]}))
            (day / "requests.json").write_text(json.dumps({"requested_ids": [1], "requested_articles": [article]}))
            result = {"cn_title": "索尼公布50款游戏", "paragraphs": [{"en": article["en_title"], "cn": "索尼公布了50款游戏。"}]}
            with patch.dict(os.environ, {"IGN_DAILY_WRITE_LOCK": str(root / "write.lock"), "TRANSLATOR_MODEL": "gpt-6.1-terra"}), patch.object(fulltext, "DATA_DIR", root), patch.object(fulltext, "load_env_file"), patch.object(fulltext, "resolve_api_key", return_value="test"), patch.object(fulltext, "ensure_cached_source", return_value=(copy.deepcopy(article), source)), patch.object(fulltext, "load_cached_source", return_value=source), patch.object(fulltext, "matched_terms", return_value={"Sony": "索尼"}), patch.object(fulltext, "enforce_translation_memory", return_value=[]), patch.object(fulltext, "set_article_step"), patch.object(fulltext, "record_deepseek_usage_safe"), patch.object(fulltext.subprocess, "run"), patch.object(fulltext, "call_deepseek_response", return_value=("not JSON" if invalid_json else json.dumps(result), {})) as model, patch.object(fulltext, "repair_translation_once") as repair, patch.object(fulltext, "translate_paragraph_chunks") as chunks, patch.object(fulltext, "save_manual_review_failure", return_value={}) as failure:
                self.assertEqual(fulltext.translate_date(day.name), 0 if invalid_json else 1)
                self.assertEqual(model.call_count, 1)
                repair.assert_not_called()
                chunks.assert_not_called()
                if invalid_json:
                    failure.assert_called_once()
                    return
            saved = json.loads((day / "translations/01.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["quality_review"]["status"], "pending")
            self.assertEqual(validate_translation_quality(saved), [])
            self.assertNotIn("reviewer_model", saved)
            self.assertEqual(json.loads((day / "requests.json").read_text())["requested_ids"], [])

    def test_invalid_json_does_not_trigger_paid_repair_or_chunk_retranslation(self):
        self.test_one_generation_is_saved_for_human_review_without_api_repair(invalid_json=True)

    def test_release_format_check_accepts_faithful_document_without_creative_subtitle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = root / "2026-11-03"
            (day / "translations").mkdir(parents=True)
            (day / "index.json").write_text(json.dumps({"articles": [{"id": 1, "translation_status": "done", "cn_title": "标题"}]}), encoding="utf-8")
            (day / "translations/01.json").write_text(json.dumps({"translator": "api", "translation_mode": "faithful", "cn_title": "标题", "subtitle": "", "opus_summary": "", "paragraphs": [{"en": "The game costs $80.", "cn": "游戏售价80美元。"}]}), encoding="utf-8")
            with patch("common_paths.DATA_DIR", root), patch.object(sys, "argv", ["post_translate_check.py", day.name]):
                with self.assertRaises(SystemExit) as result:
                    runpy.run_path(str(fulltext.REPO_ROOT / "scripts/post_translate_check.py"), run_name="__main__")
            self.assertEqual(result.exception.code, 0)

    def test_native_document_roundtrip_keeps_body_when_subtitle_is_empty(self):
        from import_tencent_polish import parse_document_articles
        articles = parse_document_articles("26/11/03 标题\n\n正文第一段。\n正文第二段。\n", preserve_empty_subtitle=True)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].subtitle, "")
        self.assertEqual(articles[0].paragraphs, ["正文第一段。", "正文第二段。"])
        historical = parse_document_articles("26/11/03 旧稿\n\n旧副标题\n正文。\n", preserve_empty_subtitle={("2026-11-03", "另一篇新稿")})
        self.assertEqual(historical[0].subtitle, "旧副标题")
        self.assertEqual(historical[0].paragraphs, ["正文。"])

    def test_uses_same_non_body_filter_as_release_gate(self):
        body = "Sony confirmed the lineup."
        byline = "Tom Phillips is IGN's News Editor. You can reach Tom on Bluesky."
        source = {"paragraphs_en": [body, byline]}
        self.assertEqual(authoritative_source_paragraphs(source), [body])

    def test_preserves_exact_source_anchors(self):
        paragraphs = ["First paragraph.", "Second paragraph with 40,000 players."]
        self.assertEqual(
            authoritative_source_paragraphs({"paragraphs_en": paragraphs}),
            paragraphs,
        )


if __name__ == "__main__":
    unittest.main()
