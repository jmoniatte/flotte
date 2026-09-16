import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flotte.theme import (
    BASE16_SLOTS,
    list_themes,
    load_palette,
    palette_to_tcss,
    read_scheme,
    resolve_theme,
    theme_colors,
)

BASE_TCSS = Path(__file__).resolve().parents[1] / "flotte" / "styles" / "base.tcss"
HEX = re.compile(r"^#[0-9a-f]{6}$")

ACCENTS = {
    "base08": "#f38ba8", "base09": "#fab387", "base0A": "#f9e2af", "base0B": "#a6e3a1",
    "base0C": "#94e2d5", "base0D": "#89b4fa", "base0E": "#cba6f7", "base0F": "#f2cdcd",
}
# Ramp runs dark -> light; base16 reverses it for light schemes.
DARK = dict(ACCENTS, base00="#1e1e2e", base01="#2a2a3c", base02="#363648",
            base03="#6c7086", base04="#7f849c", base05="#cdd6f4", base06="#dce0f0",
            base07="#eceff5")
LIGHT = dict(ACCENTS, base00="#fafafa", base01="#f0f0f1", base02="#e5e5e6",
             base03="#a0a1a7", base04="#696c77", base05="#383a42", base06="#202227",
             base07="#090a0b")


def _write(directory, scheme, nested=True):
    path = Path(directory) / "scheme.yaml"
    body = "\n".join(f'  {slot}: "{value}"' for slot, value in scheme.items())
    path.write_text("palette:\n" + body if nested else body.replace("  ", ""))
    return path


def _red(value):
    return int(value[1:3], 16)


class ReadSchemeTest(unittest.TestCase):
    def test_accepts_both_spec_layouts_and_bare_hex(self):
        with tempfile.TemporaryDirectory() as directory:
            nested = read_scheme(_write(directory, DARK))
            flat = read_scheme(_write(directory, DARK, nested=False))
            bare = read_scheme(
                _write(directory, {k: v.lstrip("#") for k, v in DARK.items()})
            )
        self.assertEqual(nested, flat)
        self.assertEqual(nested, bare)
        self.assertEqual(set(nested), set(BASE16_SLOTS))
        self.assertEqual(nested["base00"], (0x1E, 0x1E, 0x2E))

    def test_missing_slot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = {k: v for k, v in DARK.items() if k != "base0F"}
            with self.assertRaisesRegex(ValueError, "base0F"):
                read_scheme(_write(directory, partial))


class DerivedSurfacesTest(unittest.TestCase):
    """bg-dark and gutter have no base16 slot; they come off the greyscale ramp."""

    def _palette(self, scheme):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(directory, scheme)
            with patch("flotte.theme.THEMES_DIR", path.parent):
                return load_palette("scheme")

    def test_recessed_surface_is_darker_than_background_in_both_variants(self):
        for variant, scheme in (("dark", DARK), ("light", LIGHT)):
            with self.subTest(variant=variant):
                palette = self._palette(scheme)
                self.assertLess(_red(palette["bg-dark"]), _red(palette["bg"]))
                self.assertGreaterEqual(
                    _red(palette["bg"]) - _red(palette["bg-dark"]), 3
                )

    def test_dark_scheme_overshoots_the_ramp_rather_than_using_base01(self):
        palette = self._palette(DARK)
        self.assertEqual(palette["bg-dark"], "#181827")
        self.assertEqual(palette["bg"], DARK["base00"])

    def test_light_scheme_uses_the_recessed_slot_the_author_chose(self):
        self.assertEqual(self._palette(LIGHT)["bg-dark"], LIGHT["base01"])

    def test_dark_scheme_with_a_recessed_base01_uses_it_rather_than_overshooting(self):
        """Catppuccin and Dracula spend base01 on a surface below the background."""
        scheme = dict(DARK, base01="#181825")
        self.assertEqual(self._palette(scheme)["bg-dark"], "#181825")

    def test_background_at_the_end_of_the_ramp_falls_back_to_base01(self):
        palette = self._palette(dict(DARK, base00="#000000", base01="#0a0a0a"))
        self.assertEqual(palette["bg-dark"], "#0a0a0a")

    def test_gutter_sits_between_selection_background_and_comments(self):
        for variant, scheme in (("dark", DARK), ("light", LIGHT)):
            with self.subTest(variant=variant):
                palette = self._palette(scheme)
                edges = sorted((_red(palette["bg-light"]), _red(palette["comment"])))
                self.assertTrue(edges[0] < _red(palette["gutter"]) < edges[1])


class InstalledThemesTest(unittest.TestCase):
    def test_every_theme_fills_each_variable_base_tcss_uses(self):
        required = set(re.findall(r"\$([\w-]+)", BASE_TCSS.read_text()))
        self.assertIn("bg-dark", required)
        installed = list_themes()
        self.assertIn("onedark", installed)
        for name in installed:
            with self.subTest(theme=name):
                palette = load_palette(name)
                self.assertEqual(required - set(palette), set())
                for var, value in palette.items():
                    self.assertRegex(value, HEX, f"{name}.{var}")
                self.assertEqual(len(palette_to_tcss(palette).splitlines()), len(palette))
                self.assertEqual(theme_colors(palette).dim, palette["comment"])

    def test_unknown_theme_falls_back_to_the_default(self):
        self.assertEqual(load_palette("no-such-theme"), load_palette("onedark"))

    def test_theme_names_are_upstream_slugs_verbatim(self):
        self.assertIsNone(resolve_theme("no-such-theme"))
        self.assertIsNone(resolve_theme("onelight"))  # ours once; never base16's
        self.assertEqual(resolve_theme("one-light"), "one-light")
        self.assertEqual(resolve_theme("onedark"), "onedark")


if __name__ == "__main__":
    unittest.main()
