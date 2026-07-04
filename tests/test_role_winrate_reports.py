import unittest

from PIL import Image

from jarvis.stats.role_winrate_reports import (
    _role_wr_build_overall_rows,
    _role_wr_build_teammate_rows,
    _role_wr_render_overall_image,
    _role_wr_render_teammate_image,
)


def match_row(match, uid, player, camp, win, **role_seconds):
    role_sec = {"Vanguard": 0.0, "Duelist": 0.0, "Strategist": 0.0}
    role_sec.update(role_seconds)
    return {
        "match_key": match,
        "player_uid": uid,
        "player": player,
        "camp": camp,
        "is_win": win,
        "total_sec": 600.0,
        "role_sec": role_sec,
    }


class RoleWinrateReportTests(unittest.TestCase):
    def test_aggregation_preserves_role_eligibility_and_teammates(self):
        rows = [
            match_row("m1", 1, "Alpha", 0, 1, Duelist=300),
            match_row("m1", 2, "Beta", 0, 1, Vanguard=300),
            match_row("m2", 1, "Alpha", 1, 0, Duelist=119),
            match_row("m2", 2, "Beta", 1, 0, Vanguard=300),
        ]
        overall = {row["player"]: row for row in _role_wr_build_overall_rows(rows)}
        self.assertEqual(overall["Alpha"]["Duelist_games"], 1)
        self.assertEqual(overall["Alpha"]["Duelist_wins"], 1)

        teammates = _role_wr_build_teammate_rows(rows, 1, "Duelist")
        self.assertEqual(teammates, [{"player_uid": 2, "player": "Beta", "wins": 1, "games": 1}])

    def test_renderers_return_readable_png_images(self):
        overall_rows = [{
            "player": "Alpha",
            "Vanguard_wins": 1,
            "Vanguard_games": 2,
            "Duelist_wins": 0,
            "Duelist_games": 0,
            "Strategist_wins": 0,
            "Strategist_games": 0,
        }]
        outputs = [
            (_role_wr_render_overall_image(8, overall_rows), (1900, 520)),
            (_role_wr_render_teammate_image(
                8, "Alpha", "Vanguard", [{"player": "Beta", "wins": 1, "games": 2}]
            ), (1450, 500)),
        ]
        for output, expected_size in outputs:
            self.assertGreater(len(output.getvalue()), 0)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, expected_size)
                image.verify()


if __name__ == "__main__":
    unittest.main()
