import unittest

from PIL import Image

from jarvis.rendering.head_to_head import _h2h_render_matchup_image


def player_pack(name, wins, losses):
    games = wins + losses
    return {
        "name": name,
        "h2h_games": games,
        "h2h_wins": wins,
        "h2h_losses": losses,
        "h2h_win_pct": (wins / games * 100.0) if games else 0.0,
        "h2h_avg_kda": 2.0,
        "h2h_avg_k": 10.0,
        "h2h_avg_d": 5.0,
        "h2h_avg_a": 8.0,
        "h2h_avg_dmg": 10000.0,
        "h2h_avg_heal": 2000.0,
        "h2h_avg_taken": 7000.0,
        "h2h_accuracy": 0.45,
        "h2h_mvp": 1,
        "h2h_svp": 0,
        "h2h_hero_pool": 4,
        "season_win_pct": 55.0,
        "low_team_pct": None,
        "low_team_on_less": 0,
        "low_team_uneven": 0,
        "vers_pct": None,
        "top_hero": "Test Hero",
        "badges": "None",
    }


class HeadToHeadRendererTests(unittest.TestCase):
    def test_opponents_report_is_nonempty_readable_png(self):
        output = _h2h_render_matchup_image(
            "HEAD TO HEAD - Test",
            player_pack("Alpha", 3, 2),
            player_pack("Beta", 2, 3),
            {
                "a_wins": 3,
                "b_wins": 2,
                "opp_games": 5,
                "duo_wins": 4,
                "duo_losses": 1,
                "duo_games": 5,
            },
        )
        self.assertGreater(len(output.getvalue()), 0)
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 1000)
            self.assertGreater(image.height, 500)
            image.verify()


if __name__ == "__main__":
    unittest.main()
