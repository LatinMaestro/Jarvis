import io
import sqlite3
import unittest

from PIL import Image

from jarvis.stats.team_size_records import (
    aggregate_records,
    eligible_exact_2v2_labels,
    eligible_min_4v4_labels,
    render_records_image,
)


class TeamSizeRecordTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute(
            """
            CREATE TABLE mr_player_match (
                season_id INTEGER,
                game_label TEXT,
                match_uid TEXT,
                camp INTEGER,
                player_uid INTEGER,
                player TEXT,
                is_bot INTEGER,
                is_win INTEGER
            )
            """
        )
        self._add_game("G2", 2, 2)
        self._add_game("G3", 3, 3)
        self._add_game("G4", 4, 4)
        self.cursor.execute(
            "INSERT INTO mr_player_match VALUES (1, 'G2', 'm-G2', 1, 999, 'Bot', 1, 1)"
        )
        self.connection.commit()

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def _add_game(self, label, first_team_size, second_team_size):
        uid = 1
        for camp, size, won in ((1, first_team_size, 1), (2, second_team_size, 0)):
            for _ in range(size):
                self.cursor.execute(
                    "INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                    (1, label, f"m-{label}", camp, uid, f"Player {uid}", won),
                )
                uid += 1

    def test_exact_2v2_ignores_bots_and_rejects_larger_games(self):
        self.assertEqual(eligible_exact_2v2_labels(self.cursor, 1), ["G2"])

    def test_minimum_4v4_requires_four_humans_on_each_team(self):
        self.assertEqual(eligible_min_4v4_labels(self.cursor, 1), ["G4"])

    def test_aggregation_counts_humans_only_and_preserves_columns(self):
        frame = aggregate_records(self.cursor, 1, ["G2"])

        self.assertEqual(
            list(frame.columns),
            ["player_uid", "player", "games", "wins", "losses", "wl_str", "winrate"],
        )
        self.assertEqual(len(frame), 4)
        self.assertNotIn("Bot", set(frame["player"]))
        self.assertEqual(set(frame["games"]), {1})
        self.assertEqual(set(frame["winrate"]), {0.0, 100.0})

    def test_rendered_png_is_nonempty_and_pillow_openable(self):
        buffer = render_records_image(
            [("Player 1", 3, 2, 1, 66.7)],
            title="Regression Records",
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
