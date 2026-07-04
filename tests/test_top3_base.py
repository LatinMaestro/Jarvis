import unittest

from jarvis.stats.top3_base import build_top3_base


class Top3BaseTests(unittest.TestCase):
    def test_advantaged_and_disadvantaged_team_counts(self):
        rows = [
            ("m1", 1, "A", 0, 1), ("m1", 2, "B", 0, 1),
            ("m1", 3, "C", 1, 0), ("m1", 4, "D", 1, 0),
        ]
        result = build_top3_base(rows, [1, 2, 3])
        by_uid = {row["player_uid"]: row for row in result["rows_base"]}
        self.assertEqual(result["summary"]["qualifying_matches"], 1)
        self.assertEqual(by_uid[1]["more_games"], 1)
        self.assertEqual(by_uid[3]["vs_more_games"], 1)


if __name__ == "__main__":
    unittest.main()
