from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Select, Static

from .. import REPOSITORY_URL, __version__
from .. import shortcuts as shortcut_help
from ..theme import effective_theme, selectable_themes
from ..widgets.table_rules import DashedTableFooter
from ..widgets.web_link import WebLink
from ..widgets.worktree_header import WorktreeTable


class SettingsScreen(ModalScreen):
    """Modal screen for app settings and the documented keyboard shortcuts."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def _sections(self) -> list[tuple[str, tuple[shortcut_help.Shortcut, ...]]]:
        """Read the shortcuts off the bindings, so the two cannot drift."""
        sources = (WorktreeTable.BINDINGS, self.app.BINDINGS)
        return [
            (section, shortcut_help.for_section(section, *sources))
            for section in shortcut_help.SECTIONS
        ]

    def compose(self) -> ComposeResult:
        with Vertical():
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

            yield DashedTableFooter(id="settings-theme-separator")

            with Horizontal(id="shortcuts-sections"):
                for section, shortcuts in self._sections():
                    with Vertical(
                        id=f"shortcuts-{section.lower()}", classes="shortcuts-section"
                    ):
                        yield Static(section.upper(), classes="section-title")
                        for shortcut in shortcuts:
                            with Horizontal(classes="shortcut-row"):
                                yield Static(shortcut.key, classes="shortcut-key")
                                yield Static(shortcut.description, classes="shortcut-desc")

            yield DashedTableFooter(id="shortcuts-separator")
            yield Static(
                "Manage docker-compose projects across git worktrees",
                id="settings-tagline",
            )
            yield Static("", id="settings-footer-spacer")
            with Horizontal(id="settings-footer"):
                yield Static("esc to close", classes="spacer")
                yield WebLink(REPOSITORY_URL, label="Flotte", id="settings-repository")
                yield Static(__version__, id="settings-version")

    @on(Select.Changed, "#theme-selector")
    def on_theme_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.value is not Select.BLANK:
            self.app.set_theme(event.value)

    def on_click(self, event) -> None:
        """Dismiss on a click outside the dialog, but let the dropdown work."""
        if event.widget is self:
            self.dismiss()
