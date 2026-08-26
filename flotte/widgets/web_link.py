from textual.widgets import Link

from ..formatters import display_web_url


class WebLink(Link):
    """A consistently styled, non-focusable URL link."""

    can_focus = False

    def __init__(self, url: str | None = None, **kwargs) -> None:
        super().__init__(display_web_url(url), url=url or "", **kwargs)
        self.display = bool(url)

    def set_url(self, url: str | None) -> None:
        self.text = display_web_url(url)
        self.url = url or ""
        self.display = bool(url)
