import sqlite3
import unittest

from jarvis.stats.profiles import latest_player_name, list_human_players, load_accuracy_rows


class ProfilePlayerReadTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, player_uid INTEGER, player TEXT, is_bot INTEGER)")
        self.cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?)", [(7, 2, "Beta", 0), (7, 1, "Alpha Old", 0), (7, 1, "Alpha", 0), (7, 3, "Bot", 1), (6, 9, "Old", 0)])

    def tearDown(self):
        self.cursor.close(); self.connection.close()

    def test_lists_unique_humans_in_name_order(self):
        self.assertEqual(list_human_players(self.cursor, 7), [{"player_uid": 1, "player": "Alpha"}, {"player_uid": 2, "player": "Beta"}])

    def test_latest_name_and_uid_fallback(self):
        self.assertEqual(latest_player_name(self.cursor, 7, 1), "Alpha")
        self.assertEqual(latest_player_name(self.cursor, 7, 99), "UID_99")

    def test_accuracy_rows_weight_only_non_null_accuracy(self):
        self.cursor.execute("CREATE TABLE mr_hero_segments (season_id INTEGER, player_uid INTEGER, is_bot INTEGER, session_hit_rate REAL, seconds REAL)")
        self.cursor.executemany("INSERT INTO mr_hero_segments VALUES (?, ?, ?, ?, ?)", [(7, 1, 0, 0.5, 100), (7, 1, 0, 1.0, 50), (7, 1, 0, None, 999), (7, 2, 1, 1.0, 100)])
        self.assertEqual(load_accuracy_rows(self.cursor, 7), [(1, 100.0, 150.0)])


if __name__ == "__main__":
    unittest.main()
