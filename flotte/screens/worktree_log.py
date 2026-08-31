import asyncio
from collections.abc import Callable
import csv
from datetime import datetime, tzinfo
from pathlib import Path

from textual.app import ComposeResult
from textual import events, on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Checkbox, RichLog, Static, TabbedContent, TabPane, Tabs
from textual.worker import Worker
from rich.text import Text

from ..models import LinkedWorktree
from ..services.docker_manager import DockerManager
from ..services.worktree_log import WorktreeLogStore
from ..widgets import AppHeader, DashedTableFooter


def _local_timezone_name() -> str:
    return datetime.now().astimezone().tzname() or "Local"


def _format_local_timestamp(
    timestamp: str, local_timezone: tzinfo | None = None
) -> str | None:
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


def _format_process_output(line: bytes) -> Text:
    return Text.from_ansi(line.decode("utf-8", errors="replace"))


def _format_container_output(line: bytes, services: dict[str, str]) -> Text:
    prefix, separator, output = line.partition(b" | ")
    if separator:
        container_name = prefix.decode("utf-8", errors="replace").strip()
        service = services.get(container_name)
        if service:
            line = service.encode() + separator + output
    return _format_process_output(line)


class LogsScreen(Screen):
    """Flotte, container, and linked-process logs for a worktree."""

    INITIAL_READ_BYTES = 128 * 1024
    INITIAL_LINES = 200
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("b", "back", "Back"),
    ]

    def __init__(
        self,
        worktree_name: str,
        log_path: Path,
        docker_manager: DockerManager,
        container_services: dict[str, str],
        container_log_services: tuple[str, ...],
        linked_worktrees: list[LinkedWorktree],
        project_name: str,
        show_worktrees: Callable[[], None],
        show_worktree: Callable[[], None],
        wrap: bool = False,
    ):
        super().__init__()
        self.worktree_name = worktree_name
        self.log_path = log_path
        self.docker_manager = docker_manager
        self.container_services = container_services
        self.container_log_services = container_log_services
        self.linked_worktrees = [
            linked
            for linked in linked_worktrees
            if linked.log_path is not None and linked.log_path.exists()
        ]
        self.project_name = project_name
        self.wrap = wrap
        self.show_worktrees = show_worktrees
        self.show_worktree = show_worktree
        self._linked_by_tab = {
            f"linked-{index}": linked
            for index, linked in enumerate(self.linked_worktrees)
        }
        self._active_tab = ""
        self._linked_offset = 0
        self._linked_identity: tuple[int, int] | None = None
        self._linked_pending = b""
        self._docker_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        yield AppHeader(Static(self.project_name, id="project-name"))
        with Vertical(id="worktree-log-screen"):
            with Horizontal(id="log-breadcrumbs"):
                yield Static("Worktrees", id="log-breadcrumb-worktrees")
                yield Static(">", classes="log-breadcrumb-separator")
                yield Static(self.worktree_name, id="log-breadcrumb-worktree")
                yield Static(">", classes="log-breadcrumb-separator")
                yield Static("Logs", id="log-breadcrumb-current")
                yield Static("", classes="spacer")
                yield Checkbox("Wrap", value=self.wrap, id="wrap-logs")
            with TabbedContent(initial="flotte", id="logs-tabs"):
                with TabPane("Flotte", id="flotte"):
                    with Horizontal(id="worktree-log-header"):
                        yield Static(
                            f"DateTime {_local_timezone_name()}",
                            id="worktree-log-datetime",
                        )
                        yield Static("Log", id="worktree-log-label")
                    yield DashedTableFooter(id="worktree-log-rule")
                    yield RichLog(
                        wrap=self.wrap,
                        markup=False,
                        auto_scroll=False,
                        id="flotte-log",
                        classes="logs-output",
                    )
                with TabPane("Containers", id="containers"):
                    yield RichLog(
                        wrap=self.wrap,
                        markup=False,
                        auto_scroll=True,
                        id="containers-log",
                        classes="logs-output",
                    )
                for tab_id, linked in self._linked_by_tab.items():
                    with TabPane(linked.repository_name, id=tab_id):
                        yield RichLog(
                            wrap=self.wrap,
                            markup=False,
                            auto_scroll=True,
                            id=f"{tab_id}-log",
                            classes="logs-output",
                        )

    def on_mount(self) -> None:
        # The wrap checkbox comes first in the DOM; the tabs still own the focus
        self.query_one(Tabs).focus()
        self._activate_tab("flotte")
        self.set_interval(0.25, self._follow_linked)

    def on_unmount(self) -> None:
        self._stop_docker_stream()

    @on(Checkbox.Changed, "#wrap-logs")
    def on_wrap_toggled(self, event: Checkbox.Changed) -> None:
        """Reload the tab; lines keep the wrapping they were written with."""
        self.wrap = event.value
        self.app.wrap_logs = event.value
        for log in self.query(RichLog):
            log.wrap = event.value
        self._reload_active_tab()

    def _reload_active_tab(self) -> None:
        tab_id = self._active_tab
        self._active_tab = ""
        self._activate_tab(tab_id)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id == "logs-tabs" and event.pane.id:
            self._activate_tab(event.pane.id)

    def _activate_tab(self, tab_id: str) -> None:
        if tab_id == self._active_tab:
            return
        self._stop_docker_stream()
        self._active_tab = tab_id
        if tab_id == "flotte":
            self.query_one("#log-breadcrumb-current", Static).update("Logs")
            self._load_flotte_log()
        elif tab_id == "containers":
            self.query_one("#log-breadcrumb-current", Static).update(
                "Logs · Containers"
            )
            log = self.query_one("#containers-log", RichLog)
            log.clear()
            self._docker_worker = self.run_worker(
                self._stream_docker_logs(), name="docker-logs", exit_on_error=False
            )
        else:
            linked = self._linked_by_tab.get(tab_id)
            if linked is None:
                return
            state = f"PID {linked.process_pid}" if linked.process_pid else "Stopped"
            self.query_one("#log-breadcrumb-current", Static).update(
                f"Logs · {linked.repository_name} · {state}"
            )
            self._load_linked_log(linked)

    def _load_flotte_log(self) -> None:
        log = self.query_one("#flotte-log", RichLog)
        log.clear()
        try:
            with self.log_path.open(encoding="utf-8", newline="") as log_file:
                entries = list(csv.DictReader(log_file))
        except FileNotFoundError:
            return
        except (OSError, csv.Error) as error:
            entries = [{"error": f"Unable to read log: {error}"}]
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

    async def _stream_docker_logs(self) -> None:
        log = self.query_one("#containers-log", RichLog)
        try:
            async for line in self.docker_manager.stream_logs(
                services=self.container_log_services
            ):
                if self._active_tab != "containers":
                    break
                log.write(
                    _format_container_output(line, self.container_services),
                    scroll_end=True,
                )
        except asyncio.CancelledError:
            raise
        except OSError as error:
            log.write(
                Text(
                    f"Unable to read container logs: {error}",
                    style=self.app.theme_colors.red,
                )
            )

    def _stop_docker_stream(self) -> None:
        if self._docker_worker is not None:
            self._docker_worker.cancel()
            self._docker_worker = None

    def _load_linked_log(self, linked: LinkedWorktree) -> None:
        log = self.query_one(f"#{self._active_tab}-log", RichLog)
        log.clear()
        log_path = linked.log_path
        if log_path is None:
            return
        try:
            stat = log_path.stat()
            start = max(0, stat.st_size - self.INITIAL_READ_BYTES)
            with log_path.open("rb") as log_file:
                log_file.seek(start)
                data = log_file.read()
        except OSError as error:
            log.write(
                Text(f"Unable to read log: {error}", style=self.app.theme_colors.red)
            )
            return

        if start:
            _, separator, data = data.partition(b"\n")
            if not separator:
                data = b""
        self._linked_identity = (stat.st_dev, stat.st_ino)
        self._linked_offset = stat.st_size
        self._linked_pending = b""
        self._write_linked_chunk(data, line_limit=self.INITIAL_LINES)

    def _follow_linked(self) -> None:
        linked = self._linked_by_tab.get(self._active_tab)
        if linked is None or linked.log_path is None:
            return
        try:
            stat = linked.log_path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity != self._linked_identity or stat.st_size < self._linked_offset:
                self._load_linked_log(linked)
                return
            if stat.st_size == self._linked_offset:
                return
            with linked.log_path.open("rb") as log_file:
                log_file.seek(self._linked_offset)
                data = log_file.read()
            self._linked_offset += len(data)
            self._write_linked_chunk(data)
        except OSError:
            return

    def _write_linked_chunk(self, data: bytes, line_limit: int | None = None) -> None:
        parts = (self._linked_pending + data).split(b"\n")
        self._linked_pending = parts.pop()
        if line_limit is not None:
            parts = parts[-line_limit:]
        log = self.query_one(f"#{self._active_tab}-log", RichLog)
        for line in parts:
            log.write(_format_process_output(line), scroll_end=True)

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
