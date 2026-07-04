import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path

from jarvis.stats.season_fairness_export import (
    build_fairness_replay,
    load_fairness_replay,
)


class SeasonFairnessExportTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            ("G1", 1, "Alpha", 0),
            ("G1", 2, "Beta", 0),
            ("G1", 3, "Gamma", 0),
            ("G1", 4, "Delta", 1),
            ("G1", 5, "Echo", 1),
            ("G2", 1, "Alpha", 1),
            ("G2", 2, "Beta", 2),
            ("G2", 4, "Delta", 1),
            ("G2", 5, "Echo", 2),
        ]
        self.role_rows = [
            ("G1", 1, "Vanguard", 120),
            ("G1", 1, "Duelist", 30),
            ("G2", 1, "Duelist", 100),
            ("G2", 2, "Unknown", 75),
        ]

    def test_replay_preserves_order_and_derives_fairness_counts(self):
        replay = build_fairness_replay(
            8, self.rows, ["G2", "G1"], self.role_rows
        )
        self.assertEqual([game["game_label"] for game in replay["games"]], ["G2", "G1"])
        self.assertEqual(replay["games"][0]["team_0"], [1, 4])
        self.assertEqual(replay["games"][0]["team_1"], [2, 5])
        self.assertEqual(replay["games"][1]["low_team"], "team_1")
        game_two_roles = {
            row["player_uid"]: row for row in replay["games"][0]["role_usage"]
        }
        self.assertEqual(game_two_roles[1]["primary_role"], "Duelist")
        self.assertEqual(game_two_roles[2]["primary_role"], "Unknown")

        players = {row["player_uid"]: row for row in replay["players"]}
        self.assertEqual(players[4]["low_team_pct"], 100.0)
        self.assertEqual(players[1]["low_team_pct"], 0.0)
        self.assertEqual(
            players[1]["role_summary"]["primary_role_games"],
            {"Vanguard": 1, "Duelist": 1, "Strategist": 0},
        )

        pairs = {
            (row["player_uid_a"], row["player_uid_b"]): row
            for row in replay["pairs"]
        }
        self.assertEqual(pairs[(1, 4)]["teammate_pct"], 50.0)
        self.assertEqual(pairs[(4, 5)]["low_team_together_pct_of_uneven_overlap"], 100.0)

    def test_export_uses_only_approved_fairness_fields(self):
        replay = build_fairness_replay(
            8, self.rows, ["G1", "G2"], self.role_rows
        )
        self.assertEqual(
            set(replay["games"][0]),
            {
                "sequence", "game_label", "team_0", "team_1",
                "unknown_team", "low_team", "role_usage",
            },
        )
        forbidden = {"json_text", "dynamic_json", "player_icon", "hero_icon", "replay_id"}
        self.assertTrue(forbidden.isdisjoint(replay["games"][0]))

    def test_loader_reads_a_database_without_writing(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute(
            "CREATE TABLE match_imports (season_id INTEGER, game_label TEXT, imported_at TEXT)"
        )
        cursor.execute(
            "CREATE TABLE mr_player_match (season_id INTEGER, game_label TEXT, player_uid INTEGER, player TEXT, camp INTEGER, is_bot INTEGER)"
        )
        cursor.execute(
            "CREATE TABLE hero_cache (hero_id TEXT, hero_role TEXT)"
        )
        cursor.execute(
            "CREATE TABLE mr_hero_segments (season_id INTEGER, game_label TEXT, player_uid INTEGER, hero_id TEXT, seconds REAL, is_bot INTEGER)"
        )
        cursor.executemany(
            "INSERT INTO match_imports VALUES (8, ?, ?)",
            [("G2", "2026-07-02"), ("G1", "2026-07-01")],
        )
        cursor.executemany(
            "INSERT INTO mr_player_match VALUES (8, ?, ?, ?, ?, 0)", self.rows
        )
        cursor.executemany(
            "INSERT INTO hero_cache VALUES (?, ?)",
            [("101", "Vanguard"), ("102", "Duelist")],
        )
        cursor.executemany(
            "INSERT INTO mr_hero_segments VALUES (8, ?, ?, ?, ?, 0)",
            [("G1", 1, "101", 120), ("G2", 1, "102", 100)],
        )
        before = connection.total_changes
        replay = load_fairness_replay(cursor, 8)
        self.assertEqual([game["game_label"] for game in replay["games"]], ["G1", "G2"])
        self.assertEqual(connection.total_changes, before)
        players = {row["player_uid"]: row for row in replay["players"]}
        self.assertEqual(players[1]["role_summary"]["primary_role_games"]["Vanguard"], 1)
        self.assertEqual(players[1]["role_summary"]["primary_role_games"]["Duelist"], 1)
        cursor.close()
        connection.close()

    def test_loader_runs_against_a_temporary_snapshot_copy(self):
        source = Path(__file__).resolve().parents[1] / "marvel_rivals_stats.db"
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / source.name
            shutil.copy2(source, copied)
            connection = sqlite3.connect(copied)
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT MAX(season_id) FROM mr_player_match")
                season_id = int(cursor.fetchone()[0])
                replay = load_fairness_replay(cursor, season_id)
                self.assertEqual(replay["season_id"], season_id)
                self.assertGreater(replay["game_count"], 0)
                self.assertGreater(len(replay["players"]), 0)
                self.assertGreater(len(replay["pairs"]), 0)
            finally:
                cursor.close()
                connection.close()


if __name__ == "__main__":
    unittest.main()
