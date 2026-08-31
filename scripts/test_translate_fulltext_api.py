#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from translate_fulltext_api import authoritative_source_paragraphs  # noqa: E402


class AuthoritativeSourceParagraphTests(unittest.TestCase):
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
