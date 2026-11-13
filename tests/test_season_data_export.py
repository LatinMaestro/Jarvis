import csv
import io
import json
import sqlite3
import unittest
import zipfile

from jarvis.stats.season_data_export import build_season_data_export


class SeasonDataExportTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()
        self.cursor.executescript("""
            CREATE TABLE match_imports (
                season_id INTEGER, match_uid TEXT, game_label TEXT, imported_at TEXT
            );
            CREATE TABLE mr_match_meta (
                season_id INTEGER, match_uid TEXT, game_label TEXT, match_time_utc TEXT
            );
            CREATE TABLE mr_player_match (
                season_id INTEGER, match_uid TEXT, game_label TEXT,
                player_uid INTEGER, player TEXT, is_bot INTEGER,
                camp INTEGER, is_win INTEGER
            );
            CREATE TABLE mr_match_json_raw (
                season_id INTEGER, match_uid TEXT, game_label TEXT, json_text TEXT
            );
        """)

    def game(self, season_id, label, played, rows):
        match_uid = f"{season_id}-{label}"
        self.cursor.execute(
            "INSERT INTO match_imports VALUES (?,?,?,?)",
            (season_id, match_uid, label, played),
        )
        self.cursor.execute(
            "INSERT INTO mr_match_meta VALUES (?,?,?,?)",
            (season_id, match_uid, label, played),
        )
        self.cursor.execute(
            "INSERT INTO mr_match_json_raw VALUES (?,?,?,?)",
            (season_id, match_uid, label, json.dumps({"source_game": label})),
        )
        self.cursor.executemany(
            "INSERT INTO mr_player_match VALUES (?,?,?,?,?,?,?,?)",
            [(season_id, match_uid, label, player, name, bot, camp, win)
             for player, name, bot, camp, win in rows],
        )

    def test_zip_includes_all_games_source_data_and_leaderboard(self):
        self.game(10, "Game_1", "2026-11-12T12:00:00+00:00", [
            (1, "Ada", 0, 0, 1), (2, "Ben", 0, 1, 0),
            (99, "Bot", 1, 0, 1),
        ])
        self.game(10, "Game_2", "2026-11-12T12:15:00+00:00", [
            (1, "Ada", 0, 1, 0), (2, "Ben", 0, 0, 1),
        ])
        self.game(9, "Old_Game", "2025-11-12T12:00:00+00:00", [
            (1, "Ada", 0, 0, 1),
        ])
        archive_buffer = build_season_data_export(self.cursor, 10)
        self.assertIsNotNone(archive_buffer)
        with zipfile.ZipFile(archive_buffer) as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.json", names)
            self.assertIn("leaderboard_timeline.json", names)
            self.assertIn("leaderboard_history.csv", names)
            self.assertIn("games.csv", names)
            self.assertIn("tables/mr_match_json_raw.csv", names)
            self.assertIn("tables/mr_player_match.csv", names)
            self.assertNotIn("movie_story.md", names)

            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["game_count"], 2)
            self.assertEqual(manifest["unique_human_players"], 2)
            self.assertEqual(manifest["source_table_row_counts"]["mr_player_match"], 5)
            timeline = json.loads(archive.read("leaderboard_timeline.json"))
            self.assertEqual([g["game_label"] for g in timeline["games"]],
                             ["Game_1", "Game_2"])
            ranks = [
                {p["player_uid"]: p["rank"] for p in game["standings_after"]}
                for game in timeline["games"]
            ]
            self.assertEqual(ranks, [{1: 1, 2: 2}, {1: 1, 2: 2}])
            history = list(csv.DictReader(io.StringIO(
                archive.read("leaderboard_history.csv").decode("utf-8-sig")
            )))
            self.assertEqual(len(history), 4)
            matches = list(csv.DictReader(io.StringIO(
                archive.read("tables/mr_match_json_raw.csv").decode("utf-8-sig")
            )))
            self.assertEqual(len(matches), 2)
            self.assertEqual(json.loads(matches[0]["json_text"])["source_game"], "Game_1")

    def test_no_games_returns_none(self):
        self.assertIsNone(build_season_data_export(self.cursor, 10))

    def test_missing_human_result_refuses_incomplete_history(self):
        self.game(10, "Game_1", "2026-11-12T12:00:00+00:00", [
            (99, "Bot", 1, 0, 1)
        ])
        with self.assertRaisesRegex(ValueError, "does not match human results"):
            build_season_data_export(self.cursor, 10)


if __name__ == "__main__":
    unittest.main()
