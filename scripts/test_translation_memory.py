"""Regression tests for conservative exact translation memory."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import translation_memory
from check_translation_memory import hits_active_for_translation
from rebuild_translation_memory import align_polished, build_document


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
            self.assertTrue(saved["entries"][0]["active_from"])
            self.assertEqual(saved["entries"][0]["source"]["article_id"], 1)

    def test_polish_alignment_survives_deleted_noise(self) -> None:
        before = ["第一段译文。", "需要删除的作者简介。", "第三段译文。"]
        after = ["第一段润色稿。", "第三段润色稿。"]
        pairs = align_polished(before, after)
        self.assertEqual([(left, right) for left, right, _ in pairs], [(0, 0), (2, 1)])

    def test_conflicting_polished_versions_are_quarantined(self) -> None:
        candidates = [
            {"kind": "paragraph", "en": "Same source.", "cn": "版本甲。", "source": {"date": "2026-07-12"}},
            {"kind": "paragraph", "en": "Same source.", "cn": "版本乙。", "source": {"date": "2026-07-13"}},
        ]
        rebuilt = build_document(document(), candidates, {}, now="2026-07-14T12:00:00+08:00")
        self.assertEqual(rebuilt["entries"][0]["status"], "conflict")
        self.assertEqual(len(translation_memory.approved_entries(rebuilt)), 0)

    def test_low_confidence_polish_requires_review(self) -> None:
        candidates = [{
            "kind": "paragraph",
            "en": "A complete source paragraph that must not be partially remembered.",
            "cn": "这是一段需要人工确认的润色译文。",
            "source": {"date": "2026-07-13", "alignment_ratio": 0.61},
            "auto_approve": False,
        }]
        rebuilt = build_document(document(), candidates, {}, now="2026-07-14T12:00:00+08:00")
        self.assertEqual(rebuilt["entries"][0]["status"], "candidate")
        self.assertEqual(rebuilt["_meta"]["candidate_auto_entries"], 1)
        self.assertEqual(len(translation_memory.approved_entries(rebuilt)), 0)

    def test_new_memory_does_not_retroactively_fail_old_translation(self) -> None:
        hit = {"active_from": "2026-07-14T12:00:00+08:00"}
        old = {"translated_at": "2026-07-14T08:20:00+08:00"}
        new = {"translated_at": "2026-07-14T12:20:00+08:00"}
        self.assertEqual(hits_active_for_translation([hit], old), [])
        self.assertEqual(hits_active_for_translation([hit], new), [hit])

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
