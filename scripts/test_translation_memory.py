"""Regression tests for conservative exact translation memory."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import translation_memory


def document(*entries):
    return {"_meta": {"schema_version": 1}, "entries": list(entries)}


class TranslationMemoryTest(unittest.TestCase):
    def test_normalization_only_ignores_presentation_differences(self) -> None:
        self.assertEqual(
            translation_memory.memory_key('He said “wait here.”'),
            translation_memory.memory_key('He  said  "wait here."'),
        )
        self.assertNotEqual(
            translation_memory.memory_key("Sony will reverse its decision."),
            translation_memory.memory_key("Sony will not reverse its decision."),
        )

    def test_only_approved_exact_quote_matches(self) -> None:
        approved_quote = "I sympathize with physical media fans, but Sony isn't reversing this decision."
        memory = document(
            {"kind": "quote", "en": approved_quote, "cn": "标准引语", "status": "approved"},
            {"kind": "quote", "en": "Pending quote long enough to be detected here.", "cn": "候选", "status": "candidate"},
        )
        paragraphs = [f'Toto told IGN, "{approved_quote}" The discussion continued.']
        hits = translation_memory.find_hits(paragraphs, memory)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "quote")
        self.assertEqual(hits[0]["cn"], "标准引语")

    def test_full_paragraph_is_applied_deterministically(self) -> None:
        english = "This is an entire repeated paragraph with enough context."
        memory = document({"kind": "paragraph", "en": english, "cn": "人工确认全文。", "status": "approved"})
        hits = translation_memory.find_hits([english], memory)
        data = {"paragraphs": [{"en": english, "cn": "模型的另一种译法。"}]}
        self.assertEqual(translation_memory.apply_paragraph_locks(data, hits), 1)
        self.assertEqual(data["paragraphs"][0]["cn"], "人工确认全文。")
        self.assertEqual(translation_memory.validate_locks(data, hits), [])

    def test_quote_mismatch_blocks_validation(self) -> None:
        english = "A quoted sentence that is long enough for exact matching."
        memory = document({"kind": "quote", "en": english, "cn": "必须复用的引语", "status": "approved"})
        hits = translation_memory.find_hits([f'He said, "{english}"'], memory)
        errors = translation_memory.validate_locks({"paragraphs": [{"cn": "另一种引语。"}]}, hits)
        self.assertEqual(len(errors), 1)
        self.assertIn("approved quote", errors[0])

    def test_upsert_writes_auditable_approved_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            entry = translation_memory.upsert_approved(
                "Exact English sentence.",
                "准确中文句子。",
                kind="paragraph",
                source={"date": "2026-07-14", "article_id": 1},
                path=path,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(entry["status"], "approved")
            self.assertEqual(saved["entries"][0]["approved_by"], "user")
            self.assertEqual(saved["entries"][0]["source"]["article_id"], 1)

    def test_conflicting_approved_translations_are_rejected(self) -> None:
        memory = document(
            {"kind": "paragraph", "en": "Same English.", "cn": "版本甲。", "status": "approved"},
            {"kind": "paragraph", "en": "Same English.", "cn": "版本乙。", "status": "approved"},
        )
        with self.assertRaises(ValueError):
            translation_memory.find_hits(["Same English."], memory)

    def test_invalid_existing_json_is_not_silently_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                translation_memory.load_memory(path)


if __name__ == "__main__":
    unittest.main()
