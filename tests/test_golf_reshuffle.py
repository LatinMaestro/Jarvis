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


if __name__ == "__main__":
    unittest.main()
