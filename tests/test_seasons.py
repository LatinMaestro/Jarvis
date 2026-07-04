import sqlite3
import unittest

from jarvis.stats.seasons import season_date_range, season_game_count


class SeasonSummaryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE match_imports (season_id INTEGER, game_label TEXT)")
        self.cursor.execute("CREATE TABLE game_stats (season_id INTEGER, game_label TEXT, timestamp TEXT)")
        self.cursor.execute("CREATE TABLE mr_match_meta (season_id INTEGER, imported_at TEXT)")

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def test_api_game_count_is_preferred(self):
        self.cursor.executemany("INSERT INTO match_imports VALUES (7, ?)", [("A",), ("B",), ("B",)])
        self.cursor.executemany("INSERT INTO game_stats VALUES (7, ?, '2026-01-01')", [("A",), ("B",), ("C",)])
        self.assertEqual(season_game_count(self.cursor, 7), 2)

    def test_legacy_count_is_fallback(self):
        self.cursor.executemany("INSERT INTO game_stats VALUES (7, ?, '2026-01-01')", [("A",), ("B",)])
        self.assertEqual(season_game_count(self.cursor, 7), 2)

    def test_api_date_range_is_preferred_and_truncated(self):
        self.cursor.executemany("INSERT INTO mr_match_meta VALUES (7, ?)", [("2026-05-16 10:00",), ("2026-07-10 11:00",)])
        self.assertEqual(season_date_range(self.cursor, 7), ("2026-05-16", "2026-07-10"))

    def test_empty_range_returns_none_pair(self):
        self.assertEqual(season_date_range(self.cursor, 7), (None, None))


if __name__ == "__main__":
    unittest.main()
