import sqlite3
import unittest

from jarvis.stats.hero_bans import get_top_hero_bans


class HeroBanTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute(
            "CREATE TABLE hero_bans (season_id INTEGER, hero_id INTEGER)"
        )
        self.cursor.executemany(
            "INSERT INTO hero_bans VALUES (?, ?)",
            [
                (7, 101),
                (7, 101),
                (7, 101),
                (7, 202),
                (7, 202),
                (7, 303),
                (6, 999),
                (6, 999),
                (6, 999),
                (6, 999),
            ],
        )

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def test_counts_only_requested_season_in_descending_order(self):
        self.assertEqual(
            get_top_hero_bans(self.cursor, 7),
            [(101, 3), (202, 2), (303, 1)],
        )

    def test_limit_is_applied(self):
        self.assertEqual(get_top_hero_bans(self.cursor, 7, limit=2), [(101, 3), (202, 2)])

    def test_missing_season_returns_empty_list(self):
        self.assertEqual(get_top_hero_bans(self.cursor, 8), [])


if __name__ == "__main__":
    unittest.main()
