import sqlite3
import unittest

from PIL import Image

from jarvis.stats.player_bans import (
    build_player_bans_report,
    load_ban_events,
    load_human_player_matches,
    render_player_bans_image,
)


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

    def test_report_counts_only_opposing_team_bans(self):
        player_rows = []
        ban_rows = []
        for index in range(5):
            match_uid = f"m{index}"
            player_rows.extend([(match_uid, "Alpha", 0), (match_uid, "Beta", 1)])
            ban_rows.extend([(match_uid, 0, 202), (match_uid, 1, 101)])

        report = build_player_bans_report(
            player_rows,
            ban_rows,
            {"101": "Hero One", "202": "Hero Two"},
        )

        by_player = {row["player"]: row for row in report["table_rows"]}
        self.assertEqual(by_player["Alpha"]["b1"], "Hero One (5, 100%)")
        self.assertEqual(by_player["Beta"]["b1"], "Hero Two (5, 100%)")
        self.assertEqual(len(report["top5"]), 2)

    def test_rendered_report_is_fixed_size_valid_png(self):
        report = build_player_bans_report(
            [("m1", "Alpha", 0), ("m1", "Beta", 1)],
            [("m1", 1, 101)],
            {"101": "Hero One"},
        )
        buffer = render_player_bans_image(7, report)
        self.assertGreater(len(buffer.getvalue()), 0)
        with Image.open(buffer) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (1500, 980))
            image.verify()


if __name__ == "__main__":
    unittest.main()
