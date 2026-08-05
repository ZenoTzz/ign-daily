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

    def test_doctor_doom_context_does_not_trigger_game_title(self) -> None:
        source = "Dr Doom became the MCU villain. Later, Doom raised an army."
        for match in re.finditer(r"\bDoom\b", source):
            self.assertTrue(
                checker.is_known_homonym_context("games", "Doom", source, match)
            )

    def test_doom_game_context_still_triggers_game_title(self) -> None:
        source = "Doom is a landmark first-person shooter."
        match = re.search(r"\bDoom\b", source)
        assert match is not None
        self.assertFalse(
            checker.is_known_homonym_context("games", "Doom", source, match)
        )

    def test_blur_animation_studio_context_does_not_trigger_game_title(self) -> None:
        source = "The series will be written by John Orloff, with Blur again animating."
        match = re.search(r"\bBlur\b", source)
        assert match is not None
        self.assertTrue(
            checker.is_known_homonym_context("games", "Blur", source, match)
        )

    def test_blur_game_context_still_triggers_game_title(self) -> None:
        source = "Blur was released for consoles in 2010."
        match = re.search(r"\bBlur\b", source)
        assert match is not None
        self.assertFalse(
            checker.is_known_homonym_context("games", "Blur", source, match)
        )

    def test_dreams_coming_true_is_common_prose(self) -> None:
        source = "Some great things, exciting things. Dreams coming true."
        match = re.search(r"\bDreams\b", source)
        assert match is not None
        self.assertTrue(
            checker.is_known_homonym_context("games", "Dreams", source, match)
        )

    def test_dreams_game_context_still_triggers_game_title(self) -> None:
        source = "Dreams was released for PlayStation 4."
        match = re.search(r"\bDreams\b", source)
        assert match is not None
        self.assertFalse(
            checker.is_known_homonym_context("games", "Dreams", source, match)
        )


if __name__ == "__main__":
    unittest.main()
