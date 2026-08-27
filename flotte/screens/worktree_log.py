from pathlib import Path
from collections.abc import Callable
import csv

from textual.app import ComposeResult
from textual import events, on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import RichLog, Static
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip

from .. import REPOSITORY_URL, __version__
from ..services.worktree_log import WorktreeLogStore
from ..widgets import DashedTableFooter, WebLink


class HoverRichLog(RichLog):
    """RichLog that highlights the line under the mouse pointer."""

    _hovered_line: int | None = None

    def on_mouse_move(self, event: events.MouseMove) -> None:
        line = self.scroll_offset.y + int(event.y)
        self._set_hovered_line(line if 0 <= line < len(self.lines) else None)

    def on_leave(self) -> None:
        self._set_hovered_line(None)

    def _set_hovered_line(self, line: int | None) -> None:
        if line == self._hovered_line:
            return
        previous_line = self._hovered_line
        self._hovered_line = line
        if previous_line is not None:
            self.refresh_line(previous_line)
        if line is not None:
            self.refresh_line(line)

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if self.scroll_offset.y + y == self._hovered_line:
            return Strip(
                Segment.apply_style(
                    strip,
                    post_style=Style(bgcolor=self.app.theme_colors.bg_light),
                ),
                strip.cell_length,
            )
        return strip


class WorktreeLogScreen(Screen):
    """Scrollable operation log for a worktree."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("b", "back", "Back"),
    ]

    def __init__(
        self,
        worktree_name: str,
        log_path: Path,
        project_name: str,
        show_worktrees: Callable[[], None],
        show_worktree: Callable[[], None],
    ):
        super().__init__()
        self.worktree_name = worktree_name
        self.log_path = log_path
        self.project_name = project_name
        self.show_worktrees = show_worktrees
        self.show_worktree = show_worktree

    def compose(self) -> ComposeResult:
        with Horizontal(id="app-header"):
            with Vertical(id="app-title-group"):
                yield WebLink(REPOSITORY_URL, label="Flotte", id="app-title")
                yield Static(f"v{__version__}", id="app-subtitle")
            yield Static("", id="header-spacer")
            yield Static(self.project_name, id="project-name")
        with Vertical(id="worktree-log-screen"):
            with Horizontal(id="log-breadcrumbs"):
                yield Static("Worktrees", id="log-breadcrumb-worktrees")
                yield Static(">", classes="log-breadcrumb-separator")
                yield Static(self.worktree_name, id="log-breadcrumb-worktree")
                yield Static(">", classes="log-breadcrumb-separator")
                yield Static("Logs", id="log-breadcrumb-current")
            with Horizontal(id="worktree-log-header"):
                yield Static("DateTime", id="worktree-log-datetime")
                yield Static("Log", id="worktree-log-label")
            yield DashedTableFooter(id="worktree-log-rule")
            yield HoverRichLog(wrap=False, markup=False, auto_scroll=False, id="worktree-log")

    def on_mount(self) -> None:
        try:
            with self.log_path.open(encoding="utf-8", newline="") as log_file:
                entries = list(csv.DictReader(log_file))
        except FileNotFoundError:
            return
        except OSError as error:
            entries = [{"error": f"Unable to read log: {error}"}]
        log = self.query_one("#worktree-log", RichLog)
        for entry in reversed(entries):
            log.write(self._format_entry(entry), scroll_end=False)

    def _format_entry(self, entry: dict[str, str]) -> Text:
        if "error" in entry:
            return Text(entry["error"], style=self.app.theme_colors.red)
        rendered = Text(f"{entry['timestamp']:<22}")
        rendered.append(
            entry["action"],
            style=self.app.theme_colors.green
            if entry["status"] == "success"
            else self.app.theme_colors.red,
        )
        duration = WorktreeLogStore.format_duration(float(entry["duration_seconds"]))
        rendered.append(f" [took {duration}]", style=self.app.theme_colors.dim)
        return rendered

    def action_back(self) -> None:
        self.app.pop_screen()

    @on(events.Click, "#log-breadcrumb-worktrees")
    def on_worktrees_clicked(self) -> None:
        self.show_worktrees()

    @on(events.Click, "#log-breadcrumb-worktree")
    def on_worktree_clicked(self) -> None:
        self.show_worktree()
