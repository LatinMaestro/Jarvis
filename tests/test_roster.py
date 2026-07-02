import sqlite3
import unittest

from jarvis.database.roster import list_enabled_roster_uids, list_roster


class RosterReadTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE mr_roster (player_uid INTEGER, player_name TEXT, enabled INTEGER)")
        self.cursor.executemany("INSERT INTO mr_roster VALUES (?, ?, ?)", [(3, "C", 0), (2, "B", 1), (1, "A", 1)])

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def test_full_roster_preserves_enabled_then_uid_order(self):
        self.assertEqual(list_roster(self.cursor), [(1, "A", 1), (2, "B", 1), (3, "C", 0)])

    def test_enabled_uid_list_filters_and_orders(self):
        self.assertEqual(list_enabled_roster_uids(self.cursor), [1, 2])


if __name__ == "__main__":
    unittest.main()
