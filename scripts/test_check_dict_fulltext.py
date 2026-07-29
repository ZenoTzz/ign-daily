import re
import unittest

import check_dict_fulltext as checker
import enforce_dict_titles as title_checker


class EnglishTermBoundaryTests(unittest.TestCase):
    def test_numbered_title_does_not_match_decimal_variant(self) -> None:
        pattern = checker.en_pattern("Cyberpunk: Edgerunners 2")
        self.assertIsNone(pattern.search("Cyberpunk: Edgerunners 2.5D brawler"))
        self.assertIsNotNone(pattern.search("Cyberpunk: Edgerunners 2 announced"))
        title_pattern = title_checker.en_pattern("Cyberpunk: Edgerunners 2")
        self.assertIsNone(title_pattern.search("Cyberpunk: Edgerunners 2.5D brawler"))
        self.assertIsNotNone(title_pattern.search("Cyberpunk: Edgerunners 2 announced"))

    def test_lowercase_company_name_is_treated_as_common_noun(self) -> None:
        match = re.search("rockstar", "legendary rockstar terrorist")
        assert match is not None
        self.assertTrue(
            checker.is_lowercase_common_noun_match("companies", "Rockstar", match)
        )


if __name__ == "__main__":
    unittest.main()
