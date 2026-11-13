"""Check that the Discord command remains factual and backwards compatible."""

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class SeasonMovieCommandContractTests(unittest.TestCase):
    def test_command_keeps_its_name_and_returns_a_factual_zip(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8-sig")
        section = source.split("# !season_movie_pack — factual, season-scoped export (ZIP)", 1)[1]
        section = section.split("# !run_all_stats —", 1)[0]
        self.assertIn('@bot.command(name="season_movie_pack")', section)
        self.assertIn("async def season_movie_pack(ctx, season_id: int = None):", section)
        self.assertIn("build_season_data_export(c, sid)", section)
        self.assertIn('filename=f"season_database_s{sid}.zip"', section)
        self.assertNotIn("_smp_build_movie_pack_md", section)
        self.assertNotIn("cinematic season story", section)

    def test_command_is_registered_exactly_once(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8-sig")
        self.assertEqual(source.count('@bot.command(name="season_movie_pack")'), 1)


if __name__ == "__main__":
    unittest.main()
