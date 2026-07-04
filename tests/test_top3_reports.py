import unittest

from jarvis.stats.top3_reports import _top3_more_prepare_payload


class Top3ReportPayloadTests(unittest.TestCase):
    def test_all_and_qualifying_scopes_use_expected_denominators(self):
        base = {"rows_base": [{"player_uid": 1, "player": "A", "is_top3": False,
            "all_games": 10, "all_wins": 5, "qual_games": 4, "qual_wins": 3,
            "more_games": 2, "more_wins": 2, "vs_more_games": 1, "vs_more_wins": 0,
            "more_by1": 1, "more_by2plus": 1}], "summary": {}}
        all_row = _top3_more_prepare_payload(base, "all")["rows"][0]
        qual_row = _top3_more_prepare_payload(base, "qual")["rows"][0]
        self.assertEqual(all_row["more_pct"], 20.0)
        self.assertEqual(qual_row["more_pct"], 50.0)
        self.assertEqual(qual_row["overall_wr"], 75.0)


if __name__ == "__main__":
    unittest.main()
