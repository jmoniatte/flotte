from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Static
from textual.app import ComposeResult


class HelpScreen(ModalScreen):
    """Modal screen showing keyboard shortcuts."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Keyboard Shortcuts", id="dialog-title")
            yield Static("", id="title-separator")

            yield Static("ACTIONS", classes="section-title")
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

            yield Static("GENERAL", classes="section-title-spaced")
            with Horizontal(classes="shortcut-row"):
                yield Static("q", classes="shortcut-key")
                yield Static("Quit", classes="shortcut-desc")
            with Horizontal(classes="shortcut-row"):
                yield Static("?", classes="shortcut-key")
                yield Static("Show help", classes="shortcut-desc")

            yield Static("Press any key to close", id="help-footer")

    def on_key(self, event) -> None:
        """Dismiss on any key press."""
        self.dismiss()

    def on_click(self, event) -> None:
        """Also dismiss on click for convenience."""
        self.dismiss()
