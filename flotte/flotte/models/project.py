from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from .worktree import Worktree

if TYPE_CHECKING:
    from textual.app import App


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
        self._poll_interval: float = 2.0

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

    def start_polling(self, app: App, interval: float = 2.0) -> None:
        """Start the polling loop for container status.

        Args:
            app: The Textual app to post messages to.
            interval: Seconds between polls.
        """
        self._app = app
        self._poll_interval = interval

        if self._poll_task is not None:
            self._poll_task.cancel()

        self._poll_task = asyncio.create_task(self._poll_loop())

    def stop_polling(self) -> None:
        """Stop the polling loop."""
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    async def _poll_loop(self) -> None:
        """Polling loop that runs until cancelled."""
        from ..messages import WorktreeStatusChanged

        while True:
            try:
                await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self._app:
                    self._app.log.error(f"Poll error: {e}")

            await asyncio.sleep(self._poll_interval)

    async def _poll(self) -> None:
        """Poll all worktrees and refresh UI."""
        from ..messages import WorktreeStatusChanged

        # Poll all worktrees in parallel
        await asyncio.gather(*[wt.poll() for wt in self.worktrees.values()])

        # Always refresh UI with current state
        if self._app:
            for wt in self.worktrees.values():
                self._app.post_message(WorktreeStatusChanged(wt))

    async def poll_once(self) -> None:
        """Poll once immediately (for initial load)."""
        await self._poll()
