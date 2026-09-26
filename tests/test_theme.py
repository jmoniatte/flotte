import re
import unittest

from tui_kit.theme import list_themes, load_palette

from flotte.app import load_stylesheet
from flotte.colors import theme_colors


class ThemeTest(unittest.TestCase):
    def test_every_theme_fills_each_variable_the_stylesheets_use(self):
        required = set(re.findall(r"\$([\w-]+)", load_stylesheet()))
        self.assertIn("bg-dark", required)
        for name in list_themes():
            with self.subTest(theme=name):
                self.assertEqual(required - set(load_palette(name)), set())

    def test_the_rich_colors_come_from_the_palette(self):
        palette = load_palette("dracula")
        colors = theme_colors(palette)
        self.assertEqual(colors.red, palette["red"])
        self.assertEqual(colors.dim, palette["comment"])


if __name__ == "__main__":
    unittest.main()
