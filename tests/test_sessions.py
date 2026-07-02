import sqlite3
import unittest

from jarvis.stats.sessions import load_all_ordered_game_labels, load_games_grouped_by_local_date


class SessionDateReadTests(unittest.TestCase):
    def test_groups_first_import_by_brisbane_date_and_orders_games(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE match_imports (season_id INTEGER, game_label TEXT, imported_at TEXT)")
        cursor.executemany("INSERT INTO match_imports VALUES (?, ?, ?)", [(7, "G2", "2026-01-02 00:00:00"), (7, "G1", "2026-01-01 15:00:00"), (7, "G1", "2026-01-03 00:00:00"), (6, "OLD", "2026-01-01 00:00:00")])
        dates, grouped = load_games_grouped_by_local_date(cursor, 7, 10)
        self.assertEqual(dates, ["2026-01-02"])
        self.assertEqual(grouped, {"2026-01-02": ["G1", "G2"]})
        self.assertEqual(load_all_ordered_game_labels(cursor, 7, 10), ["G1", "G2"])
        cursor.close(); connection.close()


if __name__ == "__main__":
    unittest.main()
