from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Button
from textual.reactive import reactive
from textual.css.query import NoMatches


class ErrorView(Vertical):
    """Shows an error message with dismiss button."""

    message: reactive[str] = reactive("")

    def compose(self):
        yield Static(id="error-message")
        with Horizontal(id="error-buttons"):
            yield Button("Dismiss", id="btn-error-dismiss")

    def watch_message(self, value: str) -> None:
        """Update the error message display."""
        try:
            self.query_one("#error-message", Static).update(
                f"[bold red]Error:[/bold red] {value}"
            )
        except NoMatches:
            pass  # Widget not mounted yet

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle dismiss button."""
        if event.button.id == "btn-error-dismiss":
            # ErrorView is no longer used for operation errors (using notifications instead)
            # This is kept for potential future use
            self.display = False
