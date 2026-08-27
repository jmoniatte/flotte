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
        except (OSError, csv.Error) as error:
            entries = [{"error": f"Unable to read log: {error}"}]
        log = self.query_one("#worktree-log", RichLog)
        malformed_entries = 0
        for entry in reversed(entries):
            rendered = self._format_entry(entry)
            if rendered is None:
                malformed_entries += 1
            else:
                log.write(rendered, scroll_end=False)
        if malformed_entries:
            log.write(
                Text(
                    f"Skipped {malformed_entries} malformed log entr"
                    f"{'y' if malformed_entries == 1 else 'ies'}",
                    style=self.app.theme_colors.red,
                ),
                scroll_end=False,
            )

    def _format_entry(self, entry: dict[str, str | None]) -> Text | None:
        if "error" in entry:
            return Text(entry["error"], style=self.app.theme_colors.red)
        timestamp = entry.get("timestamp")
        action = entry.get("action")
        status = entry.get("status")
        duration_seconds = entry.get("duration_seconds")
        if (
            not all(isinstance(value, str) for value in (timestamp, action, status, duration_seconds))
            or status not in ("success", "failed")
        ):
            return None
        try:
            duration = WorktreeLogStore.format_duration(float(duration_seconds))
        except ValueError:
            return None
        rendered = Text(f"{timestamp:<22}")
        rendered.append(
            action,
            style=self.app.theme_colors.green
            if status == "success"
            else self.app.theme_colors.red,
        )
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
