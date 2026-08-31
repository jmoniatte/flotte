from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from .. import REPOSITORY_URL, __version__
from .header_notification import HeaderNotification
from .web_link import WebLink


class AppHeader(Horizontal):
    """The title bar every screen shares, plus whatever that screen puts on the right."""

    def __init__(self, *trailing: Widget, **kwargs) -> None:
        super().__init__(id="app-header", **kwargs)
        self._trailing = trailing

    def compose(self) -> ComposeResult:
        with Vertical(id="app-title-group"):
            yield WebLink(REPOSITORY_URL, label="Flotte", id="app-title")
            yield Static(f"v{__version__}", id="app-subtitle")
        yield Static("", classes="header-notification-spacer")
        yield HeaderNotification()
        yield Static("", id="header-spacer")
        yield from self._trailing
