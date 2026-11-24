import sqlite3
import unittest
from PIL import Image

from jarvis.stats.early_exits import (
    add_exit, ensure_tables, find_matches, format_summary, get_match,
    list_exits, remove_exit, render_summary, summarize,
)


class EarlyExitTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("""CREATE TABLE mr_match_meta (
            season_id INTEGER, match_uid TEXT, game_label TEXT,
            match_time_utc TEXT, PRIMARY KEY(season_id,match_uid))""")
        self.db.execute("""CREATE TABLE mr_player_match (
            season_id INTEGER, match_uid TEXT, player_uid INTEGER,
            player TEXT, camp INTEGER, is_win INTEGER, is_bot INTEGER)""")
        for sid, mid, win in [(11, "100", 0), (11, "200", 1), (10, "300", 1)]:
            self.db.execute("INSERT INTO mr_match_meta VALUES (?,?,?,?)",
                            (sid,mid,"1","2026-11-20T10:00:00Z"))
            self.db.executemany("INSERT INTO mr_player_match VALUES (?,?,?,?,?,?,?)",
                [(sid,mid,1,"LatinMaestro",1,win,0),
                 (sid,mid,2,"Rhys",1,win,0),
                 (sid,mid,3,"Grayson",2,1-win,0),
                 (sid,mid,4,"JarvisBot",1,win,1)])
        self.db.commit()
        ensure_tables(self.db)

    def tearDown(self):
        self.db.close()

    def test_match_lookup_and_human_participation(self):
        self.assertEqual({p[0] for p in get_match(self.db,11,"100")["players"]}, {1,2,3})
        self.assertEqual(len(get_match(self.db,11,"100")["players"]),3)
        self.assertEqual(len(find_matches(self.db,"100")),1)

    def test_duplicate_and_missing_player_are_rejected(self):
        self.assertEqual(add_exit(self.db,99,11,"100",1,777),"saved")
        self.assertEqual(add_exit(self.db,99,11,"100",1,777),"duplicate")
        self.assertEqual(add_exit(self.db,99,11,"100",4,777),"not_found")
        self.assertEqual(add_exit(self.db,99,11,"absent",1,777),"not_found")
        self.assertEqual(len(list_exits(self.db,99,11)),1)

    def test_win_loss_and_teammates(self):
        for sid,mid in [(11,"100"),(11,"200"),(10,"300")]:
            self.assertEqual(add_exit(self.db,99,sid,mid,1,777),"saved")
        report=summarize(self.db,99,11)
        self.assertEqual(report["total"]["exits"],2)
        self.assertEqual(report["total"]["wins"],1)
        self.assertEqual(report["total"]["losses"],1)
        self.assertEqual(report["affected"][2]["games"],2)
        self.assertNotIn(3,report["affected"])
        all_time=summarize(self.db,99)
        self.assertEqual(all_time["total"]["exits"],3)
        self.assertEqual(all_time["total"]["affected_occurrences"],3)
        self.assertEqual(all_time["total"]["unique_teammates"],1)
        self.assertIn("2W / 1L",format_summary(all_time,"All time"))

    def test_scope_and_removal(self):
        self.assertEqual(add_exit(self.db,99,11,"100",1,777),"saved")
        self.assertEqual(add_exit(self.db,100,11,"100",1,888),"saved")
        self.assertTrue(remove_exit(self.db,99,11,"100",1))
        self.assertFalse(remove_exit(self.db,99,11,"100",1))
        self.assertEqual(len(list_exits(self.db,100)),1)

    def test_unknown_result_does_not_become_loss(self):
        self.db.execute("UPDATE mr_player_match SET is_win=NULL WHERE season_id=11 AND match_uid='100' AND player_uid=1")
        self.db.commit()
        add_exit(self.db,99,11,"100",1,777)
        totals=summarize(self.db,99)["total"]
        self.assertEqual((totals["wins"],totals["losses"],totals["unknown"]),(0,0,1))

    def test_image_includes_both_tables_and_scales_with_record_count(self):
        add_exit(self.db, 99, 11, "100", 1, 777)
        report = summarize(self.db, 99)
        image = Image.open(render_summary(report, "Season 11 Early Exit Report"))
        self.assertEqual(image.size[0], 1200)
        # One departing player and one affected teammate must have a table row.
        self.assertGreaterEqual(image.size[1], 800)

        # A longer player list must increase height instead of truncating rows.
        enlarged = summarize(self.db, 99)
        enlarged["by_player"] = {
            uid: {"exits": 1, "wins": 0, "losses": 1, "unknown": 0}
            for uid in range(1, 31)
        }
        enlarged["affected"] = {
            uid: {"games": 1, "wins": 0, "losses": 1, "unknown": 0}
            for uid in range(40, 70)
        }
        enlarged["names"] = {
            uid: "PlayerWithAnExtremelyLongUsernameWhichMustFit"
            for uid in list(enlarged["by_player"]) + list(enlarged["affected"])
        }
        large_image = Image.open(render_summary(enlarged, "Season 11 Early Exit Report"))
        self.assertGreater(large_image.size[1], image.size[1] + 2000)

    def test_image_is_valid_png(self):
        buf=render_summary(summarize(self.db,99),"Season 11 Early Exit Report")
        self.assertEqual(buf.read(8),bytes.fromhex("89504e470d0a1a0a"))


if __name__ == "__main__":
    unittest.main()
