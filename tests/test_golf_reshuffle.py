import sqlite3
import unittest

from jarvis.stats.golf_reshuffle import (
    ensure_golf_tables, adjust_credits, available_credits, credit_balances,
    eligible_champions, claim_credit, refund_credit, valid_golf_choices,
    satisfies_golf_choices,
)


class GolfReshuffleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        ensure_golf_tables(self.db)
        self.active = {f"u{i}" for i in range(1, 9)}

    def tearDown(self):
        self.db.close()

    def test_awards_add_and_persist_season_balance(self):
        self.assertEqual(adjust_credits(self.db, 10, 8, 101, 2), 2)
        self.assertEqual(adjust_credits(self.db, 10, 8, 101, 1), 3)
        self.assertEqual(available_credits(self.db, 10, 8, 101), 3)
        self.assertEqual(available_credits(self.db, 10, 9, 101), 0)
        self.assertEqual(available_credits(self.db, 11, 8, 101), 0)

    def test_credit_claim_is_atomic_and_exhausts(self):
        adjust_credits(self.db, 10, 8, 101, 1)
        self.assertTrue(claim_credit(self.db, 10, 8, 101))
        self.assertFalse(claim_credit(self.db, 10, 8, 101))
        self.assertEqual(available_credits(self.db, 10, 8, 101), 0)

    def test_refund_after_send_failure(self):
        adjust_credits(self.db, 10, 8, 101, 1)
        self.assertTrue(claim_credit(self.db, 10, 8, 101))
        refund_credit(self.db, 10, 8, 101)
        self.assertEqual(available_credits(self.db, 10, 8, 101), 1)

    def test_remove_only_unspent_credits(self):
        adjust_credits(self.db, 10, 8, 101, 3)
        self.assertTrue(claim_credit(self.db, 10, 8, 101))
        self.assertEqual(adjust_credits(self.db, 10, 8, 101, -2), 0)
        with self.assertRaises(ValueError):
            adjust_credits(self.db, 10, 8, 101, -1)

    def test_only_eligible_champions_and_minimum_eight(self):
        balances = {"u1": 2, "u2": 0, "u3": 1, "u9": 4}
        self.assertEqual(eligible_champions(balances, self.active), {"u1": 2, "u3": 1})
        self.assertEqual(eligible_champions(balances, set(list(self.active)[:7])), {})
        self.assertEqual(eligible_champions(balances, self.active, "u1"), {"u3": 1})
        self.assertEqual(eligible_champions({"u1": 2}, self.active, "u1"), {})

    def test_valid_choices_require_three_distinct_active_members(self):
        self.assertTrue(valid_golf_choices(self.active, "u1", "u2", "u3"))
        self.assertFalse(valid_golf_choices(self.active, "u1", "u1", "u3"))
        self.assertFalse(valid_golf_choices(self.active, "u1", "u2", "u9"))
        self.assertFalse(valid_golf_choices(set(list(self.active)[:7]), "u1", "u2", "u3"))

    def test_constraints_work_with_either_team_side(self):
        a, b = {"u1", "u2", "u4", "u5"}, {"u3", "u6", "u7", "u8"}
        self.assertTrue(satisfies_golf_choices(a, b, "u1", "u2", "u3"))
        self.assertTrue(satisfies_golf_choices(b, a, "u1", "u2", "u3"))
        self.assertFalse(satisfies_golf_choices(a, b, "u1", "u3", "u2"))

    def test_balances_reflect_spent_not_original_award(self):
        adjust_credits(self.db, 10, 8, 1, 3)
        adjust_credits(self.db, 10, 8, 2, 1)
        claim_credit(self.db, 10, 8, 1)
        self.assertEqual(credit_balances(self.db, 10, 8), {"u1": 2, "u2": 1})


    def test_golf_reshuffle_rebuilds_role_bans_normally(self):
        """Golf choices filter teams; the existing role-ban builder runs afresh."""
        import ast
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
        tree = ast.parse(source)
        roll = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_next_teams_roll"
        )
        role_builder_calls = [
            node for node in ast.walk(roll)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_nt_build_restricted_roles_for_roll"
        ]
        self.assertEqual(len(role_builder_calls), 1)
        self.assertTrue(
            any(isinstance(n, ast.Name) and n.id == "satisfies_golf_choices"
                for n in ast.walk(roll))
        )
        self.assertIn('"restricted_roles": dict(restricted_roles or {})', source)

    def test_paid_reshuffle_excludes_identical_pending_split(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
        self.assertIn("matchup_key(team_a, team_b) == matchup_key(old_a, old_b)", source)
        self.assertIn("if golf_constraints:", source)

    def test_golf_constraints_do_not_auto_disable_hard_pair_lock(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text()
        self.assertIn(
            "if not best_heap and pair_lock_enforced and not golf_constraints:",
            source,
        )

if __name__ == "__main__":
    unittest.main()
