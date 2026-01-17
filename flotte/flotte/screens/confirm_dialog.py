from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Button
from textual.app import ComposeResult


class ConfirmDialog(ModalScreen[bool]):
    """Reusable confirmation dialog modal. Returns True if confirmed, False if cancelled."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(
        self,
        message: str,
        title: str = "Confirm",
        confirm_label: str = "Yes",
        cancel_label: str = "No"
    ):
        super().__init__()
        self.message = message
        self.dialog_title = title
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[bold]{self.dialog_title}[/bold]", id="dialog-title")
            yield Static(self.message, id="dialog-message")
            with Horizontal(id="dialog-buttons"):
                yield Button(self.cancel_label, id="cancel-btn")
                yield Button(self.confirm_label, id="confirm-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-btn")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
