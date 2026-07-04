import sqlite3
import unittest

from jarvis.stats.top3 import load_human_match_rows


class TopThreeReadTests(unittest.TestCase):
    def test_filters_invalid_rows_and_preserves_insert_order(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, match_uid TEXT, player_uid INTEGER, player TEXT, camp INTEGER, is_win INTEGER, is_bot INTEGER)")
        cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?, ?)", [(7, "m2", 2, "B", 2, 0, 0), (7, "m1", 1, "A", 1, 1, 0), (7, "bot", 3, "Bot", 1, 1, 1), (6, "old", 9, "Old", 1, 1, 0)])
        self.assertEqual(load_human_match_rows(cursor, 7), [("m2", 2, "B", 2, 0), ("m1", 1, "A", 1, 1)])
        cursor.close()
        connection.close()


if __name__ == "__main__":
    unittest.main()
