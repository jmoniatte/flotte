from dataclasses import dataclass
from enum import StrEnum

from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Button, Static
from textual.app import ComposeResult

from ..services import WorkspaceManager
from ..models import GitStatus, Worktree


@dataclass
class DeleteWorktreeResult:
    """Result of worktree deletion."""
    success: bool
    worktree_name: str


class DeleteStage(StrEnum):
    CHECKING = "checking"
    CHANGES = "changes"
    CONFIRM = "confirm"
    COMMITTING = "committing"
    RECHECKING = "rechecking"
    DELETING = "deleting"


class DeleteWorktreeScreen(ModalScreen[DeleteWorktreeResult | None]):
    """Guide a worktree through inspection, confirmation, and deletion."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        worktree: Worktree,
        workspace_manager: WorkspaceManager,
    ):
        super().__init__()
        self.worktree = worktree
        self.workspace_manager = workspace_manager
        self._stage = DeleteStage.CHECKING
        self._allow_dirty_delete = False

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog"):
            yield Static("Delete Worktree", id="dialog-title")

            with Vertical(id="confirm-content"):
                yield Static("", id="confirm-message")
                yield Static("", id="confirm-warning")

            with Horizontal(id="status-area"):
                yield Static("⟳", id="loading-icon")
                yield Static("Checking worktree...", id="status-text")

            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Delete Without Commit", id="discard-btn", variant="warning")
                yield Button("Commit First", id="commit-btn", variant="primary")
                yield Button("Delete", id="delete-btn", variant="error")

    def on_mount(self) -> None:
        self._show_status("Checking worktree...")
        self.call_later(lambda: self.run_worker(self._inspect_worktree()))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()

        if event.button.id == "cancel-btn":
            if self._stage not in {
                DeleteStage.COMMITTING,
                DeleteStage.RECHECKING,
                DeleteStage.DELETING,
            }:
                self.dismiss(None)
            return

        if event.button.id == "discard-btn" and self._stage == DeleteStage.CHANGES:
            self._allow_dirty_delete = True
            self._show_delete_confirmation()
            return

        if event.button.id == "commit-btn" and self._stage == DeleteStage.CHANGES:
            self._stage = DeleteStage.COMMITTING
            self._show_status("Committing changes...")
            self.call_later(lambda: self.run_worker(self._commit_changes()))
            return

        if event.button.id == "delete-btn" and self._stage == DeleteStage.CONFIRM:
            self._stage = DeleteStage.RECHECKING
            self._show_status("Rechecking worktree...")
            self.call_later(lambda: self.run_worker(self._revalidate_and_delete()))

    def action_cancel(self) -> None:
        if self._stage not in {
            DeleteStage.COMMITTING,
            DeleteStage.RECHECKING,
            DeleteStage.DELETING,
        }:
            self.dismiss(None)

    async def _inspect_worktree(self) -> None:
        try:
            inspection = await self.workspace_manager.inspect_deletion(self.worktree)
        except Exception as error:
            self.notify(f"Failed to check worktree: {error}", severity="error")
            self.dismiss(None)
            return

        if inspection.changed_linked_repositories:
            repositories = ", ".join(inspection.changed_linked_repositories)
            self.notify(
                f"Clean linked worktrees before deleting: {repositories}",
                severity="warning",
            )
            self.dismiss(None)
            return

        if inspection.git_status.has_changes:
            self._show_changes_prompt(self._describe_changes(inspection.git_status))
            return

        self._allow_dirty_delete = False
        self._show_delete_confirmation()

    async def _commit_changes(self) -> None:
        try:
            await self.workspace_manager.commit(
                self.worktree,
                "Commit before worktree delete",
            )
        except Exception as error:
            self.notify(f"Commit failed: {error}", severity="error")
            self._stage = DeleteStage.CHANGES
            self._show_prompt(
                f"Could not commit changes in [bold]{self.worktree.name}[/bold].",
                "Retry the commit or delete without committing.",
                actions=("cancel", "discard", "commit"),
            )
            return
        self._allow_dirty_delete = False
        self._show_delete_confirmation()

    async def _revalidate_and_delete(self) -> None:
        try:
            inspection = await self.workspace_manager.inspect_deletion(self.worktree)
        except Exception as error:
            self.notify(f"Failed to recheck worktree: {error}", severity="error")
            self._show_delete_confirmation()
            return

        if inspection.changed_linked_repositories:
            repositories = ", ".join(inspection.changed_linked_repositories)
            self.notify(
                f"Clean linked worktrees before deleting: {repositories}",
                severity="warning",
            )
            self.dismiss(None)
            return

        if inspection.git_status.has_changes and not self._allow_dirty_delete:
            self._show_changes_prompt(self._describe_changes(inspection.git_status))
            return

        self._stage = DeleteStage.DELETING
        self._show_status("Deleting...")
        await self._do_delete()

    def _show_changes_prompt(self, changes: list[str]) -> None:
        self._stage = DeleteStage.CHANGES
        self._show_prompt(
            f"{', '.join(changes)} in [bold]{self.worktree.name}[/bold].",
            "Commit these changes before deleting the worktree?",
            actions=("cancel", "discard", "commit"),
        )

    @staticmethod
    def _describe_changes(status: GitStatus) -> list[str]:
        changes = []
        if status.staged:
            changes.append(f"{status.staged} staged")
        if status.unstaged:
            changes.append(f"{status.unstaged} unstaged")
        if status.untracked:
            changes.append(f"{status.untracked} untracked")
        return changes

    def _show_delete_confirmation(self) -> None:
        self._stage = DeleteStage.CONFIRM
        self._show_prompt(
            f"Are you sure you want to delete [bold]{self.worktree.name}[/bold]?",
            "This will remove Docker containers, volumes, and the worktree directory.",
            actions=("cancel", "delete"),
        )

    def _show_prompt(
        self,
        message: str,
        warning: str,
        *,
        actions: tuple[str, ...],
    ) -> None:
        self.query_one("#confirm-message", Static).update(message)
        self.query_one("#confirm-warning", Static).update(warning)
        self.query_one("#confirm-content").display = True
        self.query_one("#status-area").display = False
        self.query_one("#dialog-buttons").display = True
        for action in ("cancel", "discard", "commit", "delete"):
            self.query_one(f"#{action}-btn", Button).display = action in actions
        focus_action = "delete" if "delete" in actions else "commit"
        self.query_one(f"#{focus_action}-btn", Button).focus()

    def _show_status(self, message: str) -> None:
        self._update_status(message)
        self.query_one("#confirm-content").display = False
        self.query_one("#dialog-buttons").display = False
        self.query_one("#status-area").display = True
        self.refresh(layout=True)

    def _update_status(self, message: str) -> None:
        """Update status message."""
        self.query_one("#status-text", Static).update(message)

    async def _do_delete(self) -> None:
        try:
            await self.workspace_manager.delete(
                self.worktree,
                on_progress=self._update_status,
            )

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
