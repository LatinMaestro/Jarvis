import unittest
import pandas
from PIL import Image
from jarvis.rendering.session_pairs import _render_session_pairs_underdog_image_api

class SessionPairsRendererTests(unittest.TestCase):
    def test_empty_session_page_is_readable_png(self):
        output = _render_session_pairs_underdog_image_api(
            "2026-07-01", [], pandas.DataFrame(), {}, [],
            {"games": 0}, {"wins": 0}, [], [], []
        )
        self.assertGreater(len(output.getvalue()), 0)
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            image.verify()

if __name__ == "__main__": unittest.main()
