import asyncio
from functools import partial
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, Vertical
from textual.widgets import Button, ContentSwitcher, Static, Select
from textual import events, on, work

from .config import load_config, Project as ConfigProject
from .formatters import format_git_status
from .theme import load_theme_colors
from .models import Worktree
from .models.project import Project
from .models.worktree import WorktreeStatus
from .messages import OperationCompleted, WorktreeStatusChanged
from .services import LinkedWorktreeManager, RideWrapper, WorktreeManager
from .screens import (
    ConfirmDialog,
    CreateWorktreeScreen,
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
    WorktreeOpened,
    ProgressView,
    ErrorView,
    LinkedRepositories,
    LinkedRepositoryAction,
    DashedTableFooter,
    WebLink,
)
from . import __version__


class FlotteApp(App):
    """Flotte - Manage docker-compose projects across git worktrees."""

    TITLE = "Flotte"
    SUB_TITLE = "Manage docker-compose projects across git worktrees"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit", show=False),
        Binding("?", "show_help", show=False),
        Binding("n", "new_worktree", show=False),
        Binding("d", "delete_worktree", show=False),
        Binding("s", "start_environment", show=False),
        Binding("x", "stop_environment", show=False),
        Binding("r", "refresh", show=False),
        Binding("R", "ride", show=False),
        Binding("o", "open_url", show=False),
        Binding("tab", "focus_next", show=False),
        Binding("shift+tab", "focus_previous", show=False),
        Binding("escape", "escape", show=False),
        Binding("b", "back_to_worktrees", show=False),
    ]

    def __init__(self):
        # Load config first to determine theme
        self.config = load_config()

        # Load theme colors for Python code (parsed from same TCSS file)
        self.theme_colors = load_theme_colors(self.config.theme)

        # Load and combine CSS: theme (variables) + base (layout rules)
        styles_dir = Path(__file__).parent / "styles"
        theme_path = styles_dir / "themes" / f"{self.config.theme}.tcss"
        if not theme_path.exists():
            theme_path = styles_dir / "themes" / "onedark.tcss"
        base_path = styles_dir / "base.tcss"
        # Concatenate theme variables with base rules so variables are in scope
        self.CSS = theme_path.read_text() + "\n" + base_path.read_text()

        super().__init__()

        # Current config project (for selector UI)
        self.current_config_project: ConfigProject | None = None
        if self.config.projects:
            self.current_config_project = self.config.projects[0]

        # Project model (owns worktrees and polling)
        self.project: Project | None = None
        if self.current_config_project:
            self.project = Project(
                self.current_config_project.name,
                self.current_config_project.repository_path,
                self.current_config_project.ride_command,
            )

        # WorktreeManager for discovery and lifecycle operations
        self.worktree_manager: WorktreeManager | None = None
        self.linked_worktree_manager: LinkedWorktreeManager | None = None
        if self.current_config_project:
            self.worktree_manager = WorktreeManager(
                main_repo_path=Path(self.current_config_project.repository_path),
                worktree_path_template=self.current_config_project.worktree_path,
                clone_paths=self.current_config_project.clone_paths,
                env_file=self.current_config_project.env_file,
                post_create_commands=self.current_config_project.post_create_commands,
            )
            if self.current_config_project.linked_repositories:
                self.linked_worktree_manager = LinkedWorktreeManager(
                    self.current_config_project.linked_repositories
                )

        self.selected_worktree: Worktree | None = None

        # Git status fetch state (serializes fetches, one subprocess at a time)
        self._git_fetch_running: bool = False
        self._git_fetch_queued: bool = False
        self._list_git_fetch_running: bool = False
        self._list_git_fetch_queued: bool = False

        # Simple operation lock (prevents concurrent operations)
        self._operation_in_progress: bool = False
        self._operation_type: str | None = None  # "create", "delete", "start", "stop", "restart"
        self._operation_target: str | None = None  # worktree name

    def compose(self) -> ComposeResult:
        # Show no-config screen if no projects configured
        if not self.config.projects:
            from .config import CONFIG_FILE
            with Center(id="no-config-center"):
                with Vertical(id="no-config-dialog"):
                    yield Static("No Projects Configured", id="dialog-title")
                    with Vertical(id="no-config-content"):
                        yield Static(
                            "At least one project must be configured to use Flotte.",
                            id="no-config-message"
                        )
                        yield Static(
                            f"Configuration file: [bold]{CONFIG_FILE}[/bold]",
                            id="no-config-path"
                        )
                        yield Static(
                            "Add a [[projects]] entry with name and path.",
                            id="no-config-help"
                        )
                    with Horizontal(id="dialog-buttons"):
                        yield Button("Quit", id="quit-btn", variant="error")
            return

        # Custom header with project selector
        with Horizontal(id="app-header"):
            with Vertical(id="app-title-group"):
                yield Static("Flotte", id="app-title")
                yield Static(f"v{__version__}", id="app-subtitle")
                yield Static("", id="header-gap")
            yield Static("", id="header-spacer")
            yield Select(
                options=[(p.name, p) for p in self.config.projects],
                value=self.current_config_project,
                id="project-selector",
                allow_blank=False,
            )

        with ContentSwitcher(initial="list-view", id="view-switcher"):
            with Container(id="list-view"):
                yield Static("Worktrees", id="worktrees-title")
                with Container(id="worktrees-box"):
                    yield WorktreeHeader(id="worktree-header")
                with Horizontal(id="worktree-controls"):
                    yield Button("New", id="btn-new-worktree", variant="primary")
                    yield Button("Refresh", id="btn-refresh", variant="default")
                    yield Static("", classes="spacer")
                    yield Button("Help", id="btn-help", variant="default")
            with Container(id="details-view"):
                with Horizontal(id="breadcrumbs"):
                    yield Static("Worktrees", id="breadcrumb-worktrees")
                    yield Static(">", id="breadcrumb-separator")
                    yield Static("", id="breadcrumb-worktree")
                    yield Static("", id="breadcrumb-git-status")
                    yield Static("", classes="spacer")
                    yield Button("Go Ride", id="btn-ride")
                with Container(id="containers-box"):
                    yield ContainerTable(id="container-table")
                    yield DashedTableFooter(id="container-table-footer-rule")
                    yield ProgressView(id="progress-view")
                    yield ErrorView(id="error-view")
                    yield ContainerControls(id="container-controls")
                    yield LinkedRepositories(id="linked-repositories")

    # Operation lock helpers

    def _acquire_operation_lock(self, op_type: str, target: str) -> bool:
        """Try to acquire operation lock. Returns True if acquired.

        MUST be called from sync context (action methods, callbacks).
        """
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return False

        self._operation_in_progress = True
        self._operation_type = op_type
        self._operation_target = target
        self._update_container_view()
        self.log.info(f"Lock acquired: {op_type} on {target}")
        return True

    def _release_operation_lock(self) -> None:
        """Release operation lock.

        Safe to call even if lock not held (idempotent).
        """
        if not self._operation_in_progress:
            return  # Already released, nothing to do

        op_type = self._operation_type
        target = self._operation_target

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

    def _set_view(self, *, show_details: bool) -> None:
        """Switch between the worktree list and selected-worktree details."""
        self.query_one("#view-switcher", ContentSwitcher).current = (
            "details-view" if show_details else "list-view"
        )
        self.query_one("#project-selector").display = not show_details

        if not show_details:
            self.query_one("#worktree-table").focus()

    def _is_showing_worktree_details(self) -> bool:
        """Return whether the detail view is the active ContentSwitcher child."""
        return self.query_one("#view-switcher", ContentSwitcher).current == "details-view"

    def _show_worktree_list(self) -> None:
        """Show the compact worktree browser."""
        self._set_view(show_details=False)

    def _show_worktree_details(self) -> None:
        """Show full-height controls for the selected worktree."""
        if self.selected_worktree is None:
            return
        self._set_view(show_details=True)
        self._refresh_detail_view(fetch_git_status=True)

    def _refresh_detail_view(self, *, fetch_git_status: bool = False) -> None:
        """Synchronize widgets shown for the selected worktree."""
        if self.selected_worktree is None:
            return

        table = self.query_one("#container-table", ContainerTable)
        if table.worktree is None or table.worktree.name != self.selected_worktree.name:
            table.worktree = self.selected_worktree
        else:
            table.sync_worktree(self.selected_worktree)
        self._update_container_view(refresh_linked_repositories=True)
        if fetch_git_status:
            self.run_worker(self._fetch_git_status())

    @on(Select.Changed, "#project-selector")
    def on_project_changed(self, event: Select.Changed) -> None:
        """Handle project selection change."""
        if self._operation_in_progress:
            self.notify("Cannot switch project during operation", severity="warning")
            # Reset selector to current project
            self.query_one("#project-selector", Select).value = self.current_config_project
            return

        new_config_project = event.value
        if new_config_project and new_config_project != self.current_config_project:
            self.switch_project(new_config_project)

    def switch_project(self, config_project: ConfigProject) -> None:
        """Switch to a different project, resetting all state."""
        # Stop polling on old project
        if self.project:
            self.project.stop_polling()

        self.current_config_project = config_project

        # Create new Project model
        self.project = Project(
            config_project.name,
            config_project.repository_path,
            config_project.ride_command,
        )

        # Reset selection
        self.selected_worktree = None

        # Create new WorktreeManager for new project
        self.worktree_manager = WorktreeManager(
            main_repo_path=Path(config_project.repository_path),
            worktree_path_template=config_project.worktree_path,
            clone_paths=config_project.clone_paths,
            env_file=config_project.env_file,
            post_create_commands=config_project.post_create_commands,
        )
        self.linked_worktree_manager = (
            LinkedWorktreeManager(config_project.linked_repositories)
            if config_project.linked_repositories else None
        )

        # Clear UI state
        self._clear_ui_state()
        self._show_worktree_list()

        # Discover worktrees for new project
        self.run_worker(self.refresh_worktrees())

        # Start polling for new project
        self.project.start_polling(self)

    def _clear_ui_state(self) -> None:
        """Clear all UI widgets to blank state."""
        # Clear worktree header
        header = self.query_one("#worktree-header", WorktreeHeader)
        header.refresh_worktrees([])

        # Clear container table by setting worktree to None
        container_table = self.query_one("#container-table", ContainerTable)
        container_table.worktree = None

        # Hide progress/error views
        self.query_one("#progress-view", ProgressView).display = False
        self.query_one("#error-view", ErrorView).display = False

        # Reset controls
        controls = self.query_one("#container-controls", ContainerControls)
        controls.status = WorktreeStatus.UNKNOWN
        controls.operation_active = False
        self._update_breadcrumb()

    def on_mount(self) -> None:
        """Initialize app and start polling."""
        # No-config mode: just focus the quit button
        if not self.config.projects:
            self.query_one("#quit-btn", Button).focus()
            return

        self._show_worktree_list()

        # Set initial display states
        self.query_one("#progress-view").display = False
        self.query_one("#error-view").display = False

        self.run_worker(self.refresh_worktrees())

        # Start project polling
        if self.project:
            self.project.start_polling(self)

        self.notify("Welcome!")

    async def refresh_worktrees(self) -> None:
        """Discover and display all worktrees."""
        if not self.worktree_manager or not self.project:
            return  # No project selected

        # Discover worktrees via WorktreeManager
        discovered = await self.worktree_manager.discover_worktrees()

        if self.linked_worktree_manager:
            for worktree in discovered:
                self.linked_worktree_manager.attach(worktree)

        # Copy discovered worktrees to Project model
        self.project.worktrees.clear()
        for wt in discovered:
            self.project.worktrees[wt.name] = wt

        # Pre-fetch volumes so they're cached for worktree creation
        await self.worktree_manager.get_volumes()

        # Update header dropdown
        header = self.query_one("#worktree-header", WorktreeHeader)
        header.refresh_worktrees(list(self.project.worktrees.values()))

        # Auto-select first worktree if none selected
        if self.project.worktrees and self.selected_worktree is None:
            first_wt = list(self.project.worktrees.values())[0]
            self.selected_worktree = first_wt
            header.select_worktree(self.selected_worktree)

        # Poll once immediately to get initial status
        if self.project:
            await self.project.poll_once()
            self._update_ui_after_status_change()
        self.run_worker(self._fetch_list_git_statuses())

    def _sync_worktree_ui(self) -> None:
        """Update UI from existing worktrees (no discovery)."""
        if not self.project:
            return
        header = self.query_one("#worktree-header", WorktreeHeader)
        header.refresh_worktrees(list(self.project.worktrees.values()))

    async def on_unmount(self) -> None:
        """Stop polling and the docker events watcher on app shutdown."""
        if self.project:
            await self.project.shutdown()

    def on_app_focus(self) -> None:
        """Terminal gained focus - resume normal reconciliation cadence."""
        if self.project:
            self.project.set_focused(True)

    def on_app_blur(self) -> None:
        """Terminal lost focus - slow down reconciliation polling."""
        if self.project:
            self.project.set_focused(False)

    def on_worktree_status_changed(self, event: WorktreeStatusChanged) -> None:
        """Handle worktree status change from polling."""
        self._update_ui_after_status_change(changed_worktree=event.worktree)

    def on_operation_completed(self, event: OperationCompleted) -> None:
        """Handle operation completion - show notification."""
        wt = event.worktree
        if event.operation == WorktreeStatus.STARTING:
            self.notify(f"Started {wt.name}", severity="information")
        elif event.operation == WorktreeStatus.STOPPING:
            self.notify(f"Stopped {wt.name}", severity="information")

    def _update_ui_after_status_change(
        self, changed_worktree: Worktree | None = None
    ) -> None:
        """Update UI elements after status change.

        Args:
            changed_worktree: The worktree that changed, or None for a
                global refresh (fetches git status regardless).
        """
        if not self.project:
            return

        header = self.query_one("#worktree-header", WorktreeHeader)
        if changed_worktree is None:
            header.refresh_worktrees(list(self.project.worktrees.values()))
        else:
            header.update_worktree_status(changed_worktree)

        if self.selected_worktree:
            wt_name = self.selected_worktree.name
            fresh_wt = self.project.worktrees.get(wt_name)
            if fresh_wt is None:
                self.selected_worktree = None
            elif self._is_showing_worktree_details() and (
                changed_worktree is None or changed_worktree.name == wt_name
            ):
                self._refresh_detail_view(fetch_git_status=changed_worktree is None)

        self._update_container_view()

    def _effective_status(self) -> WorktreeStatus:
        """Get status for currently selected worktree."""
        if self.selected_worktree is None:
            return WorktreeStatus.UNKNOWN
        return self.selected_worktree.status

    def _update_container_view(self, *, refresh_linked_repositories: bool = False) -> None:
        """Show/hide container box widgets based on effective status."""
        status = self._effective_status()

        # Show table for container-related states, progress for create/delete
        # During DELETING, show table so user sees containers disappearing
        show_table = status != WorktreeStatus.CREATING
        show_progress = status == WorktreeStatus.CREATING

        self.query_one("#container-table").display = show_table
        self.query_one("#progress-view").display = show_progress
        self.query_one("#error-view").display = False  # Errors shown via notify

        controls = self.query_one("#container-controls", ContainerControls)
        controls.status = status
        # Only a running command locks the buttons - a worktree left half-up after
        # the command returns must stay actionable
        controls.operation_active = self._operation_in_progress
        ride_button = self.query_one("#btn-ride", Button)
        ride_button.disabled = self._operation_in_progress or status in (
            WorktreeStatus.CREATING,
            WorktreeStatus.DELETING,
        )
        self.query_one("#container-url", WebLink).set_url(
            self.selected_worktree.web_url if self.selected_worktree else None
        )

        delete_button = self.query_one("#btn-delete-worktree", Button)
        can_delete = (
            self.selected_worktree is not None
            and not self.selected_worktree.is_main
            and status == WorktreeStatus.STOPPED
            and all(
                link.path is None or not link.can_start or link.process_status == "stopped"
                for link in self.selected_worktree.linked_worktrees
            )
            and not self._operation_in_progress
        )
        delete_button.display = can_delete
        delete_button.disabled = False

        self._update_breadcrumb()
        if refresh_linked_repositories:
            self._refresh_linked_repositories()

    def _update_breadcrumb(self) -> None:
        """Show the selected worktree as the current breadcrumb segment."""
        title = self.selected_worktree.name if self.selected_worktree else ""
        self.query_one("#breadcrumb-worktree", Static).update(title)
        self.query_one("#breadcrumb-git-status", Static).update(
            format_git_status(
                self.selected_worktree.git_status if self.selected_worktree else None,
                self.theme_colors,
                prefix="· ",
            )
        )

    def _refresh_linked_repositories(self) -> None:
        widget = self.query_one("#linked-repositories", LinkedRepositories)
        if not widget.update_worktree(self.selected_worktree):
            self._mount_linked_repositories()

    @work(group="linked-repositories", exclusive=True)
    async def _mount_linked_repositories(self) -> None:
        await self.query_one("#linked-repositories", LinkedRepositories).show_worktree(
            self.selected_worktree
        )

    def on_linked_repository_action(self, event: LinkedRepositoryAction) -> None:
        handlers = {
            "link": self._request_create_link,
            "start": partial(self._request_link_lifecycle, "start"),
            "stop": partial(self._request_link_lifecycle, "stop"),
            "restart": partial(self._request_link_lifecycle, "restart"),
            "unlink": self._request_delete_link,
        }
        handler = handlers.get(event.action)
        if handler:
            handler(event.repository_name)

    def on_worktree_changed(self, event: WorktreeChanged) -> None:
        """Handle worktree selection from the worktree table."""
        if not self.project:
            return
        if (
            self.selected_worktree is not None
            and self.selected_worktree.name == event.worktree.name
        ):
            return
        fresh_wt = self.project.worktrees.get(event.worktree.name)
        self.selected_worktree = fresh_wt if fresh_wt else event.worktree
        if self._is_showing_worktree_details():
            self._refresh_detail_view(fetch_git_status=True)

    def on_worktree_opened(self, event: WorktreeOpened) -> None:
        """Open the selected worktree's full-height detail view."""
        if not self.project:
            return
        self.selected_worktree = self.project.worktrees.get(event.worktree.name, event.worktree)
        self._show_worktree_details()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        # No-config mode quit button
        if event.button.id == "quit-btn":
            self.exit()
            return

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

    @on(events.Click, "#breadcrumb-worktrees")
    def on_breadcrumb_worktrees_clicked(self, event: events.Click) -> None:
        """Return to the worktree list from the breadcrumb."""
        event.stop()
        self.action_back_to_worktrees()

    async def _fetch_git_status(self) -> None:
        """Fetch git status for the selected worktree and update display.

        Runs one git subprocess at a time; overlapping requests queue a
        single re-fetch so the result always matches the current selection.
        """
        if self._git_fetch_running:
            self._git_fetch_queued = True
            return

        self._git_fetch_running = True
        try:
            while True:
                self._git_fetch_queued = False
                wt = self.selected_worktree
                if wt is None:
                    return
                git_status, linked_statuses = await asyncio.gather(
                    self.worktree_manager.get_git_status(wt),
                    self.linked_worktree_manager.linked_statuses(wt)
                    if self.linked_worktree_manager else self._empty_linked_statuses(),
                )
                if self._git_fetch_queued:
                    continue
                if self.selected_worktree and self.selected_worktree.name == wt.name:
                    wt.git_status = git_status
                    header = self.query_one("#worktree-header", WorktreeHeader)
                    header.update_git_status(wt.name, git_status)
                    self._update_breadcrumb()
                    for linked in wt.linked_worktrees:
                        linked.git_status = linked_statuses.get(linked.repository_name)
                    self._refresh_linked_repositories()
                return
        finally:
            self._git_fetch_running = False

    async def _fetch_list_git_statuses(self) -> None:
        """Populate Git column values without delaying worktree navigation."""
        if self._list_git_fetch_running:
            self._list_git_fetch_queued = True
            return

        self._list_git_fetch_running = True
        try:
            while True:
                self._list_git_fetch_queued = False
                if not self.project or not self.worktree_manager:
                    return
                worktrees = list(self.project.worktrees.values())
                for worktree in worktrees:
                    git_status = await self.worktree_manager.get_git_status(worktree)
                    if self.project.worktrees.get(worktree.name) is worktree:
                        worktree.git_status = git_status
                        self.query_one("#worktree-header", WorktreeHeader).update_git_status(
                            worktree.name, git_status
                        )
                if not self._list_git_fetch_queued:
                    return
        finally:
            self._list_git_fetch_running = False

    async def _empty_linked_statuses(self) -> dict[str, dict]:
        return {}

    # Action methods

    def action_refresh(self) -> None:
        """Refresh worktree list and container status."""
        self.run_worker(self.refresh_worktrees())

    def action_back_to_worktrees(self) -> None:
        """Return to the worktree list."""
        if self._is_showing_worktree_details():
            self._show_worktree_list()

    def action_escape(self) -> None:
        """Return to the list, or quit when already browsing it."""
        if self._is_showing_worktree_details():
            self._show_worktree_list()
        else:
            self.exit()

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

        wt.start_operation(WorktreeStatus.STARTING, WorktreeStatus.RUNNING)
        self._update_container_view()

        try:
            returncode, stdout, stderr = await RideWrapper(wt.path, wt.compose_project_name).start()
            if returncode != 0:
                self.log.error(f"Start failed: {stderr or stdout}")
                self.notify(f"Failed to start: {stderr or stdout}", severity="error")
                wt.clear_operation()
            # Success: poll will confirm when all services running and post OperationCompleted
        except asyncio.CancelledError:
            self.log.warning(f"Start cancelled: {wt.name}")
            wt.clear_operation()
            raise
        except Exception as e:
            self.log.error(f"Start failed: {e}")
            self.notify(f"Failed to start: {e}", severity="error")
            wt.clear_operation()
        finally:
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

        wt.start_operation(WorktreeStatus.STOPPING, WorktreeStatus.STOPPED)
        self._update_container_view()

        try:
            returncode, stdout, stderr = await RideWrapper(wt.path, wt.compose_project_name).stop()
            if returncode != 0:
                self.log.error(f"Stop failed: {stderr or stdout}")
                self.notify(f"Failed to stop: {stderr or stdout}", severity="error")
                wt.clear_operation()
            # Success: poll will confirm when all services stopped and post OperationCompleted
        except asyncio.CancelledError:
            self.log.warning(f"Stop cancelled: {wt.name}")
            wt.clear_operation()
            raise
        except Exception as e:
            self.log.error(f"Stop failed: {e}")
            self.notify(f"Failed to stop: {e}", severity="error")
            wt.clear_operation()
        finally:
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

        try:
            # Phase 1: Stop
            wt.start_operation(WorktreeStatus.STOPPING, None)  # No auto-clear
            self._update_container_view()

            returncode, stdout, stderr = await RideWrapper(wt.path, wt.compose_project_name).stop()
            if returncode != 0:
                self.log.error(f"Restart (stop phase) failed: {stderr or stdout}")
                self.notify(f"Failed to restart: {stderr or stdout}", severity="error")
                wt.clear_operation()
                return  # Don't proceed to start

            # Phase 2: Start
            wt.start_operation(WorktreeStatus.STARTING, WorktreeStatus.RUNNING)
            self._update_container_view()

            returncode, stdout, stderr = await RideWrapper(wt.path, wt.compose_project_name).start()
            if returncode != 0:
                self.log.error(f"Restart (start phase) failed: {stderr or stdout}")
                self.notify(f"Failed to restart: {stderr or stdout}", severity="error")
                wt.clear_operation()
            # Success: poll will confirm when all containers running and post OperationCompleted

        except asyncio.CancelledError:
            self.log.warning(f"Restart cancelled: {wt.name}")
            wt.clear_operation()
            raise
        except Exception as e:
            self.log.error(f"Restart failed: {e}")
            self.notify(f"Failed to restart: {e}", severity="error")
            wt.clear_operation()
        finally:
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

        # Refresh worktrees to show the new one
        self.run_worker(self._finish_create_worktree(result.worktree))

    async def _finish_create_worktree(self, worktree: Worktree) -> None:
        """Finish worktree creation after modal is done."""
        if not self.project:
            return
        # Add the worktree to our project model
        self.project.worktrees[worktree.name] = worktree
        self._sync_worktree_ui()
        self.selected_worktree = worktree
        self.query_one("#worktree-header", WorktreeHeader).select_worktree(worktree)
        self._show_worktree_details()
        self.notify(f"Created {worktree.name}", severity="information")

    def action_delete_worktree(self) -> None:
        """Handle Delete button."""
        if self._operation_in_progress:
            self.notify("Operation in progress", severity="warning")
            return
        if not self.selected_worktree or not self.project:
            return
        if self.selected_worktree.is_main:
            self.notify("Cannot delete main environment", severity="error")
            return

        wt = self.selected_worktree  # Capture NOW

        # Validate worktree exists in project
        if wt.name not in self.project.worktrees:
            self.notify("Worktree no longer exists", severity="error")
            return

        # Start lightweight worker to check git status
        self.run_worker(self._prepare_delete(wt))

    def _request_create_link(self, repository_name: str) -> None:
        if not self.selected_worktree or not self.linked_worktree_manager:
            return
        if not self._acquire_operation_lock("link", self.selected_worktree.name):
            return
        self.run_worker(
            self._create_link(self.selected_worktree, repository_name),
            name="op-link",
            exclusive=False,
        )

    async def _create_link(self, worktree: Worktree, repository_name: str) -> None:
        try:
            result = await self.linked_worktree_manager.create_link(worktree, repository_name)
            if result.state == "error":
                self.notify(f"Link setup failed: {result.error}", severity="error")
            else:
                self.notify(f"Linked {repository_name}", severity="information")
            self._update_container_view(refresh_linked_repositories=True)
        finally:
            self._release_operation_lock()

    def _request_link_lifecycle(self, action: str, repository_name: str) -> None:
        if not self.selected_worktree or not self.linked_worktree_manager:
            return
        if not self._acquire_operation_lock(f"{action}-linked", self.selected_worktree.name):
            return
        self.run_worker(
            self._run_link_lifecycle(self.selected_worktree, repository_name, action),
            name=f"op-{action}-linked",
            exclusive=False,
        )

    async def _run_link_lifecycle(
        self,
        worktree: Worktree,
        repository_name: str,
        action: str,
    ) -> None:
        operations = {
            "start": self.linked_worktree_manager.start_link,
            "stop": self.linked_worktree_manager.stop_link,
            "restart": self.linked_worktree_manager.restart_link,
        }
        messages = {
            "start": ("Started", "Failed to start"),
            "stop": ("Stopped", "Failed to stop"),
            "restart": ("Restarted", "Failed to restart"),
        }
        try:
            await operations[action](worktree, repository_name)
            self._update_container_view(refresh_linked_repositories=True)
            self.notify(f"{messages[action][0]} {repository_name}", severity="information")
        except Exception as error:
            self.notify(f"{messages[action][1]} {repository_name}: {error}", severity="error")
        finally:
            self._release_operation_lock()

    def _request_delete_link(self, repository_name: str) -> None:
        if not self.selected_worktree or not self.linked_worktree_manager:
            return
        self.run_worker(self._prepare_delete_link(self.selected_worktree, repository_name))

    async def _prepare_delete_link(self, worktree: Worktree, repository_name: str) -> None:
        status = (await self.linked_worktree_manager.linked_statuses(worktree)).get(repository_name)
        if status and any(status[key] for key in ("modified", "staged", "untracked")):
            self.notify(f"Clean {repository_name} before deleting", severity="warning")
            return
        self._clear_action_focus()
        self.push_screen(
            ConfirmDialog(
                f"Delete the linked {repository_name} worktree?",
                title="Delete Linked Worktree",
                confirm_label="Delete",
                cancel_label="Cancel",
            ),
            callback=lambda confirmed, wt=worktree, name=repository_name: self._on_delete_link_confirmed(wt, name, confirmed),
        )

    def _on_delete_link_confirmed(self, worktree: Worktree, repository_name: str, confirmed: bool) -> None:
        if not confirmed:
            self._update_container_view(refresh_linked_repositories=True)
            return
        if not self._acquire_operation_lock("unlink", worktree.name):
            self._update_container_view(refresh_linked_repositories=True)
            return
        self.run_worker(self._delete_link(worktree, repository_name), name="op-unlink", exclusive=False)

    async def _delete_link(self, worktree: Worktree, repository_name: str) -> None:
        try:
            await self.linked_worktree_manager.remove_link(worktree, repository_name)
            self.linked_worktree_manager.attach(worktree)
            self._update_container_view(refresh_linked_repositories=True)
            self.notify(f"Unlinked {repository_name}", severity="information")
        except Exception as error:
            self.notify(f"Failed to unlink {repository_name}: {error}", severity="error")
        finally:
            self._release_operation_lock()

    async def _prepare_delete(self, wt: Worktree) -> None:
        """Check git status and initiate delete dialog chain.

        This is NOT a locked operation - just preparation.
        """
        if not self.project:
            return

        try:
            # Re-validate (could have been deleted during worker startup)
            if wt.name not in self.project.worktrees:
                self.notify("Worktree no longer exists", severity="error")
                return

            # If an operation started while we were checking, abort
            if self._operation_in_progress:
                self.log.debug("Operation started during _prepare_delete, aborting")
                return

            git_status = await self.worktree_manager.get_git_status(wt)
            linked_statuses = {}
            if self.linked_worktree_manager:
                linked_statuses = await self.linked_worktree_manager.linked_statuses(wt)
            has_changes = (
                git_status["modified"] > 0 or
                git_status["staged"] > 0 or
                git_status["untracked"] > 0
            )

            dirty_links = []
            for repository_name, linked_status in linked_statuses.items():
                changed = sum(
                    linked_status[key]
                    for key in ("modified", "staged", "untracked")
                )
                if changed:
                    dirty_links.append(f"{repository_name} ({changed} changes)")

            if dirty_links:
                self.notify(
                    "Clean linked worktrees before deleting: " + ", ".join(dirty_links),
                    severity="warning",
                )
                return

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

        if not self.project:
            return

        # Re-validate worktree still exists
        if wt.name not in self.project.worktrees:
            self.notify("Worktree no longer exists", severity="error")
            return

        self._clear_action_focus()
        self.push_screen(
            DeleteWorktreeScreen(wt, self.worktree_manager, self.linked_worktree_manager),
            callback=lambda result: self._on_delete_result(result)
        )

    def _clear_action_focus(self) -> None:
        """Avoid leaving an action button visually focused behind a modal."""
        self.screen.set_focus(None)

    def _on_delete_result(self, result: DeleteWorktreeResult | None) -> None:
        """Handle delete modal result."""
        if result is None:
            self._update_container_view()
            return

        if result.success:
            self.notify(f"Deleted {result.worktree_name}", severity="information")
            # Refresh worktrees and select main
            self.run_worker(self._post_delete_refresh(result.worktree_name))
        else:
            self._update_container_view()

    async def _post_delete_refresh(self, deleted_name: str) -> None:
        """Refresh worktrees after deletion and select main."""
        if not self.project:
            return

        # Remove from project model
        self.project.worktrees.pop(deleted_name, None)

        self._sync_worktree_ui()
        main_wt = next(
            (w for w in self.project.worktrees.values() if w.is_main),
            None
        )
        if main_wt:
            self.selected_worktree = main_wt
            self.query_one("#worktree-header", WorktreeHeader).select_worktree(main_wt)
        self._show_worktree_list()

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

        if not self.current_config_project or not self.current_config_project.ride_command:
            self.notify("ride_command not configured for this project", severity="warning")
            return

        env = {
            **os.environ,
            "PROJECT_PATH": str(self.selected_worktree.path),
            "PROJECT_NAME": self.selected_worktree.name,
        }
        try:
            subprocess.Popen(
                shlex.split(self.current_config_project.ride_command),
                env=env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.notify(f"Command not found: {self.current_config_project.ride_command}", severity="error")
        except Exception as e:
            self.notify(f"Failed to run ride_command: {e}", severity="error")

    def action_open_url(self, url: str = "") -> None:
        """Open web URL in browser - 'o' key or click on URL."""
        import webbrowser

        if not url:
            if not self.selected_worktree:
                return
            url = self.selected_worktree.web_url

        if url:
            webbrowser.open(url)
        else:
            self.notify("No web server URL available", severity="warning")
