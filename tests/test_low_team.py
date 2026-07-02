import io
import unittest

from PIL import Image

from jarvis.stats.low_team import calculate_low_team_results, render_low_team_image


class LowTeamTests(unittest.TestCase):
    def test_calculation_ignores_balanced_games_and_tracks_both_sides(self):
        rows = [
            ("G1", "Small Winner 1", 1),
            ("G1", "Small Winner 2", 1),
            ("G1", "Large Loser 1", 0),
            ("G1", "Large Loser 2", 0),
            ("G1", "Large Loser 3", 0),
            ("G2", "Large Winner 1", 1),
            ("G2", "Large Winner 2", 1),
            ("G2", "Large Winner 3", 1),
            ("G2", "Small Loser 1", 0),
            ("G2", "Small Loser 2", 0),
            ("Balanced", "Ignored Winner", 1),
            ("Balanced", "Ignored Loser", 0),
        ]

        by_name = {row[0]: row for row in calculate_low_team_results(rows)}

        self.assertNotIn("Ignored Winner", by_name)
        self.assertEqual(by_name["Small Winner 1"][1:5], (1, 1, 100.0, 100.0))
        self.assertIsNone(by_name["Small Winner 1"][5])
        self.assertEqual(by_name["Small Loser 1"][1:5], (1, 1, 100.0, 0.0))
        self.assertEqual(by_name["Large Loser 1"][1:5], (0, 1, 0.0, 0.0))
        self.assertEqual(by_name["Large Loser 1"][5], 100.0)
        self.assertEqual(by_name["Large Winner 1"][5], 0.0)

    def test_name_normalisation_matches_existing_behavior(self):
        rows = [
            ("G1", "Player.Name", 1),
            ("G1", "Other", 0),
            ("G1", "Third", 0),
            ("G2", "player_name", 0),
            ("G2", "Winner", 1),
            ("G2", "Second Winner", 1),
        ]

        matching = [
            row for row in calculate_low_team_results(rows) if row[0] == "player_name"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0][2], 2)

    def test_rendered_png_is_nonempty_and_pillow_openable(self):
        buffer = render_low_team_image(
            [("Player", 2, 3, 66.7, 50.0, 25.0)],
            title="Low-Team Regression",
        )

        self.assertIsInstance(buffer, io.BytesIO)
        self.assertGreater(len(buffer.getvalue()), 0)
        with Image.open(buffer) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 0)
            self.assertGreater(image.height, 0)
            image.verify()


if __name__ == "__main__":
    unittest.main()
