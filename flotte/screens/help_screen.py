from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from .. import REPOSITORY_URL, __version__
from .. import shortcuts as shortcut_help
from ..widgets.table_rules import DashedTableFooter
from ..widgets.web_link import WebLink
from ..widgets.worktree_header import WorktreeTable
from .panel import PanelScreen


class HelpScreen(PanelScreen):
    """The documented shortcuts, read off the bindings so the two cannot drift, with the version and the repository."""

    def _sections(self) -> list[tuple[str, tuple[shortcut_help.Shortcut, ...]]]:
        sources = (WorktreeTable.BINDINGS, self.app.BINDINGS)
        return [
            (section, shortcut_help.for_section(section, *sources))
            for section in shortcut_help.SECTIONS
        ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Help", id="dialog-title")
            yield Static("", id="title-separator")

            with Horizontal(id="shortcuts-sections"):
                for section, shortcuts in self._sections():
                    with Vertical(
                        id=f"shortcuts-{section.lower()}", classes="shortcuts-section"
                    ):
                        yield Static(section.upper(), classes="section-title")
                        for shortcut in shortcuts:
                            with Horizontal(classes="shortcut-row"):
                                yield Static(shortcut.key, classes="shortcut-key")
                                yield Static(shortcut.description, classes="shortcut-desc")

            yield DashedTableFooter(id="shortcuts-separator")
            yield Static(
                "Manage docker-compose projects across git worktrees",
                id="help-tagline",
            )
            yield Static("", id="panel-footer-spacer")
            with Horizontal(id="panel-footer"):
                yield Static("esc to close", classes="spacer")
                yield WebLink(REPOSITORY_URL, label="Flotte", id="panel-repository")
                yield Static(__version__, id="panel-version")
