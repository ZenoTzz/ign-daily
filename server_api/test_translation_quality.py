from __future__ import annotations

import unittest

from server_api.translation_quality import validate_translation_quality


def valid_translation() -> dict:
    reviewed_at = "2026-07-17T10:00:00+00:00"
    return {
        "translator": "codex",
        "translator_provider": "openai",
        "translator_model": "gpt-5.6-sol",
        "reasoning_effort": "low",
        "reviewer_model": "gpt-5.6-sol",
        "reviewed_at": reviewed_at,
        "prompt_version": "codex-fulltext-v2",
        "quality_gate_version": 1,
        "quality_review": {
            "status": "passed",
            "reviewer_model": "gpt-5.6-sol",
            "reviewed_at": reviewed_at,
            "checks": {
                "source_coverage": True,
                "quote_attribution": True,
                "numeric_facts": True,
            },
        },
        "paragraphs": [
            {
                "en": 'Toto told IGN, "Sony expected the reaction." Revenue rose 14.5% in 2026.',
                "cn": "Toto告诉IGN：「索尼预料到了这种反应。」2026年收入增长14.5%。",
            }
        ],
    }


class TranslationQualityTest(unittest.TestCase):
    def test_valid_review_passes(self) -> None:
        self.assertEqual(validate_translation_quality(valid_translation()), [])

    def test_missing_metadata_and_review_are_blocking(self) -> None:
        errors = validate_translation_quality({"paragraphs": []})
        self.assertIn("missing metadata: translator_model", errors)
        self.assertIn("missing quality_review", errors)

    def test_numeric_omission_is_blocking(self) -> None:
        data = valid_translation()
        data["paragraphs"][0]["cn"] = "Toto告诉IGN：「索尼预料到了这种反应。」"
        errors = validate_translation_quality(data)
        self.assertTrue(any("14.5%" in error for error in errors))

    def test_unmarked_direct_quote_is_blocking(self) -> None:
        data = valid_translation()
        data["paragraphs"][0]["cn"] = "Toto告诉IGN，索尼预料到了这种反应。2026年收入增长14.5%。"
        errors = validate_translation_quality(data)
        self.assertTrue(any("quote marks" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
