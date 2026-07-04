import unittest
import pandas
from PIL import Image
from jarvis.rendering.session_overview import render_session_overview

class SessionOverviewRendererTests(unittest.TestCase):
    def test_empty_tables_render_without_role_lookup(self):
        called = []
        output = render_session_overview(
            "2026-07-01", [], pandas.DataFrame(), pandas.DataFrame(),
            get_season_id=lambda: 8,
            load_role_distribution=lambda *args, **kwargs: called.append(True),
        )
        self.assertEqual(called, [])
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            image.verify()

if __name__ == "__main__": unittest.main()
