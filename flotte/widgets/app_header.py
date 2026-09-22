from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from .. import __version__
from .header_notification import HeaderNotification


class HelpRequested(Message):
    """The logo in the header was clicked."""


class TitleLink(Static):
    """The app's name; clicking it opens Help, like ? does."""

    def on_click(self) -> None:
        self.post_message(HelpRequested())


class AppHeader(Horizontal):
    """The title bar every screen shares, plus whatever that screen puts on the right."""

    def __init__(self, *trailing: Widget, **kwargs) -> None:
        super().__init__(id="app-header", **kwargs)
        self._trailing = trailing

    def compose(self) -> ComposeResult:
        with Vertical(id="app-title-group"):
            yield TitleLink("Flotte", id="app-title")
            yield Static(__version__, id="app-subtitle")
        yield Static("", classes="header-notification-spacer")
        yield HeaderNotification()
        yield Static("", id="header-spacer")
        yield from self._trailing
