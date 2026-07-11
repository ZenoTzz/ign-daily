#!/usr/bin/env python3
import unittest

from learning_quality import align_paragraphs, candidate_quality, promotion_status


class LearningQualityTests(unittest.TestCase):
    def test_insert_does_not_shift_following_paragraphs(self):
        changes = align_paragraphs(["甲", "乙", "丙"], ["甲", "新增", "乙", "丙"])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["operation"], "insert")
        self.assertEqual(changes[0]["after"], ["新增"])

    def test_rejects_headline_fragment(self):
        result = candidate_quality(
            "Ahead of Sony's State of Play Showcase, New Data",
            "羊蹄山之魂",
            source_text="Ahead of Sony's State of Play Showcase, New Data suggests...",
            origin="headline_pair",
        )
        self.assertFalse(result["accepted_as_evidence"])
        self.assertIn("headline_fragment", result["reasons"])

    def test_rejects_identity_mapping(self):
        self.assertFalse(candidate_quality("Ariel Lawrence", "Ariel Lawrence")["accepted_as_evidence"])

    def test_never_promotes_without_semantic_review(self):
        self.assertEqual(promotion_status(days_seen=9, articles_seen=20), "observed")
        self.assertEqual(
            promotion_status(days_seen=2, articles_seen=3, semantic_review="approved"),
            "ready_for_review",
        )


if __name__ == "__main__":
    unittest.main()
