import unittest

from jarvis.stats.team_fairness import (
    candidate_pair_target_penalty,
    candidate_role_ban_exposure_penalty,
    dynamic_pair_lock_limit,
    record_role_ban_exposure,
    role_ban_history_key,
    same_team_probability,
)
from jarvis.stats.season_fairness_export import build_fairness_replay


class TeamFairnessTests(unittest.TestCase):
    def test_neutral_teammate_probability_uses_team_sizes(self):
        self.assertAlmostEqual(same_team_probability(5, 5), 4 / 9)
        self.assertAlmostEqual(same_team_probability(4, 4), 3 / 7)
        self.assertAlmostEqual(same_team_probability(4, 5), 4 / 9)

    def test_pair_penalty_prefers_correcting_overused_pair(self):
        seen = {("a", "b"): 20}
        together = {("a", "b"): 14}
        expected = {("a", "b"): 20 * (2 / 5)}
        split_pair, _ = candidate_pair_target_penalty(
            frozenset(("a", "c", "d")),
            frozenset(("b", "e", "f")),
            pair_seen=seen,
            pair_together=together,
            pair_expected=expected,
        )
        keep_pair, _ = candidate_pair_target_penalty(
            frozenset(("a", "b", "c")),
            frozenset(("d", "e", "f")),
            pair_seen=seen,
            pair_together=together,
            pair_expected=expected,
        )
        self.assertLess(split_pair, keep_pair)

    def test_dynamic_lock_is_sample_aware_and_target_relative(self):
        key = ("a", "b")
        self.assertIsNone(dynamic_pair_lock_limit(
            key,
            pair_seen={key: 5},
            pair_expected={key: 5 * (4 / 9)},
            current_neutral_probability=4 / 9,
        ))
        limit = dynamic_pair_lock_limit(
            key,
            pair_seen={key: 20},
            pair_expected={key: 20 * (4 / 9)},
            current_neutral_probability=4 / 9,
        )
        self.assertAlmostEqual(limit, (4 / 9) + 0.10)

    def test_committed_role_bans_record_ordered_exposure(self):
        history = record_role_ban_exposure(
            {},
            frozenset(("a", "b")),
            frozenset(("c", "d")),
            {"a": "Vanguard", "b": "Duelist", "c": "Strategist", "d": "Vanguard"},
        )
        same = history["entries"][role_ban_history_key("a", "b", "Duelist")]
        opposite = history["entries"][role_ban_history_key("a", "c", "Strategist")]
        self.assertEqual(same["together"], 1)
        self.assertEqual(opposite["together"], 0)
        self.assertEqual(same["opportunities"], 1)
        self.assertAlmostEqual(same["expected"], 1 / 3)
        self.assertEqual(history["rolls"][0]["team_a"], ["a", "b"])
        self.assertEqual(history["rolls"][0]["restricted_roles"]["c"], "Strategist")

    def test_movie_pack_exports_committed_role_bans(self):
        history = record_role_ban_exposure(
            {},
            frozenset(("u1", "u2")),
            frozenset(("u3", "u4")),
            {"u1": "Vanguard", "u2": "Duelist", "u3": "Strategist", "u4": "Vanguard"},
        )
        replay = build_fairness_replay(9, [], [], role_ban_history=history)
        roll = replay["committed_role_ban_rolls"][0]
        self.assertEqual(roll["team_0"], [1, 2])
        self.assertIn(
            {"player_uid": 3, "banned_role": "Strategist"},
            roll["restricted_roles"],
        )

    def test_role_ban_penalty_prefers_underexposed_receiver_pair(self):
        restrictions = {"a": "Duelist", "b": "Vanguard", "c": "Strategist", "d": "Duelist"}
        entries = {}
        for receiver in restrictions:
            for teammate, banned_role in restrictions.items():
                if receiver == teammate:
                    continue
                entries[role_ban_history_key(receiver, teammate, banned_role)] = {
                    "opportunities": 12,
                    "expected": 4.0,
                    "together": 4,
                }
        entries[role_ban_history_key("a", "b", "Vanguard")]["together"] = 9
        history = {
            "version": 1,
            "entries": entries,
        }
        split_pair, _ = candidate_role_ban_exposure_penalty(
            frozenset(("a", "c")), frozenset(("b", "d")), restrictions, history
        )
        keep_pair, _ = candidate_role_ban_exposure_penalty(
            frozenset(("a", "b")), frozenset(("c", "d")), restrictions, history
        )
        self.assertLess(split_pair, keep_pair)


if __name__ == "__main__":
    unittest.main()
