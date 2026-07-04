import unittest
from PIL import Image, ImageDraw
from jarvis.rendering.fonts import get_fonts
from jarvis.rendering.season_story import _ss_draw_role_ternary_plot

class SeasonStoryRendererTests(unittest.TestCase):
    def test_role_plot_draws_on_existing_canvas(self):
        image = Image.new("RGB", (600, 500), (20, 20, 26))
        draw = ImageDraw.Draw(image)
        font, _ = get_fonts(body_pt=18, title_pt=24)
        _ss_draw_role_ternary_plot(
            draw, 20, 20, 560, 450,
            [{"player_uid": 1, "v": 0.5, "d": 0.3, "s": 0.2}],
            {1: "Alpha"}, font, 24,
            (255, 215, 0), (235, 235, 235), (180, 180, 200), (80, 80, 100),
        )
        self.assertNotEqual(image.getbbox(), None)

if __name__ == "__main__": unittest.main()
