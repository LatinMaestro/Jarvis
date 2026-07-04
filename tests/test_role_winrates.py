import sqlite3
import unittest

from jarvis.stats.role_winrates import load_role_segment_rows


class RoleWinrateReadTests(unittest.TestCase):
    def test_join_sums_segments_and_excludes_bots(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_hero_segments (season_id INTEGER, match_uid TEXT, game_label TEXT, player_uid INTEGER, hero_id INTEGER, seconds REAL)")
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, match_uid TEXT, game_label TEXT, player_uid INTEGER, player TEXT, camp INTEGER, is_win INTEGER, is_bot INTEGER)")
        cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [(7, "m", "G", 1, "A", 1, 1, 0), (7, "m", "G", 2, "Bot", 2, 0, 1)])
        cursor.executemany("INSERT INTO mr_hero_segments VALUES (?, ?, ?, ?, ?, ?)", [(7, "m", "G", 1, 101, 20), (7, "m", "G", 1, 101, 30), (7, "m", "G", 2, 202, 99)])
        self.assertEqual(load_role_segment_rows(cursor, 7), [("m", "G", 1, "A", 1, 1, 101, 50.0)])
        cursor.close(); connection.close()


if __name__ == "__main__":
    unittest.main()
