import sqlite3
import unittest

from jarvis.stats.sessions import (
    aggregate_wl_for_labels,
    load_all_ordered_game_labels,
    load_games_grouped_by_local_date,
    load_human_season_standings,
)


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

    def test_groups_games_across_midnight_when_gap_is_within_twelve_hours(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE match_imports (season_id INTEGER, match_uid TEXT, game_label TEXT, imported_at TEXT)")
        cursor.execute("CREATE TABLE mr_match_meta (season_id INTEGER, match_uid TEXT, match_time_utc TEXT)")
        cursor.executemany(
            "INSERT INTO match_imports VALUES (?, ?, ?, ?)",
            [
                (10, "M1", "G1", "2026-09-11 20:00:00"),
                (10, "M2", "G2", "2026-09-12 20:00:00"),
            ],
        )
        cursor.executemany(
            "INSERT INTO mr_match_meta VALUES (?, ?, ?)",
            [
                (10, "M1", "2026-09-11T13:30:00+00:00"),  # 23:30 Brisbane
                (10, "M2", "2026-09-11T15:00:00+00:00"),  # 01:00 Brisbane
            ],
        )
        dates, grouped = load_games_grouped_by_local_date(cursor, 10)
        self.assertEqual(dates, ["2026-09-11"])
        self.assertEqual(grouped["2026-09-11"], ["G1", "G2"])
        cursor.close(); connection.close()

    def test_starts_new_session_only_after_more_than_twelve_hours(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE match_imports (season_id INTEGER, game_label TEXT, imported_at TEXT)")
        cursor.executemany(
            "INSERT INTO match_imports VALUES (?, ?, ?)",
            [
                (10, "G1", "2026-09-11T10:00:00+00:00"),
                (10, "G2", "2026-09-11T22:00:00+00:00"),
                (10, "G3", "2026-09-12T10:00:01+00:00"),
            ],
        )
        dates, grouped = load_games_grouped_by_local_date(cursor, 10)
        self.assertEqual(dates, ["2026-09-11", "2026-09-12"])
        self.assertEqual(grouped["2026-09-11"], ["G1", "G2"])
        self.assertEqual(grouped["2026-09-12"], ["G3"])
        cursor.close(); connection.close()

    def test_wl_aggregation_filters_bots_and_sorts_by_winrate(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, game_label TEXT, player_uid INTEGER, player TEXT, is_win INTEGER, is_bot INTEGER)")
        cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?)", [(7, "G1", 1, "A", 1, 0), (7, "G2", 1, "A", 0, 0), (7, "G1", 2, "B", 1, 0), (7, "G2", 2, "B", 1, 0), (7, "G1", 3, "Bot", 1, 1)])
        frame = aggregate_wl_for_labels(cursor, 7, ["G1", "G2"])
        self.assertEqual(list(frame["player"]), ["B", "A"])
        self.assertEqual(list(frame["wl_str"]), ["2/0", "1/1"])
        cursor.close(); connection.close()

    def test_season_standings_match_leaderboard_primary_source(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE game_stats_v (player TEXT, win INTEGER, loss INTEGER)")
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, player TEXT, is_win INTEGER, is_bot INTEGER)")
        cursor.executemany(
            "INSERT INTO game_stats_v VALUES (?, ?, ?)",
            [("Alpha", 1, 0), (" Alpha ", 0, 1), ("Beta", 1, 0)],
        )
        cursor.execute("INSERT INTO mr_player_match VALUES (10, 'Ignored fallback', 1, 0)")
        frame = load_human_season_standings(cursor, 10)
        self.assertEqual(list(frame["player"]), ["Beta", " Alpha "])
        self.assertEqual(list(frame["wl_str"]), ["1/0", "1/1"])
        self.assertEqual(list(frame["winrate"]), [100.0, 50.0])
        cursor.close(); connection.close()

    def test_season_standings_use_api_fallback_when_leaderboard_view_is_empty(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE game_stats_v (player TEXT, win INTEGER, loss INTEGER)")
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, player TEXT, is_win INTEGER, is_bot INTEGER)")
        cursor.executemany(
            "INSERT INTO mr_player_match VALUES (?, ?, ?, ?)",
            [(10, "Alpha", 1, 0), (10, "Alpha", 0, 0), (10, "Bot", 1, 1)],
        )
        frame = load_human_season_standings(cursor, 10)
        self.assertEqual(list(frame["wl_str"]), ["1/1"])
        self.assertEqual(list(frame["winrate"]), [50.0])
        cursor.close(); connection.close()


if __name__ == "__main__":
    unittest.main()
