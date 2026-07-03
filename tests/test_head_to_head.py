import sqlite3
import unittest

from jarvis.stats.head_to_head import get_opponent_match_uids, load_accuracy_components, load_player_totals, load_total_seconds


class HeadToHeadReadTests(unittest.TestCase):
    def test_returns_only_human_opponent_matches(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, match_uid TEXT, game_label TEXT, player_uid INTEGER, is_bot INTEGER, is_win INTEGER)")
        cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?)", [(7, "opp", "G1", 1, 0, 1), (7, "opp", "G1", 2, 0, 0), (7, "same", "G2", 1, 0, 1), (7, "same", "G2", 2, 0, 1), (7, "bot", "G3", 1, 0, 1), (7, "bot", "G3", 2, 1, 0)])
        self.assertEqual(get_opponent_match_uids(cursor, 7, 1, 2), ["opp"])
        cursor.close(); connection.close()

    def test_accuracy_components_weight_by_seconds(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_hero_segments (season_id INTEGER, match_uid TEXT, player_uid INTEGER, is_bot INTEGER, session_hit_rate REAL, seconds REAL)")
        cursor.executemany("INSERT INTO mr_hero_segments VALUES (?, ?, ?, ?, ?, ?)", [(7, "m1", 1, 0, 0.5, 100), (7, "m2", 1, 0, 1.0, 50), (7, "other", 1, 0, 0.0, 999), (7, "m1", 2, 0, 1.0, 100)])
        self.assertEqual(load_accuracy_components(cursor, 7, 1, ["m1", "m2"]), (100.0, 150.0))
        cursor.close(); connection.close()

    def test_total_seconds_is_restricted_to_matches_and_player(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_hero_segments (season_id INTEGER, match_uid TEXT, player_uid INTEGER, is_bot INTEGER, seconds REAL)")
        cursor.executemany("INSERT INTO mr_hero_segments VALUES (?, ?, ?, ?, ?)", [(7, "m1", 1, 0, 100), (7, "m2", 1, 0, 50), (7, "other", 1, 0, 999), (7, "m1", 2, 0, 999)])
        self.assertEqual(load_total_seconds(cursor, 7, 1, ["m1", "m2"]), 150.0)
        cursor.close(); connection.close()

    def test_player_totals_are_restricted_to_requested_matches(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE mr_player_match (season_id INTEGER, match_uid TEXT, player_uid INTEGER, is_bot INTEGER, is_win INTEGER, kills INTEGER, deaths INTEGER, assists INTEGER, total_hero_damage REAL, total_hero_heal REAL, total_damage_taken REAL)")
        cursor.executemany("INSERT INTO mr_player_match VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [(7, "m1", 1, 0, 1, 10, 2, 5, 100, 20, 50), (7, "m2", 1, 0, 0, 4, 3, 2, 40, 10, 30), (7, "other", 1, 0, 1, 99, 0, 0, 999, 999, 999)])
        self.assertEqual(load_player_totals(cursor, 7, 1, ["m1", "m2"]), (2, 1, 1, 14, 5, 7, 140.0, 30.0, 80.0))
        cursor.close(); connection.close()


if __name__ == "__main__":
    unittest.main()
