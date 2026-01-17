import asyncio
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Button, Header, Static
from textual.timer import Timer
from textual import work

from .config import load_config
from .models import Worktree
from .models.worktree import WorktreeStatus
from .services import DockerManager, RideWrapper, WorktreeManager
from .screens import (
    ConfirmDialog,
    CreateWorktreeScreen,
    CreateWorktreeParams,
    CreateWorktreeResult,
    DeleteWorktreeScreen,
    DeleteWorktreeResult,
    HelpScreen,
)
from .widgets import (
    ContainerControls,
    ContainerTable,
    WorktreeHeader,
    WorktreeChanged,
    ProgressView,
    ErrorView,
    StatusLine,
)


class FlotteApp(App):
    """Flotte - Manage docker-compose projects across git worktrees."""

    TITLE = "Flotte"
    SUB_TITLE = "Manage docker-compose projects across git worktrees"
    CSS_PATH = "styles/app.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit", show=False),
        Binding("?", "show_help", show=False),
        Binding("s", "start_environment", show=False),
        Binding("x", "stop_environment", show=False),
        Binding("d", "delete_worktree", show=False),
        Binding("r", "refresh", show=False),
        Binding("R", "ride", show=False),
        Binding("tab", "focus_next", show=False),
        Binding("shift+tab", "focus_previous", show=False),
        Binding("escape", "deselect", show=False),
    ]

    # Grace period for expected status after operation completes
    OPERATION_GRACE_PERIOD = 2.0  # seconds

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.worktree_manager = WorktreeManager(
            main_repo_path=Path(self.config.main_repo_path),
        )
        self.selected_worktree: Worktree | None = None

        # Operation state - single source of truth
        self._operation_in_progress: bool = False
        self._operation_type: str | None = None  # "create", "delete", "start", "stop", "restart"
        self._operation_target: str | None = None  # worktree name
        self._poll_timer: Timer | None = None

        # Grace period state - prevents status flash after operation completes
        self._recent_operation_target: str | None = None
        self._recent_operation_expected_status: WorktreeStatus | None = None
        self._recent_operation_time: float | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False, icon="")
        with Container(id="main-content"):
            with Container(id="worktrees-box"):
                yield WorktreeHeader(id="worktree-header")
                with Horizontal(id="worktree-controls"):
                    yield Button("New", id="btn-new-worktree", variant="primary")
                    yield Button("Refresh", id="btn-refresh", variant="default")
                    yield Static("", classes="spacer")
                    yield Button("Help", id="btn-help", variant="default")
            with Container(id="containers-box"):
                yield StatusLine(id="status-line")
                yield ContainerTable(id="container-table")
                yield ProgressView(id="progress-view")
                yield ErrorView(id="error-view")
                yield ContainerControls(id="container-controls")

    # Operation lock helpers

    def _acquire_operation_lock(self, op_type: str, target: str) -> bool:
        """Try to acquire operation lock. Returns True if acquired.

        MUST be called from sync context (action methods, callbacks).
        Clears any stale grace period for this target.
        """
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return False

        # Clear any stale grace period for this target
        if self._recent_operation_target == target:
            self._recent_operation_target = None
            self._recent_operation_expected_status = None
            self._recent_operation_time = None

        self._operation_in_progress = True
        self._operation_type = op_type
        self._operation_target = target
        self._update_container_view()
        self.log.info(f"Lock acquired: {op_type} on {target}")
        return True

    def _release_operation_lock(self, expected_status: WorktreeStatus | None = None) -> None:
        """Release operation lock and optionally set grace period for expected status.

        Args:
            expected_status: The status we expect after operation completes.
                            If provided, this status will be returned by get_worktree_status()
                            for OPERATION_GRACE_PERIOD seconds to prevent flashing wrong
                            status before poll confirms the expected state.

        Safe to call even if lock not held (idempotent).
        """
        if not self._operation_in_progress:
            return  # Already released, nothing to do

        op_type = self._operation_type
        target = self._operation_target

        # Set grace period if expected status provided
        if expected_status is not None and target:
            self._recent_operation_target = target
            self._recent_operation_expected_status = expected_status
            self._recent_operation_time = time.monotonic()
        else:
            # Clear grace period (operation failed or no expected status)
            self._recent_operation_target = None
            self._recent_operation_expected_status = None
            self._recent_operation_time = None

        self._operation_in_progress = False
        self._operation_type = None
        self._operation_target = None
        self._clear_progress_view()
        self._update_container_view()
        self.log.info(f"Lock released: {op_type} on {target}")

    def _clear_progress_view(self) -> None:
        """Clear the progress view after operation completes."""
        try:
            progress = self.query_one("#progress-view", ProgressView)
            progress.clear()
        except Exception:
            pass  # Progress view may not exist

    def on_mount(self) -> None:
        """Initialize app and start polling."""
        self.query_one("#worktrees-box").border_title = "Worktrees"
        self.query_one("#containers-box").border_title = "Containers"

        # Set initial display states
        self.query_one("#progress-view").display = False
        self.query_one("#error-view").display = False

        if self.config.auto_discover:
            self.run_worker(self.refresh_worktrees())

        self._poll_timer = self.set_interval(self.config.poll_interval, self.poll_container_status)

        self.notify("Welcome!")

    async def refresh_worktrees(self) -> None:
        """Discover and display all worktrees."""
        worktrees = await self.worktree_manager.discover_worktrees()

        # Pre-fetch volumes so they're cached for worktree creation
        await self.worktree_manager.get_volumes()

        # Update header dropdown - pass status function for consistent display
        header = self.query_one("#worktree-header", WorktreeHeader)
        header.refresh_worktrees(worktrees, status_fn=self.get_worktree_status)

        # Auto-select first worktree if none selected
        if worktrees and self.selected_worktree is None:
            self.selected_worktree = worktrees[0]
            header.select_worktree(self.selected_worktree)
            self.query_one("#containers-box").border_title = self.selected_worktree.name
            table = self.query_one("#container-table", ContainerTable)
            table.worktree = self.selected_worktree

        # Immediately fetch container status (don't wait for poll interval)
        self.poll_container_status()

    @work(exclusive=True, name="status-poller")
    async def poll_container_status(self) -> None:
        """Poll container status for all worktrees in parallel."""
        async def poll_single(worktree: Worktree) -> None:
            """Poll a single worktree's container status."""
            try:
                docker_mgr = DockerManager(
                    worktree.path,
                    worktree.compose_project_name
                )
                containers = await docker_mgr.get_containers()
                worktree.containers = containers

                # Calculate and store status (for backwards compatibility)
                worktree.status = worktree.calculate_status()

                # Clear grace period early if poll confirms expected status
                # This prevents showing stale expected status when containers have updated
                if (self._recent_operation_target == worktree.name
                    and self._recent_operation_expected_status is not None):
                    if worktree.status == self._recent_operation_expected_status:
                        self._recent_operation_target = None
                        self._recent_operation_expected_status = None
                        self._recent_operation_time = None
            except Exception as e:
                self.log.error(f"Error polling {worktree.name}: {e}")

        # Poll all worktrees in parallel
        await asyncio.gather(*[
            poll_single(wt) for wt in self.worktree_manager.worktrees.values()
        ])

        # Update UI
        self._update_ui_after_poll()

    def _update_ui_after_poll(self) -> None:
        """Update UI elements after status poll."""
        # Update worktree list - pass status function for consistent display
        header = self.query_one("#worktree-header", WorktreeHeader)
        header.refresh_worktrees(
            list(self.worktree_manager.worktrees.values()),
            status_fn=self.get_worktree_status
        )

        # Update container table if a worktree is selected
        if self.selected_worktree:
            wt_name = self.selected_worktree.name
            fresh_wt = self.worktree_manager.worktrees.get(wt_name)
            if fresh_wt:
                # Update to get fresh container data
                # Status flashing prevented by get_worktree_status() grace period
                self.selected_worktree = fresh_wt
                table = self.query_one("#container-table", ContainerTable)
                table.worktree = fresh_wt

                self.run_worker(self._fetch_git_status())
            else:
                # Worktree was deleted - clear selection
                self.selected_worktree = None

        # Update view - status will be computed fresh
        self._update_container_view()

    def _effective_status(self) -> WorktreeStatus:
        """Get status for currently selected worktree.

        Delegates to get_worktree_status() which handles operation state,
        grace period, and container-based calculation.
        """
        if self.selected_worktree is None:
            return WorktreeStatus.UNKNOWN
        return self.get_worktree_status(self.selected_worktree.name)

    def get_worktree_status(self, worktree_name: str) -> WorktreeStatus:
        """Compute effective status for a worktree.

        Single source of truth for status. Priority order:
        1. Operation in progress → return operation status (STARTING, STOPPING, etc.)
        2. Recent operation completed → return expected final status (grace period)
        3. Default → compute from container states

        The grace period prevents flashing wrong status between operation completion
        and the next poll confirming the expected state.
        """
        # Priority 1: Operation in progress for this worktree
        if self._operation_in_progress and self._operation_target == worktree_name:
            status_map = {
                "create": WorktreeStatus.CREATING,
                "delete": WorktreeStatus.DELETING,
                "start": WorktreeStatus.STARTING,
                "stop": WorktreeStatus.STOPPING,
                "restart": WorktreeStatus.STARTING,
            }
            return status_map.get(self._operation_type, WorktreeStatus.UNKNOWN)

        # Priority 2: Recent operation grace period
        if (self._recent_operation_target == worktree_name
            and self._recent_operation_expected_status is not None
            and self._recent_operation_time is not None):
            elapsed = time.monotonic() - self._recent_operation_time
            if elapsed < self.OPERATION_GRACE_PERIOD:
                return self._recent_operation_expected_status

        # Priority 3: Compute from container states
        wt = self.worktree_manager.worktrees.get(worktree_name)
        if wt:
            return wt.calculate_status()

        return WorktreeStatus.UNKNOWN

    def _update_container_view(self) -> None:
        """Show/hide container box widgets based on effective status."""
        status = self._effective_status()

        self.query_one("#status-line", StatusLine).status = status

        # Also update WorktreeHeader to keep status icons in sync
        # This ensures both the table icon and status line show the same status
        header = self.query_one("#worktree-header", WorktreeHeader)
        header.refresh_worktrees(
            list(self.worktree_manager.worktrees.values()),
            status_fn=self.get_worktree_status
        )

        # Show table for container-related states, progress for create/delete
        # During DELETING, show table so user sees containers disappearing
        show_table = status != WorktreeStatus.CREATING
        show_progress = status == WorktreeStatus.CREATING

        self.query_one("#container-table").display = show_table
        self.query_one("#progress-view").display = show_progress
        self.query_one("#error-view").display = False  # Errors shown via notify

        controls = self.query_one("#container-controls", ContainerControls)
        controls.status = status
        controls.is_main = self.selected_worktree.is_main if self.selected_worktree else False

        self._update_box_title()

    def _update_box_title(self) -> None:
        """Update containers-box border title based on state."""
        box = self.query_one("#containers-box")
        status = self._effective_status()

        if status == WorktreeStatus.STARTING and self._operation_target:
            box.border_title = f"Starting: {self._operation_target}"
        elif status == WorktreeStatus.STOPPING and self._operation_target:
            box.border_title = f"Stopping: {self._operation_target}"
        elif status == WorktreeStatus.CREATING and self._operation_target:
            box.border_title = f"Creating: {self._operation_target}"
        elif status == WorktreeStatus.DELETING and self._operation_target:
            box.border_title = f"Deleting: {self._operation_target}"
        elif self.selected_worktree:
            box.border_title = self.selected_worktree.name
        else:
            box.border_title = "Containers"

    def on_worktree_changed(self, event: WorktreeChanged) -> None:
        """Handle worktree selection from dropdown."""
        fresh_wt = self.worktree_manager.worktrees.get(event.worktree.name)
        self.selected_worktree = fresh_wt if fresh_wt else event.worktree

        self.run_worker(self._fetch_git_status())
        self.query_one("#container-table", ContainerTable).worktree = self.selected_worktree
        self._update_container_view()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_actions = {
            "btn-new-worktree": self.action_new_worktree,
            "btn-refresh": self.action_refresh,
            "btn-help": self.action_show_help,
            "btn-container-start": self.action_start_environment,
            "btn-container-stop": self.action_stop_environment,
            "btn-container-restart": self.action_restart_environment,
            "btn-ride": self.action_ride,
            "btn-delete-worktree": self.action_delete_worktree,
        }
        action = button_actions.get(event.button.id)
        if action:
            action()

    async def _fetch_git_status(self) -> None:
        """Fetch git status asynchronously and update display."""
        if not self.selected_worktree:
            return
        git_status = await self.worktree_manager.get_git_status(self.selected_worktree)
        header = self.query_one("#worktree-header", WorktreeHeader)
        header.update_git_status(git_status)

    # Action methods

    def action_refresh(self) -> None:
        """Refresh worktree list and container status."""
        self.run_worker(self.refresh_worktrees())
        self.poll_container_status()

    def action_start_environment(self) -> None:
        """Start Docker environment."""
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return
        if not self.selected_worktree:
            return

        wt = self.selected_worktree
        if not self._acquire_operation_lock("start", wt.name):
            return

        self.run_worker(self._perform_start(wt), name="op-start", exclusive=False)

    async def _perform_start(self, wt: Worktree) -> None:
        """Perform environment start. Lock must already be held."""
        if not self._operation_in_progress:
            self.log.error("_perform_start called without lock")
            return

        lock_released = False
        try:
            returncode, stdout, stderr = await RideWrapper(wt.path, wt.compose_project_name).start()
            if returncode != 0:
                self.log.error(f"Start failed: {stderr or stdout}")
                self.notify(f"Failed to start: {stderr or stdout}", severity="error")
                self._release_operation_lock()
                lock_released = True
            else:
                self.notify(f"Started {wt.name}", severity="information")
                self._release_operation_lock(expected_status=WorktreeStatus.RUNNING)
                lock_released = True
        except asyncio.CancelledError:
            self.log.warning(f"Start cancelled: {wt.name}")
            raise
        except Exception as e:
            self.log.error(f"Start failed: {e}")
            self.notify(f"Failed to start: {e}", severity="error")
        finally:
            if not lock_released:
                self._release_operation_lock()

    def action_stop_environment(self) -> None:
        """Stop Docker environment."""
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return
        if not self.selected_worktree:
            return

        wt = self.selected_worktree
        if not self._acquire_operation_lock("stop", wt.name):
            return

        self.run_worker(self._perform_stop(wt), name="op-stop", exclusive=False)

    async def _perform_stop(self, wt: Worktree) -> None:
        """Perform environment stop. Lock must already be held."""
        if not self._operation_in_progress:
            self.log.error("_perform_stop called without lock")
            return

        lock_released = False
        try:
            returncode, stdout, stderr = await RideWrapper(wt.path, wt.compose_project_name).stop()
            if returncode != 0:
                self.log.error(f"Stop failed: {stderr or stdout}")
                self.notify(f"Failed to stop: {stderr or stdout}", severity="error")
                self._release_operation_lock()
                lock_released = True
            else:
                self.notify(f"Stopped {wt.name}", severity="information")
                self._release_operation_lock(expected_status=WorktreeStatus.STOPPED)
                lock_released = True
        except asyncio.CancelledError:
            self.log.warning(f"Stop cancelled: {wt.name}")
            raise
        except Exception as e:
            self.log.error(f"Stop failed: {e}")
            self.notify(f"Failed to stop: {e}", severity="error")
        finally:
            if not lock_released:
                self._release_operation_lock()

    def action_restart_environment(self) -> None:
        """Restart Docker environment."""
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return
        if not self.selected_worktree:
            return

        wt = self.selected_worktree
        if not self._acquire_operation_lock("restart", wt.name):
            return

        self.run_worker(self._perform_restart(wt), name="op-restart", exclusive=False)

    async def _perform_restart(self, wt: Worktree) -> None:
        """Perform environment restart. Lock must already be held."""
        if not self._operation_in_progress:
            self.log.error("_perform_restart called without lock")
            return

        lock_released = False
        try:
            returncode, stdout, stderr = await RideWrapper(wt.path, wt.compose_project_name).restart()
            if returncode != 0:
                self.log.error(f"Restart failed: {stderr or stdout}")
                self.notify(f"Failed to restart: {stderr or stdout}", severity="error")
                self._release_operation_lock()
                lock_released = True
            else:
                self.notify(f"Restarted {wt.name}", severity="information")
                self._release_operation_lock(expected_status=WorktreeStatus.RUNNING)
                lock_released = True
        except asyncio.CancelledError:
            self.log.warning(f"Restart cancelled: {wt.name}")
            raise
        except Exception as e:
            self.log.error(f"Restart failed: {e}")
            self.notify(f"Failed to restart: {e}", severity="error")
        finally:
            if not lock_released:
                self._release_operation_lock()

    def action_new_worktree(self) -> None:
        """Handle New button - opens dialog."""
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return

        self.push_screen(
            CreateWorktreeScreen(self.worktree_manager),
            callback=self._on_create_dialog_result
        )

    def _on_create_dialog_result(self, result: CreateWorktreeResult | None) -> None:
        """Callback when create dialog dismissed."""
        if result is None:
            return  # Cancelled or failed

        worktree = result.worktree
        params = result.params

        # Refresh worktrees to show the new one
        self.run_worker(self._finish_create_worktree(worktree, params))

    async def _finish_create_worktree(self, worktree: Worktree, params: CreateWorktreeParams) -> None:
        """Finish worktree creation after modal is done."""
        # Refresh worktrees to include the new one
        await self.refresh_worktrees()

        # Select the new worktree
        self.selected_worktree = worktree
        self.query_one("#worktree-header", WorktreeHeader).select_worktree(worktree)

        # Start if requested
        if params.start_after:
            if not self._acquire_operation_lock("start", worktree.name):
                self.notify(f"Created {worktree.name}", severity="information")
                return

            returncode, stdout, stderr = await RideWrapper(worktree.path, worktree.compose_project_name).start()
            if returncode != 0:
                self.log.error(f"Start after create failed: {stderr or stdout}")
                self.notify(f"Created {worktree.name}, but start failed", severity="warning")
                self._release_operation_lock(expected_status=WorktreeStatus.STOPPED)
            else:
                self.notify(f"Created and started {worktree.name}", severity="information")
                self._release_operation_lock(expected_status=WorktreeStatus.RUNNING)
        else:
            self.notify(f"Created {worktree.name}", severity="information")

    def action_delete_worktree(self) -> None:
        """Handle Delete button."""
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return
        if not self.selected_worktree:
            return
        if self.selected_worktree.is_main:
            self.notify("Cannot delete main environment", severity="error")
            return

        wt = self.selected_worktree  # Capture NOW

        # Validate worktree exists in manager
        if wt.name not in self.worktree_manager.worktrees:
            self.notify("Worktree no longer exists", severity="error")
            return

        # Start lightweight worker to check git status
        self.run_worker(self._prepare_delete(wt))

    async def _prepare_delete(self, wt: Worktree) -> None:
        """Check git status and initiate delete dialog chain.

        This is NOT a locked operation - just preparation.
        """
        try:
            # Re-validate (could have been deleted during worker startup)
            if wt.name not in self.worktree_manager.worktrees:
                self.notify("Worktree no longer exists", severity="error")
                return

            # If an operation started while we were checking, abort
            if self._operation_in_progress:
                self.log.debug("Operation started during _prepare_delete, aborting")
                return

            git_status = await self.worktree_manager.get_git_status(wt)
            has_changes = (
                git_status["modified"] > 0 or
                git_status["staged"] > 0 or
                git_status["untracked"] > 0
            )

            # Check again after async call
            if self._operation_in_progress:
                self.log.debug("Operation started during git status check, aborting")
                return

            if has_changes:
                changes = []
                if git_status["staged"] > 0:
                    changes.append(f"{git_status['staged']} staged")
                if git_status["modified"] > 0:
                    changes.append(f"{git_status['modified']} modified")
                if git_status["untracked"] > 0:
                    changes.append(f"{git_status['untracked']} untracked")

                self._show_commit_dialog(wt, changes)
            else:
                self._show_delete_confirmation(wt)

        except asyncio.CancelledError:
            self.log.debug("_prepare_delete cancelled")
            raise

        except Exception as e:
            self.log.error(f"Failed to check git status: {e}")
            self.notify(f"Failed to check git status: {e}", severity="error")

    def _show_commit_dialog(self, wt: Worktree, changes: list[str]) -> None:
        """Show commit dialog for uncommitted changes."""
        if self._operation_in_progress:
            self.notify("Another operation started", severity="warning")
            return

        self.push_screen(
            ConfirmDialog(
                f"[bold]Uncommitted changes:[/bold]\n  {', '.join(changes)}\n\nCommit before deleting?",
                title="Uncommitted Changes",
                confirm_label="Commit",
                cancel_label="Discard"
            ),
            # Capture wt by value using default argument
            callback=lambda should_commit, wt=wt: self._on_commit_dialog_result(wt, should_commit)
        )

    def _on_commit_dialog_result(self, wt: Worktree, should_commit: bool) -> None:
        """Handle commit dialog result."""
        if self._operation_in_progress:
            self.notify("Another operation started", severity="warning")
            return

        if should_commit:
            self.run_worker(self._do_commit_then_confirm(wt))
        else:
            self._show_delete_confirmation(wt)

    async def _do_commit_then_confirm(self, wt: Worktree) -> None:
        """Commit changes then show delete confirmation."""
        try:
            if self._operation_in_progress:
                self.log.debug("Operation started before commit, aborting")
                return

            await self.worktree_manager.commit_all_changes(wt, "Commit before worktree delete")
            self._show_delete_confirmation(wt)

        except asyncio.CancelledError:
            self.log.debug("Commit cancelled")
            raise

        except Exception as e:
            self.log.error(f"Commit failed: {e}")
            self.notify(f"Commit failed: {e}", severity="error")

    def _show_delete_confirmation(self, wt: Worktree) -> None:
        """Show the delete worktree modal with progress."""
        if self._operation_in_progress:
            self.notify("Another operation started", severity="warning")
            return

        # Re-validate worktree still exists
        if wt.name not in self.worktree_manager.worktrees:
            self.notify("Worktree no longer exists", severity="error")
            return

        self.push_screen(
            DeleteWorktreeScreen(wt, self.worktree_manager),
            callback=lambda result: self._on_delete_result(result)
        )

    def _on_delete_result(self, result: DeleteWorktreeResult | None) -> None:
        """Handle delete modal result."""
        if result is None:
            # User cancelled
            return

        if result.success:
            self.notify(f"Deleted {result.worktree_name}", severity="information")
            # Refresh worktrees and select main
            self.run_worker(self._post_delete_refresh())
        else:
            # Error was already shown in modal
            pass

    async def _post_delete_refresh(self) -> None:
        """Refresh worktrees after deletion and select main."""
        await self.refresh_worktrees()
        main_wt = next(
            (w for w in self.worktree_manager.worktrees.values() if w.is_main),
            None
        )
        if main_wt:
            self.selected_worktree = main_wt
            self.query_one("#worktree-header", WorktreeHeader).select_worktree(main_wt)

    def action_show_help(self) -> None:
        """Show help screen - '?' key."""
        self.push_screen(HelpScreen())

    def action_ride(self) -> None:
        """Open workspace using configured ride_command."""
        import subprocess
        import shlex
        import os

        if not self.selected_worktree:
            return

        if not self.config.ride_command:
            self.notify("ride_command not configured in config.toml", severity="warning")
            return

        env = {
            **os.environ,
            "PROJECT_PATH": str(self.selected_worktree.path),
            "PROJECT_NAME": self.selected_worktree.name,
        }
        try:
            subprocess.Popen(
                shlex.split(self.config.ride_command),
                env=env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.notify(f"Command not found: {self.config.ride_command}", severity="error")
        except Exception as e:
            self.notify(f"Failed to run ride_command: {e}", severity="error")

    def action_open_ssh(self) -> None:
        """Open a shell in the Rails container in an external terminal."""
        import subprocess
        import shutil

        if not self.selected_worktree:
            return

        docker_cmd = (
            f"cd {self.selected_worktree.path} && "
            f"docker compose exec rails bash"
        )

        terminals = [
            ("alacritty", ["alacritty", "-e", "bash", "-c", docker_cmd]),
            ("kitty", ["kitty", "bash", "-c", docker_cmd]),
            ("wezterm", ["wezterm", "start", "--", "bash", "-c", docker_cmd]),
            ("foot", ["foot", "bash", "-c", docker_cmd]),
            ("gnome-terminal", ["gnome-terminal", "--", "bash", "-c", docker_cmd]),
            ("konsole", ["konsole", "-e", "bash", "-c", docker_cmd]),
            ("xfce4-terminal", ["xfce4-terminal", "-e", f"bash -c '{docker_cmd}'"]),
            ("xterm", ["xterm", "-e", "bash", "-c", docker_cmd]),
        ]

        for name, cmd in terminals:
            if shutil.which(name):
                try:
                    subprocess.Popen(cmd, start_new_session=True)
                    return
                except Exception:
                    continue

    def action_deselect(self) -> None:
        """Clear selection and unfocus - Escape key."""
        self.selected_worktree = None
        self.query_one("#worktree-header", WorktreeHeader).clear()
        self.query_one("#container-table", ContainerTable).worktree = None
