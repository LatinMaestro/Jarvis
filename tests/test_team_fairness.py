import unittest

from jarvis.stats.team_fairness import (
    candidate_pair_target_penalty,
    candidate_role_ban_exposure_penalty,
    candidate_versatility_low_team_penalty,
    dynamic_pair_lock_limit,
    hero_versatility_deficit,
    queue_role_ban_roll,
    reconcile_role_ban_history,
    record_role_ban_exposure,
    role_ban_history_key,
    same_team_probability,
    uploaded_game_rows_to_team_records,
)
from jarvis.stats.season_fairness_export import build_fairness_replay
from jarvis.stats.team_role_bans import (
    build_teammate_role_ban_matrix,
    render_teammate_role_ban_matrix,
)
from PIL import Image


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
        history["rolls"][0]["confirmed_match_uid"] = "m1"
        history["rolls"][0]["confirmed_game_label"] = "G1"
        replay = build_fairness_replay(9, [], [], role_ban_history=history)
        roll = replay["committed_role_ban_rolls"][0]
        self.assertEqual(roll["team_0"], [1, 2])
        self.assertIn(
            {"player_uid": 3, "banned_role": "Strategist"},
            roll["restricted_roles"],
        )

    def test_queued_roll_is_not_counted_until_exact_uploaded_game_exists(self):
        restrictions = {"u1": "Vanguard", "u2": "Duelist", "u3": "Strategist", "u4": "Vanguard"}
        queued = queue_role_ban_roll(
            {},
            frozenset(("u1", "u2")),
            frozenset(("u3", "u4")),
            restrictions,
            generated_at_epoch=1000,
            committed_at_epoch=1010,
        )
        self.assertEqual(queued["rolls"], [])
        self.assertEqual(queued["entries"], {})

        unmatched, confirmed = reconcile_role_ban_history(queued, [{
            "match_uid": "wrong",
            "game_label": "G1",
            "team_a": ["u1", "u3"],
            "team_b": ["u2", "u4"],
            "imported_at_epoch": 1020,
        }])
        self.assertEqual(confirmed, 0)
        self.assertEqual(unmatched["rolls"], [])
        self.assertEqual(len(unmatched["pending_rolls"]), 1)

        matched, confirmed = reconcile_role_ban_history(unmatched, [{
            "match_uid": "actual",
            "game_label": "G2",
            "team_a": ["u3", "u4"],
            "team_b": ["u1", "u2"],
            "imported_at_epoch": 1030,
        }])
        self.assertEqual(confirmed, 1)
        self.assertEqual(matched["pending_rolls"], [])
        self.assertEqual(matched["rolls"][0]["confirmed_match_uid"], "actual")
        self.assertTrue(matched["entries"])

    def test_upload_before_generation_does_not_confirm_accidental_roll(self):
        queued = queue_role_ban_roll(
            {}, frozenset(("u1", "u2")), frozenset(("u3", "u4")),
            {"u1": "Vanguard", "u2": "Duelist", "u3": "Strategist", "u4": "Vanguard"},
            generated_at_epoch=2000, committed_at_epoch=2010,
        )
        updated, confirmed = reconcile_role_ban_history(queued, [{
            "match_uid": "old", "game_label": "Old",
            "team_a": ["u1", "u2"], "team_b": ["u3", "u4"],
            "imported_at_epoch": 1999,
        }])
        self.assertEqual(confirmed, 0)
        self.assertEqual(updated["rolls"], [])

    def test_uploaded_rows_build_exact_human_teams_for_both_camp_formats(self):
        rows = [
            ("m1", "G1", 1, 1, "2026-07-05 10:00:00"),
            ("m1", "G1", 2, 1, "2026-07-05 10:00:00"),
            ("m1", "G1", 3, 2, "2026-07-05 10:00:00"),
            ("m1", "G1", 4, 2, "2026-07-05 10:00:00"),
            ("m2", "G2", 5, 0, "2026-07-05T11:00:00Z"),
            ("m2", "G2", 6, 1, "2026-07-05T11:00:00Z"),
        ]
        games = uploaded_game_rows_to_team_records(rows)
        self.assertEqual(games[0]["team_a"], ["u1", "u2"])
        self.assertEqual(games[0]["team_b"], ["u3", "u4"])
        self.assertEqual(games[1]["team_a"], ["u5"])
        self.assertEqual(games[1]["team_b"], ["u6"])
        self.assertGreater(games[0]["imported_at_epoch"], 0)

        timestamp_rows = [
            ("m3", "G3", 7, 1, "2026-07-05T09:00:00Z", "2026-07-06 12:00:00"),
            ("m3", "G3", 8, 2, "2026-07-05T09:00:00Z", "2026-07-06 12:00:00"),
        ]
        timestamp_game = uploaded_game_rows_to_team_records(timestamp_rows)[0]
        self.assertLess(timestamp_game["imported_at_epoch"], games[1]["imported_at_epoch"])

    def test_one_uploaded_game_confirms_only_one_duplicate_roll(self):
        history = {}
        for generated in (1000, 1001):
            history = queue_role_ban_roll(
                history, frozenset(("u1", "u2")), frozenset(("u3", "u4")),
                {"u1": "Vanguard", "u2": "Duelist", "u3": "Strategist", "u4": "Vanguard"},
                generated_at_epoch=generated, committed_at_epoch=generated + 1,
            )
        updated, confirmed = reconcile_role_ban_history(history, [{
            "match_uid": "one", "game_label": "G1",
            "team_a": ["u1", "u2"], "team_b": ["u3", "u4"],
            "imported_at_epoch": 1010,
        }])
        self.assertEqual(confirmed, 1)
        self.assertEqual(len(updated["rolls"]), 1)
        self.assertEqual(len(updated["pending_rolls"]), 1)

    def test_role_ban_matrix_uses_confirmed_rolls_only_and_renders(self):
        history = {
            "rolls": [{
                "team_a": ["u1", "u2"], "team_b": ["u3", "u4"],
                "restricted_roles": {"u1": "Vanguard", "u2": "Duelist", "u3": "Strategist", "u4": "Vanguard"},
                "confirmed_match_uid": "m1", "confirmed_game_label": "G1",
            }],
            "pending_rolls": [{
                "team_a": ["u1", "u3"], "team_b": ["u2", "u4"],
                "restricted_roles": {"u1": "Vanguard", "u2": "Duelist", "u3": "Strategist", "u4": "Vanguard"},
                "generated_at_epoch": 10, "committed_at_epoch": 11,
            }],
        }
        report = build_teammate_role_ban_matrix(
            history, {"u1": "Alpha", "u2": "Beta", "u3": "Gamma", "u4": "Delta"}
        )
        self.assertEqual(report["confirmed_rolls"], 1)
        self.assertEqual(report["cells"][("u1", "u2")]["Duelist"], 1)
        self.assertEqual(report["cells"][("u1", "u3")]["Strategist"], 0)
        output = render_teammate_role_ban_matrix(report, 9)
        self.assertGreater(len(output.getvalue()), 0)
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            image.verify()

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

    def test_hero_versatility_deficit_is_higher_for_one_tricks(self):
        one_trick = hero_versatility_deficit({"h1": 7200, "h2": 300})
        broad_pool = hero_versatility_deficit({"h1": 2500, "h2": 2400, "h3": 2300})
        self.assertGreater(one_trick, broad_pool)
        self.assertGreaterEqual(one_trick, 0.0)
        self.assertLessEqual(one_trick, 1.0)

    def test_versatility_penalty_slightly_rewards_low_team_assignment(self):
        deficits = {"a": 0.8, "b": 0.1, "c": 0.0, "d": 0.0, "e": 0.0}
        low_with_one_trick, meta = candidate_versatility_low_team_penalty(
            frozenset(("a", "b")),
            frozenset(("c", "d", "e")),
            frozenset(("a", "b")),
            deficits,
        )
        low_without_one_trick, _ = candidate_versatility_low_team_penalty(
            frozenset(("a", "b", "c")),
            frozenset(("d", "e")),
            frozenset(("d", "e")),
            deficits,
        )
        self.assertLess(low_with_one_trick, low_without_one_trick)
        self.assertGreater(meta["low_team_reward"], 0.0)

    def test_versatility_penalty_is_noop_for_even_games(self):
        score, meta = candidate_versatility_low_team_penalty(
            frozenset(("a", "b")),
            frozenset(("c", "d")),
            None,
            {"a": 1.0},
        )
        self.assertEqual(score, 0.0)
        self.assertEqual(meta["low_team_reward"], 0.0)


if __name__ == "__main__":
    unittest.main()
