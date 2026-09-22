from textual.screen import ModalScreen


class PanelScreen(ModalScreen):
    """A panel over the app: Escape or a click outside closes it. Settings and Help are panels."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def on_click(self, event) -> None:
        """Dismiss on a click outside the panel, but let a dropdown inside it work."""
        if event.widget is self:
            self.dismiss()
