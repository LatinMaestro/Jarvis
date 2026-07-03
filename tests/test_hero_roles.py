import sqlite3
import unittest

from jarvis.stats.hero_roles import load_hero_cache_rows, load_hero_name_rows, load_season_hero_usage


class HeroRoleReadTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE hero_cache (hero_id TEXT, hero_name TEXT, hero_role TEXT)")
        self.cursor.execute("CREATE TABLE mr_hero_segments (season_id INTEGER, hero_id TEXT, seconds REAL)")

    def tearDown(self):
        self.cursor.close()
        self.connection.close()

    def test_cache_rows_are_returned_without_mutation(self):
        self.cursor.execute("INSERT INTO hero_cache VALUES ('1', 'Hero', 'Duelist')")
        self.assertEqual(load_hero_cache_rows(self.cursor), [("1", "Hero", "Duelist")])
        self.assertEqual(load_hero_name_rows(self.cursor), [("1", "Hero")])

    def test_usage_is_summed_filtered_and_sorted(self):
        self.cursor.executemany("INSERT INTO mr_hero_segments VALUES (?, ?, ?)", [(7, "1", 20), (7, "1", 30), (7, "2", 80), (7, "3", 0), (6, "9", 999)])
        self.assertEqual(load_season_hero_usage(self.cursor, 7), [("2", 80.0), ("1", 50.0)])


if __name__ == "__main__":
    unittest.main()
