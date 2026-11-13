import sqlite3
import unittest

from jarvis.stats.season_leaderboard_timeline import build_season_leaderboard_timeline


class SeasonLeaderboardTimelineTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()
        self.cursor.executescript("""
            CREATE TABLE mr_player_match (
                season_id INTEGER, game_label TEXT, match_uid TEXT,
                player_uid INTEGER, player TEXT, camp INTEGER, is_win INTEGER, is_bot INTEGER
            );
            CREATE TABLE match_imports (
                season_id INTEGER, game_label TEXT, match_uid TEXT, imported_at TEXT
            );
            CREATE TABLE mr_match_meta (
                season_id INTEGER, match_uid TEXT, match_time_utc TEXT
            );
        """)

    def game(self, label, results, played_at=None):
        uid = label + "-uid"
        self.cursor.execute(
            "INSERT INTO match_imports VALUES (10,?,?,?)",
            (label, uid, "2026-11-12 02:00:00"),
        )
        self.cursor.execute(
            "INSERT INTO mr_match_meta VALUES (10,?,?)", (uid, played_at)
        )
        self.cursor.executemany(
            "INSERT INTO mr_player_match VALUES (10,?,?,?,?,?,?,0)",
            [(label, uid, p_uid, name, camp, win)
             for p_uid, name, camp, win in results],
        )

    def test_every_game_has_full_standings_and_true_rank_changes(self):
        self.game("g1", [(1, "Ada", 0, 1), (2, "Ben", 1, 0)],
                  "2026-11-10T08:00:00+00:00")
        self.game("g2", [(2, "Ben", 0, 1), (3, "Cora", 1, 0)])
        self.game("g3", [(2, "Ben", 0, 1), (1, "Ada", 1, 0)])
        self.cursor.execute(
            "INSERT INTO mr_player_match VALUES (10,'g1','g1-uid',99,'BOT',0,1,1)"
        )
        report = build_season_leaderboard_timeline(
            self.cursor, 10, ["g1", "g2", "g3"]
        )
        self.assertEqual(
            (report["game_count"], report["player_count"]), (3, 3)
        )
        first = {x["player_uid"]: x
                 for x in report["games"][0]["standings_after"]}
        self.assertEqual(
            (first[1]["rank"], first[2]["rank"], first[3]["rank"]),
            (1, 2, None),
        )
        second = {x["player_uid"]: x
                  for x in report["games"][1]["standings_after"]}
        self.assertEqual(
            (second[1]["rank"], second[2]["rank"], second[3]["rank"]),
            (1, 2, 3),
        )
        self.assertIsNone(second[3]["previous_rank"])
        final = {x["player_uid"]: x
                 for x in report["games"][2]["standings_after"]}
        self.assertEqual(
            (final[1]["rank"], final[2]["rank"], final[3]["rank"]),
            (2, 1, 3),
        )
        self.assertEqual(final[1]["rank_change"], -1)
        self.assertEqual(final[2]["rank_change"], 1)
        self.assertEqual(
            (final[1]["wins"], final[1]["losses"]), (1, 1)
        )
        self.assertEqual(
            report["games"][0]["time_source"], "match_play_time"
        )
        self.assertEqual(
            report["games"][1]["time_source"], "import_time_fallback"
        )
        self.assertEqual(
            report["fallback_or_unknown_timestamp_count"], 2
        )
        self.assertEqual(report["games"][0]["winning_camp"], 0)

    def test_fails_instead_of_silently_dropping_a_game(self):
        self.game("g1", [(1, "Ada", 0, 1)])
        self.game("g2", [(2, "Ben", 1, 0)])
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_season_leaderboard_timeline(self.cursor, 10, ["g1"])

    def test_rejects_missing_outcome(self):
        self.game("g1", [(1, "Ada", 0, None)])
        with self.assertRaisesRegex(ValueError, "invalid human win/loss"):
            build_season_leaderboard_timeline(self.cursor, 10, ["g1"])

    def test_season_isolation(self):
        self.game("g1", [(1, "Ada", 0, 1)])
        self.cursor.execute(
            "INSERT INTO mr_player_match VALUES (9,'other','other',1,'Ada',0,0,0)"
        )
        report = build_season_leaderboard_timeline(
            self.cursor, 10, ["g1"]
        )
        self.assertEqual(
            report["games"][0]["standings_after"][0]["wins"], 1
        )


if __name__ == "__main__":
    unittest.main()
