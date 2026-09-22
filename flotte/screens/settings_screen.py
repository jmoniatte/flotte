from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Select, Static

from ..theme import effective_theme, selectable_themes
from .panel import PanelScreen


class SettingsScreen(PanelScreen):
    """The theme; the shortcuts are on the Help panel."""

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-panel"):
            yield Static("Settings", id="dialog-title")
            yield Static("", id="title-separator")

            with Horizontal(id="settings-theme-row"):
                yield Static("Theme", id="settings-theme-label")
                yield Select(
                    options=[(name, name) for name in selectable_themes()],
                    value=effective_theme(self.app.config.theme),
                    id="theme-selector",
                    allow_blank=False,
                )

            yield Static("", id="panel-footer-spacer")
            with Horizontal(id="panel-footer"):
                yield Static("esc to close", classes="spacer")

    @on(Select.Changed, "#theme-selector")
    def on_theme_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.value is not Select.BLANK:
            self.app.set_theme(event.value)
