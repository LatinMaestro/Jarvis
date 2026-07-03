import unittest

from PIL import Image

from jarvis.rendering.profile_dashboard import _render_profile_dashboard


class ProfileDashboardTests(unittest.TestCase):
    def test_renderer_returns_readable_png_at_existing_dimensions(self):
        pack = {
            "season_id": 8,
            "totals": {"games": 10, "wins": 6, "losses": 4, "win_pct": 60.0},
            "streak_txt": "2W",
            "form10": "WWLLWWLLWW",
            "snapshot_rows": [
                {"label": "Win %", "value_txt": "60.0%", "pct": 50.0},
            ],
            "role_share": {"Vanguard": 0.4, "Duelist": 0.3, "Strategist": 0.3},
            "signature_heroes": [],
            "hero_names": {},
            "best_role": None,
            "teammate_hero_win": [],
            "teammate_hero_risk": [],
            "chemistry": {
                "eligible_games": 10,
                "baseline": 60.0,
                "best": [],
                "worst": [],
                "underused": None,
            },
            "momentum": {"games": 0},
            "enemy_bans": {"games": 0, "top": []},
        }

        output = _render_profile_dashboard("Test Player", pack)
        self.assertGreater(len(output.getvalue()), 0)
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (2000, 1300))
            image.verify()


if __name__ == "__main__":
    unittest.main()
