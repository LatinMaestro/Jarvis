import unittest

from jarvis.stats.profile_analytics import (
    build_snapshot_rows,
    collect_hero_ids,
    current_streak,
    form_string,
    percentile,
    pick_best_role,
    role_bucket,
    signature_heroes,
    streak_text,
)


class ProfileAnalyticsTests(unittest.TestCase):
    def test_form_and_streak_helpers(self):
        sequence = [1, 0, 1, 1]
        self.assertEqual(form_string(sequence, 4), "WLWW")
        self.assertEqual(form_string(sequence, 5), "N/A")
        self.assertEqual(current_streak(sequence), 2)
        self.assertEqual(current_streak([1, 0, 0]), -2)
        self.assertEqual(streak_text(-2), "2L")

    def test_percentile_and_role_selection(self):
        self.assertEqual(percentile([1, 2, 3], 2), 50.0)
        self.assertEqual(role_bucket("main strategist"), "Strategist")
        best = pick_best_role({"Vanguard": {"games": 4, "win_pct": 50}, "Duelist": {"games": 5, "win_pct": 60}})
        self.assertEqual(best["role"], "Duelist")

    def test_signature_sort_and_hero_collection(self):
        heroes = [{"hero_id": 1, "games": 5, "win_pct": 60, "seconds": 100}, {"hero_id": 2, "games": 8, "win_pct": 50, "seconds": 500}]
        self.assertEqual(signature_heroes(heroes, limit=1)[0]["hero_id"], 1)
        pack = {"signature_heroes": heroes[:1], "enemy_bans": {"top": [{"hero_id": 2}]}, "teammate_hero_win": [{"hero_id": 3}], "teammate_hero_risk": [{"hero_id": 4}]}
        self.assertEqual(collect_hero_ids(pack), {1, 2, 3, 4})

    def test_snapshot_rows_preserve_metric_order(self):
        mine = {"win_pct": 50.0, "kda": 2.0, "deaths_pg": 3.0, "dmg_pg": 100.0, "heal_pg": 20.0, "taken_pg": 50.0, "fh_pg": 4.0, "sk_pg": 1.0, "acc": None}
        rows = build_snapshot_rows({1: mine}, mine, enable_pct=True)
        self.assertEqual([row["label"] for row in rows], ["Win %", "KDA", "Deaths / G", "Damage / G", "Healing / G", "Taken / G", "Final Hits / G", "Solo Kills / G", "Accuracy"])
        self.assertIsNone(rows[-1]["pct"])


if __name__ == "__main__":
    unittest.main()
