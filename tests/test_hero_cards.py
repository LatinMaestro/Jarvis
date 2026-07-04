import unittest
from PIL import Image
from jarvis.rendering.hero_cards import _render_hero_synergy_card, _render_hero_tierlist_card

class HeroCardTests(unittest.TestCase):
    def test_cards_are_fixed_size_pngs(self):
        outputs = [
            _render_hero_tierlist_card(8, "Humans", [], 3, 1, 1, 0),
            _render_hero_synergy_card(8, "Humans", [], 3, 1, 1),
        ]
        for output in outputs:
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1500, 980))
                image.verify()

if __name__ == "__main__": unittest.main()
