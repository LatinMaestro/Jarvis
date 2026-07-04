import unittest

from PIL import Image

from jarvis.rendering.top3_more import _top3_more_render_image


class Top3MoreRendererTests(unittest.TestCase):
    def test_empty_report_is_readable_png(self):
        output = _top3_more_render_image(8, ["A", "B", "C"], {"rows": [], "summary": {}})
        self.assertGreater(len(output.getvalue()), 0)
        with Image.open(output) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (2500, 1100))
            image.verify()


if __name__ == "__main__":
    unittest.main()
