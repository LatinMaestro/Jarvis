import unittest

from PIL import Image

from jarvis.rendering.role_distribution import _rd_render_role_bar_chart


class RoleDistributionRendererTests(unittest.TestCase):
    def test_all_role_charts_are_readable_fixed_size_pngs(self):
        rows = [
            {"player_uid": 1, "v": 0.5, "d": 0.3, "s": 0.2},
            {"player_uid": 2, "v": 0.2, "d": 0.4, "s": 0.4},
        ]
        names = {1: "Alpha", 2: "Beta"}
        for label, key in (
            ("Vanguard", "v"),
            ("Duelist", "d"),
            ("Strategist", "s"),
        ):
            output = _rd_render_role_bar_chart(
                season_id=8,
                role_label=label,
                role_key=key,
                role_rows=rows,
                player_names=names,
            )
            self.assertGreater(len(output.getvalue()), 0)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1850, 900))
                image.verify()


if __name__ == "__main__":
    unittest.main()
