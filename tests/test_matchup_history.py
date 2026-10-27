import unittest
from jarvis.stats.matchup_history import (
    matchup_key, imported_matchups, combined_matchup_counts, choose_diverse_candidate,
)


class MatchupHistoryTests(unittest.TestCase):
    def test_order_and_team_swap_are_equivalent(self):
        self.assertEqual(
            matchup_key(["u3", "u1"], ["u2"]),
            matchup_key(["u2"], ["u1", "u3"]),
        )

    def test_different_team_split_differs(self):
        self.assertNotEqual(
            matchup_key(["u1", "u2"], ["u3", "u4"]),
            matchup_key(["u1", "u3"], ["u2", "u4"]),
        )

    def test_imported_games_use_camp_and_ignore_incomplete(self):
        games = imported_matchups([
            ("m1", 1, 0, "2026-10-28T00:00:00Z"),
            ("m1", 2, 1, "2026-10-28T00:00:00Z"),
            ("m2", 1, 0, None),
        ])
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0][0], matchup_key(["u1"], ["u2"]))

    def test_session_roll_is_counted_without_import(self):
        key = matchup_key(["u1", "u2"], ["u3"])
        counts = combined_matchup_counts([], [{
            "team_a": ["u1", "u2"], "team_b": ["u3"], "season_id": 10,
            "generated_at_epoch": 1000,
        }], 10)
        self.assertEqual(counts[key], 1)

    def test_import_reconciles_matching_session_roll_once(self):
        key = matchup_key(["u1", "u2"], ["u3"])
        imported = [(key, 1500.0)]
        session = [{"team_a": ["u1", "u2"], "team_b": ["u3"],
                    "season_id": 10, "generated_at_epoch": 1000}]
        self.assertEqual(combined_matchup_counts(imported, session, 10)[key], 1)

    def test_unrelated_import_does_not_reconcile(self):
        key = matchup_key(["u1"], ["u2"])
        session = [{"team_a": ["u1"], "team_b": ["u2"],
                    "season_id": 10, "generated_at_epoch": 1000}]
        self.assertEqual(combined_matchup_counts([(key, 25000)], session, 10)[key], 2)

    def test_other_season_session_games_ignored(self):
        key = matchup_key(["u1"], ["u2"])
        session = [{"team_a": ["u1"], "team_b": ["u2"], "season_id": 9}]
        self.assertEqual(combined_matchup_counts([], session, 10)[key], 0)

    def test_prefers_unused_within_fairness_tolerance(self):
        a = {"team_a": ["u1", "u2"], "team_b": ["u3", "u4"]}
        b = {"team_a": ["u1", "u3"], "team_b": ["u2", "u4"]}
        scores = [(100, 1, a), (110, 2, b)]
        chosen, debug = choose_diverse_candidate(
            scores, {matchup_key(a["team_a"], a["team_b"]): 4}
        )
        self.assertEqual(chosen[1], 2)
        self.assertEqual(debug["selected_repeat_count"], 0)

    def test_prefers_unused_even_with_large_fairness_gap(self):
        a = {"team_a": ["u1", "u2"], "team_b": ["u3", "u4"]}
        b = {"team_a": ["u1", "u3"], "team_b": ["u2", "u4"]}
        chosen, _ = choose_diverse_candidate(
            [(100, 1, a), (2939.410, 2, b)],
            {matchup_key(a["team_a"], a["team_b"]): 8}
        )
        self.assertEqual(chosen[1], 2)

    def test_least_repeated_when_all_used(self):
        a = {"team_a": ["u1", "u2"], "team_b": ["u3", "u4"]}
        b = {"team_a": ["u1", "u3"], "team_b": ["u2", "u4"]}
        history = {matchup_key(a["team_a"], a["team_b"]): 3,
                   matchup_key(b["team_a"], b["team_b"]): 1}
        chosen, _ = choose_diverse_candidate([(100, 1, a), (110, 2, b)], history)
        self.assertEqual(chosen[1], 2)

    def test_fairness_tiebreaks_equally_unplayed(self):
        a = {"team_a": ["u1", "u2"], "team_b": ["u3", "u4"]}
        b = {"team_a": ["u1", "u3"], "team_b": ["u2", "u4"]}
        chosen, _ = choose_diverse_candidate([(300, 1, a), (110, 2, b)], {})
        self.assertEqual(chosen[1], 2)

    def test_fairness_tiebreaks_equally_repeated(self):
        a = {"team_a": ["u1", "u2"], "team_b": ["u3", "u4"]}
        b = {"team_a": ["u1", "u3"], "team_b": ["u2", "u4"]}
        history = {matchup_key(a["team_a"], a["team_b"]): 2,
                   matchup_key(b["team_a"], b["team_b"]): 2}
        chosen, _ = choose_diverse_candidate([(100, 1, a), (95, 2, b)], history)
        self.assertEqual(chosen[1], 2)

    def test_empty_pool_does_not_raise(self):
        chosen, debug = choose_diverse_candidate([], {})
        self.assertIsNone(chosen)
        self.assertEqual(debug["reason"], "no_candidates")


if __name__ == "__main__":
    unittest.main()
