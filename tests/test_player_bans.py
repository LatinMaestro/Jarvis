import sqlite3
import unittest

from jarvis.stats.player_bans import load_ban_events, load_human_player_matches


class PlayerBanReadTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, match_uid TEXT, player TEXT, camp INTEGER, is_bot INTEGER)")
        self.cursor.execute("CREATE TABLE mr_ban_picks (season_id INTEGER, match_uid TEXT, battle_side INTEGER, hero_id INTEGER, is_pick INTEGER)")

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def test_player_rows_filter_bots_nulls_and_other_seasons(self):
        self.cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?)", [(7, "m1", "A", 1, 0), (7, "m1", "Bot", 1, 1), (7, None, "B", 2, 0), (6, "old", "C", 1, 0)])
        self.assertEqual(load_human_player_matches(self.cursor, 7), [("m1", "A", 1)])

    def test_ban_rows_exclude_picks_nulls_and_other_seasons(self):
        self.cursor.executemany("INSERT INTO mr_ban_picks VALUES (?, ?, ?, ?, ?)", [(7, "m1", 2, 101, 0), (7, "m1", 2, 102, 1), (7, None, 2, 103, 0), (6, "old", 1, 999, 0)])
        self.assertEqual(load_ban_events(self.cursor, 7), [("m1", 2, 101)])


if __name__ == "__main__":
    unittest.main()
