import unittest

from jarvis.stats.matchup_debug import format_matchup_diversity_debug


class MatchupDebugTests(unittest.TestCase):
    def test_repeated_with_unused_outside_tolerance(self):
        lines = format_matchup_diversity_debug({
            "selected_repeat_count": 4, "best_repeat_count": 4,
            "evaluated": 10, "eligible": 1, "unused_eligible": 0,
            "unused_scored": 4, "best_unused_score": 165.0,
            "fairness_best": 73.885, "fairness_selected": 73.885,
            "tolerance_limit": 98.885,
        })
        self.assertIn("**4**", "\n".join(lines))
        self.assertIn("exceeded the fairness tolerance", "\n".join(lines))
        self.assertIn("165.000", "\n".join(lines))

    def test_no_unused_scored_reports_hard_filters(self):
        lines = format_matchup_diversity_debug({
            "selected_repeat_count": 3, "best_repeat_count": 3,
            "evaluated": 1, "eligible": 1, "unused_eligible": 0,
            "unused_scored": 0,
        })
        self.assertIn("hard filters", "\n".join(lines))

    def test_selected_unused(self):
        lines = format_matchup_diversity_debug({
            "selected_repeat_count": 0, "best_repeat_count": 3,
            "evaluated": 10, "eligible": 3, "unused_eligible": 2,
            "unused_scored": 4,
        })
        self.assertNotIn("Repetition reason", "\n".join(lines))

    def test_no_tolerance_reports_unused_first_policy(self):
        lines = format_matchup_diversity_debug({
            "selected_repeat_count": 0, "best_repeat_count": 4,
            "evaluated": 10, "eligible": 10, "unused_eligible": 4,
            "unused_scored": 4, "tolerance_enabled": False,
        })
        self.assertIn("tolerance: disabled", "\\n".join(lines))
        self.assertNotIn("tolerance ceiling", "\\n".join(lines))

    def test_missing_data(self):
        self.assertIn("unavailable", " ".join(format_matchup_diversity_debug(None)))

    def test_import_warning(self):
        result = format_matchup_diversity_debug({
            "selected_repeat_count": 2, "history_source_error": True,
        })
        self.assertIn("lookup failed", "\n".join(result))


if __name__ == "__main__":
    unittest.main()
