import sqlite3
import unittest

from jarvis.stats.hero_time import get_hero_time_by_player


class HeroTimeTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute(
            "CREATE TABLE hero_time_stats (season_id INTEGER, player TEXT, hero_id INTEGER, seconds INTEGER)"
        )
        self.cursor.executemany(
            "INSERT INTO hero_time_stats VALUES (?, ?, ?, ?)",
            [(7, "Alpha", 1, 60), (7, "Alpha", 1, 40), (7, "Alpha", 2, 50), (7, "Beta", 3, 90), (6, "Alpha", 9, 999)],
        )

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def test_groups_and_sums_by_player_and_hero(self):
        self.assertEqual(
            get_hero_time_by_player(self.cursor, 7),
            {"Alpha": [("1", 100), ("2", 50)], "Beta": [("3", 90)]},
        )

    def test_optional_player_filter_is_exact(self):
        self.assertEqual(
            get_hero_time_by_player(self.cursor, 7, "Alpha"),
            {"Alpha": [("1", 100), ("2", 50)]},
        )
        self.assertEqual(get_hero_time_by_player(self.cursor, 7, "Missing"), {})


if __name__ == "__main__":
    unittest.main()
