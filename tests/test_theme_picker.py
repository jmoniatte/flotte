import asyncio
import unittest
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from flotte.screens import ThemePicker
from flotte.theme import load_palette

BASE_TCSS = Path("flotte/styles/base.tcss").read_text()


class PickerApp(App):
    """Minimal host that serves the palette the way FlotteApp does."""

    CSS = BASE_TCSS

    def __init__(self, theme: str = "onedark") -> None:
        self._palette = load_palette(theme)
        super().__init__()
        self.applied: list[str] = []
        self.result: str | None | object = "unset"

    def compose(self) -> ComposeResult:
        yield Static("host")

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **self._palette}

    def apply_theme(self, name: str) -> None:
        self.applied.append(name)
        self._palette = load_palette(name)
        self.refresh_css()


class ThemePickerTests(unittest.TestCase):
    def _run(self, body):
        async def main():
            app = PickerApp()
            async with app.run_test() as pilot:
                app.push_screen(
                    ThemePicker("onedark"),
                    callback=lambda value: setattr(app, "result", value),
                )
                await pilot.pause()
                await body(app, pilot)
            return app

        return asyncio.run(main())

    def test_highlighting_a_row_applies_it_and_enter_keeps_it(self):
        async def body(app, pilot):
            picker = app.screen
            # Opens on the configured theme, already applied.
            self.assertEqual(app.applied[-1], "onedark")
            table = picker.query_one("#theme-table", DataTable)
            self.assertEqual(table.row_count, len(picker._names))

            await pilot.press("down")
            await pilot.pause()
            moved = app.applied[-1]
            self.assertNotEqual(moved, "onedark")

            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.result, moved)

        self._run(body)

    def test_filtering_narrows_the_list_and_applies_the_first_match(self):
        async def body(app, pilot):
            picker = app.screen
            picker.query_one("#theme-filter", Input).focus()
            await pilot.press(*"dracula")
            await pilot.pause()
            self.assertEqual(picker._names, ["dracula"])
            self.assertEqual(app.applied[-1], "dracula")

        self._run(body)

    def test_escape_restores_the_theme_the_picker_opened_with(self):
        async def body(app, pilot):
            picker = app.screen
            surface = picker.query_one(Vertical).styles.background
            await pilot.press("down", "down")
            await pilot.pause()
            self.assertNotEqual(picker.query_one(Vertical).styles.background, surface)

            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.applied[-1], "onedark")
            self.assertIsNone(app.result)
            self.assertEqual(app._palette, load_palette("onedark"))

        self._run(body)


if __name__ == "__main__":
    unittest.main()


class FlotteAppThemeTests(unittest.TestCase):
    """The real app serves the palette from get_css_variables so it can be swapped."""

    def test_apply_theme_swaps_variables_and_rich_colors(self):
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "config.yaml"
            config_file.write_text("theme: onedark\n")
            with patch("flotte.config.CONFIG_FILE", config_file):
                from flotte.app import FlotteApp

                app = FlotteApp()

        onedark, dracula = load_palette("onedark"), load_palette("dracula")
        self.assertEqual(app.get_css_variables()["bg"], onedark["bg"])
        self.assertNotIn("$bg:", app.CSS)  # variables must not be baked in

        async def main():
            async with app.run_test() as pilot:
                app.apply_theme("dracula")
                await pilot.pause()

        asyncio.run(main())
        self.assertEqual(app.get_css_variables()["bg"], dracula["bg"])
        self.assertEqual(app.theme_colors.red, dracula["red"])
