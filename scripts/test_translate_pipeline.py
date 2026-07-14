"""Regression tests for the translation post-processing safety boundary."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import translate_pipeline


class PostPipelineTest(unittest.TestCase):
    def test_invalid_translation_does_not_mark_index_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = root / "data" / "2026-07-10"
            translations = day / "translations"
            translations.mkdir(parents=True)
            translation_path = translations / "01.json"
            index_path = day / "index.json"
            index_list_path = root / "data" / "index-list.json"
            translation = {
                "id": 1,
                "url": "https://www.ign.com/articles/example",
                "en_title": "Example",
                "cn_title": "示例",
                "cover": "https://images.example/cover.jpg",
                "images": [{"url": "https://images.example/cover.jpg", "caption": ""}],
                "translated_terms": {"Example": "示例"},
                "subtitle": "",
                "opus_summary": "这是一段足够长的中文摘要。" * 8,
                "paragraphs": [{"en": "Example paragraph.", "cn": "示例段落。"}],
            }
            index = {
                "date": "2026-07-10",
                "articles": [{
                    "id": 1,
                    "url": translation["url"],
                    "en_title": "Example",
                    "translation_status": "requested",
                }],
            }
            index_list = [{"date": "2026-07-10", "total": 1, "translated": 0}]
            translation_path.write_text(json.dumps(translation, ensure_ascii=False, indent=2), encoding="utf-8")
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
            index_list_path.write_text(json.dumps(index_list, ensure_ascii=False, indent=2), encoding="utf-8")
            before_translation = translation_path.read_text(encoding="utf-8")
            before_index = index_path.read_text(encoding="utf-8")
            before_index_list = index_list_path.read_text(encoding="utf-8")

            original_root = translate_pipeline.IGN_DAILY
            translate_pipeline.IGN_DAILY = root
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = translate_pipeline.post_mode("2026-07-10", "1")
            finally:
                translate_pipeline.IGN_DAILY = original_root

            self.assertFalse(result)
            self.assertEqual(translation_path.read_text(encoding="utf-8"), before_translation)
            self.assertEqual(index_path.read_text(encoding="utf-8"), before_index)
            self.assertEqual(index_list_path.read_text(encoding="utf-8"), before_index_list)

    def test_approved_exact_paragraph_is_reused_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = root / "data" / "2026-07-10"
            translations = day / "translations"
            sources = day / "sources"
            translations.mkdir(parents=True)
            sources.mkdir(parents=True)
            english = "This exact paragraph is repeated in another IGN article."
            source_url = "https://www.ign.com/articles/repeated"
            (sources / "01.json").write_text(json.dumps({
                "url": source_url,
                "paragraphs_en": [english],
            }), encoding="utf-8")
            (translations / "01.json").write_text(json.dumps({
                "id": 1,
                "url": source_url,
                "en_title": "Repeated",
                "cn_title": "重复报道",
                "cover": "https://images.example/cover.jpg",
                "images": [{"url": "https://images.example/cover.jpg", "caption": ""}],
                "translated_terms": {"IGN": "IGN"},
                "subtitle": "再次引用",
                "opus_summary": "这是一段符合允许长度范围的文章摘要，用来验证经过人工确认的相同英文段落会在正式发布之前自动复用标准中文译文，并保持跨文章表达完全一致。",
                "paragraphs": [{"en": english, "cn": "模型给出的不同译文。"}],
            }, ensure_ascii=False), encoding="utf-8")
            (day / "index.json").write_text(json.dumps({
                "date": "2026-07-10",
                "articles": [{"id": 1, "url": source_url, "en_title": "Repeated", "translation_status": "requested"}],
            }), encoding="utf-8")
            (root / "data" / "index-list.json").write_text("[]", encoding="utf-8")
            (root / "data" / "translation-memory.json").write_text(json.dumps({
                "_meta": {"schema_version": 1},
                "entries": [{
                    "kind": "paragraph",
                    "en": english,
                    "cn": "人工确认的标准译文。",
                    "status": "approved",
                }],
            }, ensure_ascii=False), encoding="utf-8")

            original_root = translate_pipeline.IGN_DAILY
            translate_pipeline.IGN_DAILY = root
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = translate_pipeline.post_mode("2026-07-10", "1")
            finally:
                translate_pipeline.IGN_DAILY = original_root

            self.assertTrue(result)
            saved = json.loads((translations / "01.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["paragraphs"][0]["cn"], "人工确认的标准译文。")
            self.assertEqual(saved["translation_memory"]["locked"][0]["kind"], "paragraph")


if __name__ == "__main__":
    unittest.main()
