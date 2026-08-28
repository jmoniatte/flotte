from pathlib import Path
from collections.abc import Callable
import csv
from datetime import datetime, tzinfo

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
from ..widgets import DashedTableFooter, HeaderNotification, WebLink


def _local_timezone_name() -> str:
    return datetime.now().astimezone().tzname() or "Local"


def _format_local_timestamp(timestamp: str, local_timezone: tzinfo | None = None) -> str | None:
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    localized = (
        parsed.astimezone()
        if local_timezone is None
        else parsed.astimezone(local_timezone)
    )
    return localized.strftime("%Y-%m-%d %H:%M:%S")


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
            yield Static("", classes="header-notification-spacer")
            yield HeaderNotification()
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
                yield Static(
                    f"DateTime {_local_timezone_name()}", id="worktree-log-datetime"
                )
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
        local_timestamp = _format_local_timestamp(timestamp)
        if local_timestamp is None:
            return None
        rendered = Text(f"{local_timestamp:<22}")
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


class LinkedProcessLogScreen(Screen):
    """Live output from a process managed for a linked repository."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("b", "back", "Back"),
    ]
    INITIAL_READ_BYTES = 128 * 1024
    INITIAL_LINES = 200

    def __init__(
        self,
        worktree_name: str,
        repository_name: str,
        log_path: Path,
        process_pid: int | None,
        project_name: str,
        show_worktrees: Callable[[], None],
        show_worktree: Callable[[], None],
    ):
        super().__init__()
        self.worktree_name = worktree_name
        self.repository_name = repository_name
        self.log_path = log_path
        self.process_pid = process_pid
        self.project_name = project_name
        self.show_worktrees = show_worktrees
        self.show_worktree = show_worktree
        self._offset = 0
        self._identity: tuple[int, int] | None = None
        self._pending = b""

    def compose(self) -> ComposeResult:
        with Horizontal(id="app-header"):
            with Vertical(id="app-title-group"):
                yield WebLink(REPOSITORY_URL, label="Flotte", id="app-title")
                yield Static(f"v{__version__}", id="app-subtitle")
            yield Static("", classes="header-notification-spacer")
            yield HeaderNotification()
            yield Static("", id="header-spacer")
            yield Static(self.project_name, id="project-name")
        with Vertical(id="worktree-log-screen"):
            with Horizontal(id="log-breadcrumbs"):
                yield Static("Worktrees", id="log-breadcrumb-worktrees")
                yield Static(">", classes="log-breadcrumb-separator")
                yield Static(self.worktree_name, id="log-breadcrumb-worktree")
                yield Static(">", classes="log-breadcrumb-separator")
                yield Static(f"{self.repository_name} Logs", id="log-breadcrumb-current")
            with Horizontal(id="worktree-log-header"):
                yield Static("Output", id="worktree-log-datetime")
                pid = f"PID {self.process_pid}" if self.process_pid else "Stopped"
                yield Static(f"{self.repository_name} · {pid}", id="worktree-log-label")
            yield DashedTableFooter(id="worktree-log-rule")
            yield HoverRichLog(wrap=False, markup=False, auto_scroll=True, id="worktree-log")

    def on_mount(self) -> None:
        self._load_initial()
        self.set_interval(0.25, self._follow)

    def _load_initial(self) -> None:
        try:
            stat = self.log_path.stat()
            start = max(0, stat.st_size - self.INITIAL_READ_BYTES)
            with self.log_path.open("rb") as log_file:
                log_file.seek(start)
                data = log_file.read()
        except OSError as error:
            self.query_one("#worktree-log", RichLog).write(
                Text(f"Unable to read log: {error}", style=self.app.theme_colors.red)
            )
            return

        if start:
            _, separator, data = data.partition(b"\n")
            if not separator:
                data = b""
        self._identity = (stat.st_dev, stat.st_ino)
        self._offset = stat.st_size
        self._write_chunk(data, line_limit=self.INITIAL_LINES)

    def _follow(self) -> None:
        try:
            stat = self.log_path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity != self._identity or stat.st_size < self._offset:
                self._identity = identity
                self._offset = 0
                self._pending = b""
                self.query_one("#worktree-log", RichLog).write(
                    Text("Log file restarted", style=self.app.theme_colors.dim)
                )
            if stat.st_size == self._offset:
                return
            with self.log_path.open("rb") as log_file:
                log_file.seek(self._offset)
                data = log_file.read()
            self._offset += len(data)
            self._write_chunk(data)
        except OSError:
            return

    def _write_chunk(self, data: bytes, line_limit: int | None = None) -> None:
        parts = (self._pending + data).split(b"\n")
        self._pending = parts.pop()
        if line_limit is not None:
            parts = parts[-line_limit:]
        log = self.query_one("#worktree-log", RichLog)
        for line in parts:
            log.write(line.decode("utf-8", errors="replace"), scroll_end=True)

    def action_back(self) -> None:
        self.app.pop_screen()

    @on(events.Click, "#log-breadcrumb-worktrees")
    def on_worktrees_clicked(self) -> None:
        self.show_worktrees()

    @on(events.Click, "#log-breadcrumb-worktree")
    def on_worktree_clicked(self) -> None:
        self.show_worktree()
