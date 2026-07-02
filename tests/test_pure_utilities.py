import unittest

from jarvis.formatting import format_duration
from jarvis.naming import canonical_player_name, norm_key, norm_simple
from jarvis.rendering.fonts import BODY_PT, DEFAULT_FONT_PATH, TITLE_PT, get_fonts


class FormattingTests(unittest.TestCase):
    def test_duration_format_matches_existing_outputs(self):
        cases = {
            0: "0s",
            None: "0s",
            59: "59s",
            60: "1m 0s",
            3599: "59m 59s",
            3600: "1h 0m",
            7325: "2h 2m",
        }
        for seconds, expected in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(format_duration(seconds), expected)


class NamingTests(unittest.TestCase):
    def test_norm_key_preserves_existing_matching_rules(self):
        self.assertEqual(norm_key(" Nev.Blade_7 "), "nevblade7")
        self.assertEqual(norm_key(None), "")

    def test_norm_simple_removes_all_non_alphanumeric_characters(self):
        self.assertEqual(norm_simple(" Nev.Blade_7 "), "nevblade7")
        self.assertEqual(norm_simple(None), "")

    def test_canonical_player_aliases_are_preserved(self):
        self.assertEqual(canonical_player_name("nev pounder"), "Nev Pounder")
        self.assertEqual(canonical_player_name("Nuffman"), "Nuffmans")
        self.assertEqual(canonical_player_name("Unknown_Player"), "Unknown_Player")


class FontTests(unittest.TestCase):
    def test_visual_defaults_are_preserved(self):
        self.assertEqual(DEFAULT_FONT_PATH, "cour.ttf")
        self.assertEqual(BODY_PT, 24)
        self.assertEqual(TITLE_PT, 36)

    def test_font_loader_returns_body_and_title_fonts(self):
        body_font, title_font = get_fonts(
            font_path="font-that-does-not-exist.ttf",
            body_pt=12,
            title_pt=18,
        )
        self.assertIsNotNone(body_font)
        self.assertIsNotNone(title_font)


if __name__ == "__main__":
    unittest.main()
