from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Static
from textual.app import ComposeResult

from .. import REPOSITORY_URL, __version__
from ..widgets.table_rules import DashedTableFooter
from ..widgets.web_link import WebLink


class HelpScreen(ModalScreen):
    """Modal screen showing keyboard shortcuts."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Keyboard Shortcuts", id="dialog-title")
            yield Static("", id="title-separator")

            with Horizontal(id="help-sections"):
                with Vertical(id="help-actions", classes="help-section"):
                    yield Static("ACTIONS", classes="section-title")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("enter", classes="shortcut-key")
                        yield Static("Open selected worktree", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("n", classes="shortcut-key")
                        yield Static("Create worktree", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("d", classes="shortcut-key")
                        yield Static("Delete worktree", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("s", classes="shortcut-key")
                        yield Static("Start services", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("x", classes="shortcut-key")
                        yield Static("Stop services", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("r", classes="shortcut-key")
                        yield Static("Refresh status", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("R", classes="shortcut-key")
                        yield Static("Go Ride", classes="shortcut-desc")

                with Vertical(id="help-general", classes="help-section"):
                    yield Static("GENERAL", classes="section-title")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("q", classes="shortcut-key")
                        yield Static("Quit", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("b / esc", classes="shortcut-key")
                        yield Static("Back to worktrees", classes="shortcut-desc")
                    with Horizontal(classes="shortcut-row"):
                        yield Static("?", classes="shortcut-key")
                        yield Static("Show help", classes="shortcut-desc")

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
