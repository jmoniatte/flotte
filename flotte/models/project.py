from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from .worktree import Worktree

if TYPE_CHECKING:
    from textual.app import App

# Reconciliation intervals; docker events wake the loop early on real changes
POLL_INTERVAL_TRANSIENT = 5.0  # seconds, while an operation is pending
POLL_INTERVAL_IDLE = 30.0  # seconds
POLL_INTERVAL_UNFOCUSED = 120.0  # seconds, while the terminal is not focused
EVENT_BURST_QUIET_SECONDS = 0.3

# docker events actions that change container state (skips healthcheck exec noise)
CONTAINER_STATE_EVENTS = (
    "create",
    "start",
    "restart",
    "pause",
    "unpause",
    "stop",
    "die",
    "destroy",
)


class Project:
    """Project that owns worktrees.

    Initialized from config data (name, path, ride_command).
    Owns and manages its worktrees, creating them on demand.
    Also owns the polling loop for container status updates.
    """

    def __init__(self, name: str, path: str, ride_command: str = ""):
        self.name = name
        self.path = Path(path)
        self.ride_command = ride_command
        self.worktrees: dict[str, Worktree] = {}

        # Polling state
        self._app: App | None = None
        self._poll_task: asyncio.Task | None = None
        self._events_task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._poll_lock = asyncio.Lock()
        self._focused = True

    def get_or_create_worktree(
        self,
        name: str,
        path: Path,
        branch: str = "",
        compose_project_name: str = "",
        is_main: bool = False,
    ) -> Worktree:
        """Get existing worktree or create new one.

        Args:
            name: Worktree name (e.g., 'feature-xyz')
            path: Absolute path to worktree
            branch: Git branch name
            compose_project_name: Docker Compose project name
            is_main: True only for main repo (cannot delete)

        Returns:
            Existing or newly created Worktree
        """
        if name not in self.worktrees:
            self.worktrees[name] = Worktree(
                name=name,
                path=path,
                branch=branch,
                compose_project_name=compose_project_name,
                is_main=is_main,
            )
        return self.worktrees[name]

    def remove_worktree(self, name: str) -> None:
        """Remove worktree from project."""
        self.worktrees.pop(name, None)

    def start_polling(self, app: App) -> None:
        """Start the reconciliation loop and the docker events watcher.

        Args:
            app: The Textual app to post messages to.
        """
        self._app = app
        self.stop_polling()
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._events_task = asyncio.create_task(self._watch_events())

    def stop_polling(self) -> None:
        """Stop the reconciliation loop and the docker events watcher."""
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._events_task is not None:
            self._events_task.cancel()
            self._events_task = None

    async def shutdown(self) -> None:
        """Stop polling and wait for the watcher subprocess to be reaped."""
        tasks = [t for t in (self._poll_task, self._events_task) if t is not None]
        self.stop_polling()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def set_focused(self, focused: bool) -> None:
        """Adjust reconciliation cadence; catch up right away on regained focus."""
        was_focused = self._focused
        self._focused = focused
        if focused and not was_focused:
            self._wake.set()

    async def _poll_loop(self) -> None:
        """Reconciliation loop; docker events wake it early via _wake."""
        while True:
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._app:
                    self._app.log.error(f"Poll error: {e}")

            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self._get_poll_interval()
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _watch_events(self) -> None:
        """Wake the poll loop whenever a compose container changes state.

        Docker pushes changes so the reconciliation loop can stay slow.
        """
        event_filters = []
        for event in CONTAINER_STATE_EVENTS:
            event_filters += ["--filter", f"event={event}"]

        while True:
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "events",
                    "--filter",
                    "type=container",
                    "--filter",
                    "label=com.docker.compose.project",
                    *event_filters,
                    "--format",
                    "{{json .}}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    await self._wait_out_burst(proc.stdout)
                    self._wake.set()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._app:
                    self._app.log.error(f"Docker events watcher error: {e}")
            finally:
                if proc is not None and proc.returncode is None:
                    proc.kill()
                    # Reap the child so its transport closes before the loop does
                    with contextlib.suppress(Exception):
                        await asyncio.shield(proc.wait())

            # Docker daemon may be down or restarting
            await asyncio.sleep(10.0)

    @staticmethod
    async def _wait_out_burst(stdout: asyncio.StreamReader) -> None:
        # compose up/down emits one event per container; refresh once for the batch
        while True:
            try:
                line = await asyncio.wait_for(
                    stdout.readline(), timeout=EVENT_BURST_QUIET_SECONDS
                )
            except asyncio.TimeoutError:
                return
            if not line:
                return

    async def _poll(self) -> None:
        """Poll all worktrees and notify UI of changes."""
        from ..messages import OperationCompleted, WorktreeStatusChanged
        from ..services.docker_manager import get_all_containers_by_project

        async with self._poll_lock:
            worktree_list = list(self.worktrees.values())
            if not worktree_list:
                return

            # One docker ps call covers every worktree
            by_project = await get_all_containers_by_project()
            results = await asyncio.gather(
                *[
                    wt.poll(by_project.get(wt.compose_project_name, []))
                    for wt in worktree_list
                ]
            )

            if self._app:
                for wt, (changed, cleared) in zip(worktree_list, results):
                    if changed:
                        self._app.post_message(WorktreeStatusChanged(wt))
                    if cleared is not None:
                        self._app.post_message(OperationCompleted(wt, cleared))

    def _get_poll_interval(self) -> float:
        """Reconciliation interval: fast during operations, slow when unfocused."""
        if any(wt.in_transient_operation for wt in self.worktrees.values()):
            return POLL_INTERVAL_TRANSIENT
        return POLL_INTERVAL_IDLE if self._focused else POLL_INTERVAL_UNFOCUSED

    async def poll_once(self) -> None:
        """Poll once immediately (for initial load)."""
        await self._poll()
