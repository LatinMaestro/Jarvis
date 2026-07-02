import sqlite3
import unittest

from jarvis.stats.head_to_head import get_opponent_match_uids


class HeadToHeadReadTests(unittest.TestCase):
    def test_returns_only_human_opponent_matches(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, match_uid TEXT, game_label TEXT, player_uid INTEGER, is_bot INTEGER, is_win INTEGER)")
        cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?)", [(7, "opp", "G1", 1, 0, 1), (7, "opp", "G1", 2, 0, 0), (7, "same", "G2", 1, 0, 1), (7, "same", "G2", 2, 0, 1), (7, "bot", "G3", 1, 0, 1), (7, "bot", "G3", 2, 1, 0)])
        self.assertEqual(get_opponent_match_uids(cursor, 7, 1, 2), ["opp"])
        cursor.close(); connection.close()


if __name__ == "__main__":
    unittest.main()
