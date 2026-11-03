import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import douban_terms as d


class DoubanTermsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name) / "cache.json"
        p = patch.object(d, "CACHE_PATH", self.cache)
        p.start()
        self.addCleanup(p.stop)

    def test_person_heading(self):
        row = d.parse_candidate("Dave Bautista", "https://movie.douban.com/celebrity/1014003/", "<h1>戴夫·巴蒂斯塔 Dave Bautista</h1>")
        self.assertEqual(row["cn"], "戴夫·巴蒂斯塔")
        self.assertEqual(row["source"], "ai_guess")
        self.assertEqual(row["reference_source"], "douban")

    def test_movie_heading(self):
        row = d.parse_candidate("Guardians of the Galaxy", "https://movie.douban.com/subject/7065154/", "<h1><span>银河护卫队 Guardians of the Galaxy</span><span>(2014)</span></h1>")
        self.assertEqual(row["cn"], "银河护卫队")
        self.assertEqual(row["cat"], "movies_tv")

    def test_wrong_identity_or_biography_is_not_a_match(self):
        self.assertIsNone(d.parse_candidate("Dave Bautista", "https://movie.douban.com/celebrity/1/", "<h1>他人 Somebody Else</h1><p>Dave Bautista</p>"))

    def test_reject_untrusted_urls(self):
        for url in ("http://movie.douban.com/subject/1", "https://evil.test/subject/1", "https://movie.douban.com.evil.test/subject/1", "https://x@movie.douban.com/subject/1", "https://movie.douban.com:444/subject/1", "https://movie.douban.com/subject/1/comments"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                d.detail_url(url)

    def test_search_links_bounded_and_validated(self):
        html = '<a href="https://www.douban.com/link2/?url=https%3A%2F%2Fmovie.douban.com%2Fsubject%2F1%2F">x</a>'
        html += '<a href="https://evil.test/subject/1">x</a>'
        self.assertEqual(d.search_urls(html), ["https://movie.douban.com/subject/1/"])

    def test_failure_is_soft_and_stops_subsequent_requests(self):
        with patch.object(d, "fetch_page", side_effect=TimeoutError) as fetch:
            self.assertEqual(d.lookup("Dave Bautista"), [])
            self.assertEqual(d.lookup("Ryan Hurst"), [])
            self.assertEqual(fetch.call_count, 1)

    def test_cached_candidate_avoids_network(self):
        with patch.object(d, "fetch_page", return_value="<h1>戴夫·巴蒂斯塔 Dave Bautista</h1>") as fetch:
            url = "https://movie.douban.com/celebrity/1014003/"
            self.assertEqual(d.lookup("Dave Bautista", url=url)[0]["cn"], "戴夫·巴蒂斯塔")
            self.assertTrue(d.lookup("Dave Bautista", url=url))
            self.assertEqual(fetch.call_count, 1)

    def test_known_and_already_translated_names_are_skipped(self):
        with patch.object(d, "iter_dict_terms", return_value=[("Dave Bautista", "戴夫", "people")]):
            self.assertEqual(d.missing_names("actor Dave Bautista and Ryan Hurst", "Dave Bautista 与瑞恩"), [])

    def test_untranslated_name_is_a_candidate_not_an_approved_entry(self):
        with patch.object(d, "iter_dict_terms", return_value=[]):
            self.assertEqual(d.missing_names("actor Dave Bautista in Guardians of the Galaxy", "Dave Bautista 出演《Guardians of the Galaxy》"), ["Dave Bautista", "Guardians of the Galaxy"])

    def test_cannot_write_cache_does_not_break_translation(self):
        with patch.object(d, "atomic_json", side_effect=OSError), patch.object(d, "fetch_page") as fetch:
            self.assertEqual(d.lookup("Dave Bautista"), [])
            fetch.assert_not_called()

    def test_no_movie_context_does_not_query(self):
        with patch.dict(d.os.environ, {"IGN_DAILY_DOUBAN_LOOKUP": "1"}), patch.object(d, "lookup") as lookup:
            self.assertEqual(d.pending_for_translation("Steam Deck is available", "Steam Deck 发售"), [])
            lookup.assert_not_called()

    def test_disabled_by_default(self):
        with patch.dict(d.os.environ, {"IGN_DAILY_DOUBAN_LOOKUP": "0"}), patch.object(d, "lookup") as lookup:
            self.assertEqual(d.pending_for_translation("actor Dave Bautista", "Dave Bautista"), [])
            lookup.assert_not_called()

    def test_enabled_lookup_only_one_name(self):
        with patch.dict(d.os.environ, {"IGN_DAILY_DOUBAN_LOOKUP": "1"}), patch.object(d, "iter_dict_terms", return_value=[]), patch.object(d, "lookup", return_value=[]) as lookup:
            d.pending_for_translation("actor Dave Bautista and Ryan Hurst", "Dave Bautista Ryan Hurst")
            lookup.assert_called_once()

    def test_ambiguous_movie_is_not_selected(self):
        search = '<a href="https://movie.douban.com/subject/1/">a</a><a href="https://movie.douban.com/subject/2/">b</a>'
        with patch.object(d, "fetch_page", side_effect=[search, '<h1>甲 Example Movie (2000)</h1>', '<h1>乙 Example Movie (2020)</h1>']):
            self.assertEqual(d.lookup("Example Movie"), [])


if __name__ == "__main__":
    unittest.main()
