import sqlite3
import unittest

from jarvis.stats.games import get_recent_games


class RecentGameTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE mr_match_meta (season_id INTEGER, game_label TEXT, match_uid TEXT, match_time_utc TEXT, imported_at TEXT)")
        self.cursor.execute("CREATE TABLE match_imports (season_id INTEGER, game_label TEXT, match_uid TEXT, imported_at TEXT)")
        self.cursor.execute("CREATE TABLE game_stats_v (game_label TEXT, timestamp TEXT)")

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def test_meta_rows_are_preferred(self):
        self.cursor.execute("INSERT INTO mr_match_meta VALUES (7, 'A', 'm1', 'played', '2026-02-01')")
        self.cursor.execute("INSERT INTO match_imports VALUES (7, 'B', 'm2', '2026-03-01')")
        self.assertEqual(get_recent_games(self.cursor, 7, 40), [("A", "m1", "played", "2026-02-01")])

    def test_import_rows_are_normalised_as_fallback(self):
        self.cursor.execute("INSERT INTO match_imports VALUES (7, 'B', 'm2', '2026-03-01')")
        self.assertEqual(get_recent_games(self.cursor, 7, 40), [("B", "m2", None, "2026-03-01")])

    def test_legacy_rows_are_final_fallback(self):
        self.cursor.execute("INSERT INTO game_stats_v VALUES ('C', '2026-04-01')")
        self.assertEqual(get_recent_games(self.cursor, 7, 40), [("C", None, None, "2026-04-01")])


if __name__ == "__main__":
    unittest.main()
