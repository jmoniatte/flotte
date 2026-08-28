from textual.content import Content
from textual.notifications import Notification
from textual.timer import Timer
from textual.widgets import Static


class HeaderNotification(Static):
    """Display the latest application notification in the header."""

    def __init__(self) -> None:
        super().__init__("")
        self.display = False
        self._clear_timer: Timer | None = None

    def show_notification(self, notification: Notification) -> None:
        if self._clear_timer is not None:
            self._clear_timer.stop()
        message = (
            Content.from_markup(notification.message)
            if notification.markup
            else Content(notification.message)
        )
        content = (
            Content.assemble(notification.title, "\n", message)
            if notification.title
            else message
        )
        self.set_classes(f"-{notification.severity}")
        self.update(content)
        self.display = True
        self._clear_timer = self.set_timer(
            max(notification.time_left, 0), self.clear_notification
        )

    def clear_notification(self) -> None:
        self.display = False
        self.update("")
        self._clear_timer = None
