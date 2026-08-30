from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Static
from textual.app import ComposeResult

from .. import shortcuts as shortcut_help
from .. import REPOSITORY_URL, __version__
from ..widgets.table_rules import DashedTableFooter
from ..widgets.web_link import WebLink
from ..widgets.worktree_header import WorktreeTable


class HelpScreen(ModalScreen):
    """Modal screen listing every documented keyboard shortcut."""

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
            yield Static("Keyboard Shortcuts", id="dialog-title")
            yield Static("", id="title-separator")

            with Horizontal(id="help-sections"):
                for section, shortcuts in self._sections():
                    with Vertical(id=f"help-{section.lower()}", classes="help-section"):
                        yield Static(section.upper(), classes="section-title")
                        for shortcut in shortcuts:
                            with Horizontal(classes="shortcut-row"):
                                yield Static(shortcut.key, classes="shortcut-key")
                                yield Static(shortcut.description, classes="shortcut-desc")

            yield DashedTableFooter(id="help-sections-separator")
            yield Static("Manage docker-compose projects across git worktrees", id="help-tagline")
            yield Static("", id="help-footer-spacer")
            with Horizontal(id="help-footer"):
                yield Static("", classes="spacer")
                yield WebLink(REPOSITORY_URL, label="Flotte", id="help-repository")
                yield Static(f"v{__version__}", id="help-version")

    def on_key(self, event) -> None:
        """Dismiss on any key press."""
        self.dismiss()

    def on_click(self, event) -> None:
        """Also dismiss on click for convenience."""
        self.dismiss()
