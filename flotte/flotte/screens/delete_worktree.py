import asyncio
from dataclasses import dataclass

from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Button, Static
from textual.app import ComposeResult

from ..services import WorktreeManager
from ..models import Worktree


@dataclass
class DeleteWorktreeResult:
    """Result of worktree deletion."""
    success: bool
    worktree_name: str


class DeleteWorktreeScreen(ModalScreen[DeleteWorktreeResult | None]):
    """Modal screen for deleting worktrees with progress display."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, worktree: Worktree, worktree_manager: WorktreeManager):
        super().__init__()
        self.worktree = worktree
        self.worktree_manager = worktree_manager
        self._is_deleting = False

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog"):
            yield Static("Delete Worktree", id="dialog-title")

            # Confirmation content (shown initially)
            with Vertical(id="confirm-content"):
                yield Static(
                    f"Are you sure you want to delete [bold]{self.worktree.name}[/bold]?",
                    id="confirm-message"
                )
                yield Static(
                    "This will remove Docker containers, volumes, and the worktree directory.",
                    id="confirm-warning"
                )

            # Status area (hidden initially)
            with Horizontal(id="status-area"):
                yield Static("⟳", id="loading-icon")
                yield Static("Deleting...", id="status-text")

            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Delete", id="delete-btn", variant="error")

    def on_mount(self) -> None:
        self.query_one("#status-area").display = False
        self.query_one("#delete-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()

        if event.button.id == "cancel-btn":
            if not self._is_deleting:
                self.dismiss(None)
            return

        if event.button.id == "delete-btn":
            if self._is_deleting:
                return
            self._is_deleting = True
            self._show_deleting_status()
            self.call_later(lambda: self.run_worker(self._do_delete()))

    def action_cancel(self) -> None:
        if not self._is_deleting:
            self.dismiss(None)

    def _show_deleting_status(self) -> None:
        """Show deleting status and disable controls."""
        self.query_one("#confirm-content").display = False
        self.query_one("#dialog-buttons").display = False
        self.query_one("#status-area").display = True
        self.refresh(layout=True)

    def _update_status(self, message: str) -> None:
        """Update status message."""
        self.query_one("#status-text", Static).update(message)

    async def _do_delete(self) -> None:
        """Perform the actual worktree deletion."""
        try:
            # Stop containers and remove volumes
            self._update_status("Stopping containers...")
            await asyncio.to_thread(
                self.worktree_manager.cleanup_docker_sync,
                self.worktree
            )

            # Remove worktree directory
            self._update_status("Removing worktree...")
            await asyncio.to_thread(
                self.worktree_manager.remove_worktree_sync,
                self.worktree
            )

            # Success
            self.dismiss(DeleteWorktreeResult(
                success=True,
                worktree_name=self.worktree.name
            ))

        except Exception as e:
            self.notify(f"Delete failed: {e}", severity="error")
            self.dismiss(DeleteWorktreeResult(
                success=False,
                worktree_name=self.worktree.name
            ))
