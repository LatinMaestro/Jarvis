import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jarvis.stats.profile_data import (
    get_accuracy_by_player,
    get_all_player_metrics,
    get_chemistry,
    get_enemy_bans,
    get_hero_stats,
    get_momentum_last_n,
    get_role_mix_and_role_wr,
    get_season_totals,
    get_teammate_hero_wr_lists,
    get_win_seq_by_import_time,
    load_hero_roles,
)


class ProfileDataSnapshotTests(unittest.TestCase):
    def test_all_profile_reads_work_against_copied_snapshot(self):
        source = Path(__file__).resolve().parents[1] / "marvel_rivals_stats.db"
        with tempfile.TemporaryDirectory() as temp_dir:
            copied = Path(temp_dir) / "profile-fixture.db"
            shutil.copy2(source, copied)
            connection = sqlite3.connect(copied)
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT season_id, player_uid FROM mr_player_match "
                    "WHERE COALESCE(is_bot, 0)=0 ORDER BY season_id DESC, rowid LIMIT 1"
                )
                season_id, player_uid = cursor.fetchone()

                totals = get_season_totals(cursor, season_id, player_uid)
                metrics = get_all_player_metrics(cursor, season_id)
                accuracy = get_accuracy_by_player(cursor, season_id)
                roles = load_hero_roles(cursor)
                role_share, role_winrates = get_role_mix_and_role_wr(
                    cursor, season_id, player_uid, roles
                )

                self.assertGreater(totals["games"], 0)
                self.assertIsInstance(metrics, dict)
                self.assertIsInstance(accuracy, dict)
                self.assertEqual(
                    set(role_share), {"Vanguard", "Duelist", "Strategist"}
                )
                self.assertEqual(set(role_winrates), set(role_share))
                self.assertIsInstance(get_hero_stats(cursor, season_id, player_uid), list)
                self.assertIsInstance(
                    get_win_seq_by_import_time(cursor, season_id, player_uid), list
                )
                self.assertIn(
                    "games", get_momentum_last_n(cursor, season_id, player_uid)
                )
                self.assertIn("best", get_chemistry(cursor, season_id, player_uid))
                self.assertIn("top", get_enemy_bans(cursor, season_id, player_uid))
                best, worst = get_teammate_hero_wr_lists(
                    cursor, season_id, player_uid
                )
                self.assertIsInstance(best, list)
                self.assertIsInstance(worst, list)
            finally:
                cursor.close()
                connection.close()


if __name__ == "__main__":
    unittest.main()
