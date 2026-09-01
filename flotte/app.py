import asyncio
from functools import partial
from getpass import getuser
from pathlib import Path
from random import choice

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.notifications import Notification, SeverityLevel
from textual.widgets import Button, ContentSwitcher, Static, Select
from textual import events, on

from .shortcuts import ACTIONS, GENERAL
from .config import (
    load_config,
    preflight_config,
    PreflightResult,
    Project as ConfigProject,
)
from .theme import load_theme_colors
from .models import GitStatus, Worktree
from .models.project import Project
from .models.worktree import WorktreeStatus
from .messages import OperationCompleted, WorktreeStatusChanged
from .services import (
    DockerManager,
    EnvironmentManager,
    EnvironmentOperation,
    EnvironmentOperationResult,
    LinkedOperationOutcome,
    LinkedRepositoryController,
    LinkedWorktreeManager,
    WorktreeCreationResult,
    WorktreeLogStore,
    WorktreeManager,
    WorkspaceManager,
    RESTART_ENVIRONMENT,
    START_ENVIRONMENT,
    STOP_ENVIRONMENT,
    get_git_status,
)
from .screens import (
    ConfirmDialog,
    CreateWorktreeScreen,
    DeleteWorktreeScreen,
    DeleteWorktreeResult,
    HelpScreen,
    LogsScreen,
)
from .widgets import (
    AppHeader,
    WorktreeChanged,
    WorktreeDetailView,
    WorktreeListView,
    WorktreeOpened,
    LinkedRepositoryAction,
    HeaderNotification,
)

GREETING_TEMPLATES = (
    "Hello {name}",
    "Bonjour {name}",
    "Hola {name}",
    "Ciao {name}",
    "Hallo {name}",
    "Olá {name}",
    "Dia dhuit {name}",
    "Hei {name}",
    "Cześć {name}",
    "Ahoj {name}",
    "Szia {name}",
    "Salut {name}",
    "Merhaba {name}",
    "Γεια σου {name}",
    "Привет {name}",
    "Привіт {name}",
    "你好 {name}",
    "こんにちは {name}",
    "안녕하세요 {name}",
    "नमस्ते {name}",
)


# Worktrees whose Git column is read concurrently
LIST_GIT_STATUS_CONCURRENCY = 8


def _random_greeting() -> str:
    account_name = getuser().strip()
    display_name = account_name[:1].upper() + account_name[1:]
    return choice(GREETING_TEMPLATES).format(name=display_name)


class FlotteApp(App):
    """Flotte - Manage docker-compose projects across git worktrees."""

    TITLE = "Flotte"
    SUB_TITLE = "Manage docker-compose projects across git worktrees"
    ENABLE_COMMAND_PALETTE = False

    # A description plus a help group is what puts a key on the help screen
    BINDINGS = [
        Binding("n", "new_worktree", "Create worktree", show=False, group=ACTIONS),
        Binding("d", "delete_worktree", "Delete worktree", show=False, group=ACTIONS),
        Binding("s", "start_environment", "Start services", show=False, group=ACTIONS),
        Binding("x", "stop_environment", "Stop services", show=False, group=ACTIONS),
        Binding("r", "refresh", "Refresh status", show=False, group=ACTIONS),
        Binding("R", "ride", "Go Ride", show=False, group=ACTIONS),
        Binding("o", "open_url", "Open web URL", show=False, group=ACTIONS),
        Binding("q", "quit", "Quit", show=False, group=GENERAL),
        Binding("b", "back_to_worktrees", "Back to worktrees", show=False, group=GENERAL),
        Binding(
            "escape",
            "escape",
            "Back, or quit the list",
            show=False,
            key_display="esc",
            group=GENERAL,
        ),
        Binding("?", "show_help", "Show help", show=False, group=GENERAL),
        Binding("tab", "focus_next", show=False),
        Binding("shift+tab", "focus_previous", show=False),
    ]

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: SeverityLevel = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        notification = Notification(
            message,
            title,
            severity,
            self.NOTIFICATION_TIMEOUT if timeout is None else timeout,
            markup=markup,
        )
        self.call_later(self._show_notification, notification)

    def _show_notification(self, notification: Notification) -> None:
        for screen in reversed(self.screen_stack):
            notifications = list(screen.query(HeaderNotification))
            if notifications:
                notifications[0].show_notification(notification)
                return
        super().notify(
            notification.message,
            title=notification.title,
            severity=notification.severity,
            timeout=max(notification.time_left, 0),
            markup=notification.markup,
        )

    def __init__(self):
        # Load config first to determine theme
        self.config = load_config()
        # Filled in by a worker once the UI is up; no problems are known before then
        self.preflight = PreflightResult(tuple(self.config.projects), ())

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

        initial_project = self.config.projects[0] if self.config.projects else None
        self._configure_project_runtime(initial_project)

        # Git status fetch state (serializes fetches, one subprocess at a time)
        self._git_fetch_running: bool = False
        self._git_fetch_queued: bool = False
        self._list_git_fetch_running: bool = False
        self._list_git_fetch_queued: bool = False

        # Kept on the app so the logs screen reopens with the same choice
        self.wrap_logs: bool = False

    def _configure_project_runtime(
        self, config_project: ConfigProject | None
    ) -> None:
        """Build the state and services scoped to one configured project."""
        self.current_config_project = config_project
        self.log_store = WorktreeLogStore(
            config_project.name if config_project else "flotte"
        )
        self.project = None
        self.worktree_manager = None
        self.environment_manager = None
        self.workspace_manager = None
        self.linked_repository_controller: LinkedRepositoryController | None = None
        self.selected_worktree = None

        if config_project is None:
            return

        self.worktree_manager = WorktreeManager(
            main_repo_path=Path(config_project.repository_path),
            worktree_path_template=config_project.worktree_path,
        )
        self.environment_manager = EnvironmentManager(
            Path(config_project.repository_path),
            config_project.env_file,
            config_project.clone_paths,
            config_project.post_create_commands,
            self.log_store,
        )
        self.project = Project(self.environment_manager)
        if config_project.linked_repositories:
            manager = LinkedWorktreeManager(
                config_project.linked_repositories,
                self.log_store,
            )
            self.linked_repository_controller = LinkedRepositoryController(
                manager,
                self.log_store,
            )
        self.workspace_manager = WorkspaceManager(
            self.worktree_manager,
            self.environment_manager,
            self.log_store,
            self.linked_repository_controller,
        )

    def compose(self) -> ComposeResult:
        # Show no-config screen if no projects configured.
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
                            "Add an entry under projects: with name, repository_path, "
                            "and worktree_path.",
                            id="no-config-help"
                        )
                        if self.config.warnings:
                            yield Static(
                                "\n".join(self.config.warnings),
                                id="no-config-warnings",
                            )
                    with Horizontal(id="dialog-buttons"):
                        yield Button("Quit", id="quit-btn", variant="error")
            return

        # Custom header with project selector
        yield AppHeader(
            Select(
                options=[(p.name, p) for p in self.config.projects],
                value=self.current_config_project,
                id="project-selector",
                allow_blank=False,
            ),
            Static(self.current_config_project.name, id="project-name"),
        )

        with ContentSwitcher(initial="list-view", id="view-switcher"):
            yield WorktreeListView(self.config.warnings, id="list-view")
            yield WorktreeDetailView(id="details-view")

    def _set_view(self, *, show_details: bool) -> None:
        """Switch between the worktree list and selected-worktree details."""
        self.query_one("#view-switcher", ContentSwitcher).current = (
            "details-view" if show_details else "list-view"
        )
        self.query_one("#project-selector").display = not show_details
        project_name = self.query_one("#project-name", Static)
        project_name.update(self.current_config_project.name)
        project_name.display = show_details

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

        self._update_container_view(refresh_linked_repositories=True)
        if fetch_git_status:
            self.run_worker(self._fetch_git_status())

    @on(Select.Changed, "#project-selector")
    def on_project_changed(self, event: Select.Changed) -> None:
        """Handle project selection change."""
        if self.workspace_manager is None:
            return
        if self.workspace_manager.has_active_operations():
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

        self._configure_project_runtime(config_project)

        # Clear UI state
        self._clear_ui_state()
        self._show_worktree_list()

        self._activate_current_project()

    def _current_project_problems(self) -> tuple[str, ...]:
        if self.current_config_project is None:
            return ()
        return self.preflight.problems_for(self.current_config_project)

    def _activate_current_project(self) -> None:
        """Show the selected project's problems or start its normal refresh loop."""
        problems = self._current_project_problems()
        self.query_one(WorktreeListView).show_project_problems(problems)
        if problems:
            # Preflight can land after a project already started polling
            if self.project:
                self.project.stop_polling()
            return
        self.run_worker(self.refresh_worktrees())
        if self.project:
            self.project.start_polling(self)

    def _clear_ui_state(self) -> None:
        """Clear all UI widgets to blank state."""
        self.query_one(WorktreeListView).reset_worktrees()
        self.query_one(WorktreeDetailView).reset_worktree()

    def on_mount(self) -> None:
        """Initialize app and start polling."""
        # No-config mode: just focus the quit button
        if not self.config.projects:
            self.query_one("#quit-btn", Button).focus()
            return

        self._show_worktree_list()
        self.run_worker(self._run_preflight())

        if self.config.warnings:
            self.notify(self._config_warning_summary(), severity="warning", markup=False)
        else:
            self.notify(_random_greeting(), markup=False)

    def _config_warning_summary(self) -> str:
        """A short header line; the list view carries the detail."""
        count = len(self.config.warnings)
        if count == 1:
            return self.config.warnings[0]
        return f"{count} problems in your config file"

    async def _run_preflight(self) -> None:
        """Validate Docker and the project paths without blocking the first paint."""
        self.preflight = await asyncio.to_thread(preflight_config, self.config)
        self._activate_current_project()

    async def refresh_worktrees(self) -> None:
        """Discover and display all worktrees."""
        if not self.workspace_manager or not self.project:
            return  # No project selected

        discovered = await self.workspace_manager.discover()

        # Copy discovered worktrees to Project model
        self.project.worktrees.clear()
        for wt in discovered:
            self.project.worktrees[wt.name] = wt

        # Update header dropdown
        list_view = self.query_one(WorktreeListView)
        list_view.refresh_worktrees(list(self.project.worktrees.values()))

        # Auto-select first worktree if none selected
        if self.project.worktrees and self.selected_worktree is None:
            first_wt = list(self.project.worktrees.values())[0]
            self.selected_worktree = first_wt
            list_view.select_worktree(self.selected_worktree)

        # Poll once immediately to get initial status
        if self.project:
            await self.project.poll_once()
            self._update_ui_after_status_change()
        self.run_worker(self._fetch_list_git_statuses())

    def _sync_worktree_ui(self) -> None:
        """Update UI from existing worktrees (no discovery)."""
        if not self.project:
            return
        self.query_one(WorktreeListView).refresh_worktrees(
            list(self.project.worktrees.values())
        )

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

        list_view = self.query_one(WorktreeListView)
        if changed_worktree is None:
            list_view.refresh_worktrees(list(self.project.worktrees.values()))
        else:
            list_view.update_worktree_status(changed_worktree)

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

    def _update_container_view(self, *, refresh_linked_repositories: bool = False) -> None:
        """Synchronize the selected worktree's detail region."""
        selected_busy = self.workspace_manager.is_busy(
            self.selected_worktree.name if self.selected_worktree else None
        )
        self.query_one(WorktreeDetailView).sync_worktree(
            self.selected_worktree,
            busy=selected_busy,
            refresh_linked_repositories=refresh_linked_repositories,
        )

    def _update_breadcrumb(self) -> None:
        """Show the selected worktree as the current breadcrumb segment."""
        self.query_one(WorktreeDetailView).update_breadcrumb(self.selected_worktree)

    def _refresh_linked_repositories(self) -> None:
        self.query_one(WorktreeDetailView).refresh_linked_repositories(
            self.selected_worktree
        )

    def on_linked_repository_action(self, event: LinkedRepositoryAction) -> None:
        handlers = {
            "link": partial(self._request_link_operation, "link"),
            "start": partial(self._request_link_operation, "start"),
            "stop": partial(self._request_link_operation, "stop"),
            "restart": partial(self._request_link_operation, "restart"),
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
            "btn-logs": self.action_show_logs,
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
                    get_git_status(wt.path),
                    self.linked_repository_controller.statuses(wt)
                    if self.linked_repository_controller else self._empty_linked_statuses(),
                )
                if self._git_fetch_queued:
                    continue
                if self.selected_worktree and self.selected_worktree.name == wt.name:
                    wt.git_status = git_status
                    self.query_one(WorktreeListView).update_git_status(
                        wt.name, git_status
                    )
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
                # Read the whole list at once, but keep git off every core
                limit = asyncio.Semaphore(LIST_GIT_STATUS_CONCURRENCY)
                await asyncio.gather(
                    *(
                        self._fetch_one_list_git_status(worktree, limit)
                        for worktree in worktrees
                    )
                )
                if not self._list_git_fetch_queued:
                    return
        finally:
            self._list_git_fetch_running = False

    async def _fetch_one_list_git_status(
        self, worktree: Worktree, limit: asyncio.Semaphore
    ) -> None:
        """Show one row's Git column as soon as its status lands."""
        async with limit:
            git_status = await get_git_status(worktree.path)
        if not self.project or self.project.worktrees.get(worktree.name) is not worktree:
            return  # Refreshed or deleted while we were reading it
        worktree.git_status = git_status
        self.query_one(WorktreeListView).update_git_status(
            worktree.name, git_status
        )

    async def _empty_linked_statuses(self) -> dict[str, GitStatus]:
        return {}

    # Action methods

    def action_refresh(self) -> None:
        """Refresh worktree list and container status."""
        if self._current_project_problems():
            self.notify("Fix this project's configuration before refreshing", severity="warning")
            return
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
        self._run_compose_operation(START_ENVIRONMENT)

    def action_stop_environment(self) -> None:
        """Stop Docker environment."""
        self._run_compose_operation(STOP_ENVIRONMENT)

    def action_restart_environment(self) -> None:
        """Restart Docker environment."""
        self._run_compose_operation(RESTART_ENVIRONMENT)

    def _run_compose_operation(self, operation: EnvironmentOperation) -> None:
        """Claim the selected worktree, then run the command in the background."""
        if not self.selected_worktree:
            return

        wt = self.selected_worktree
        task = self.workspace_manager.run_environment(
            wt,
            operation,
            self._update_container_view,
        )
        if task is None:
            self.notify("Operation in progress", severity="warning")
            return

        self.run_worker(
            self._finish_environment_operation(wt, operation, task),
            name=f"op-{operation.name}",
            exclusive=False,
        )

    async def _finish_environment_operation(
        self,
        wt: Worktree,
        operation: EnvironmentOperation,
        task: asyncio.Task[EnvironmentOperationResult],
    ) -> None:
        try:
            result = await task
            if not result.succeeded:
                self.log.error(f"{operation.name} failed: {result.reason}")
                self.notify(
                    f"Failed to {operation.name}: {result.reason}",
                    severity="error",
                )
        except asyncio.CancelledError:
            self.log.warning(f"{operation.name} cancelled: {wt.name}")
            raise

    def action_new_worktree(self) -> None:
        """Handle New button - opens dialog."""
        if not self.workspace_manager or not self.project or not self.worktree_manager:
            return
        if self._current_project_problems():
            self.notify("Fix this project's configuration before creating a worktree", severity="warning")
            return
        if self.workspace_manager.has_active_operations():
            self.notify("Operation in progress", severity="warning")
            return

        self.push_screen(
            CreateWorktreeScreen(
                self.workspace_manager,
                {
                    worktree.branch
                    for worktree in self.project.worktrees.values()
                },
            ),
            callback=self._on_create_dialog_result
        )

    def _on_create_dialog_result(self, result: WorktreeCreationResult | None) -> None:
        """Callback when create dialog dismissed."""
        if result is None:
            return  # Cancelled or failed

        # Refresh worktrees to show the new one
        self.run_worker(self._finish_create_worktree(result.worktree))

    async def _finish_create_worktree(self, worktree: Worktree) -> None:
        """Finish worktree creation after modal is done."""
        if not self.project:
            return
        if self.linked_repository_controller:
            self.linked_repository_controller.attach(worktree)
        # Add the worktree to our project model
        self.project.worktrees[worktree.name] = worktree
        self._sync_worktree_ui()
        self.selected_worktree = worktree
        self.query_one(WorktreeListView).select_worktree(worktree)
        self._show_worktree_details()
        await self.project.poll_once()
        self._update_ui_after_status_change(worktree)
        self.notify(f"Created {worktree.name}", severity="information")

    def action_delete_worktree(self) -> None:
        """Open the staged worktree deletion flow."""
        if not self.selected_worktree or not self.project:
            return
        if self.workspace_manager.is_busy(self.selected_worktree.name):
            self.notify("Operation in progress", severity="warning")
            return
        if self.selected_worktree.is_main:
            self.notify("Cannot delete main environment", severity="error")
            return

        wt = self.selected_worktree
        if wt.name not in self.project.worktrees:
            self.notify("Worktree no longer exists", severity="error")
            return

        self._clear_action_focus()
        self.push_screen(
            DeleteWorktreeScreen(wt, self.workspace_manager),
            callback=self._on_delete_result,
        )

    def _request_link_operation(
        self,
        action: str,
        repository_name: str,
        worktree: Worktree | None = None,
    ) -> None:
        worktree = worktree or self.selected_worktree
        if not worktree or not self.linked_repository_controller:
            return
        task = self.workspace_manager.run_linked(
            worktree,
            repository_name,
            action,
            self._update_container_view,
        )
        if task is None:
            self.notify("Operation in progress", severity="warning")
            return
        self.run_worker(
            self._finish_linked_operation(action, task),
            name=f"op-{action}-linked",
            exclusive=False,
        )

    async def _finish_linked_operation(self, action: str, task) -> None:
        outcome = await task
        if action == "link" or outcome.succeeded:
            self._update_container_view(refresh_linked_repositories=True)
        self._notify_linked_outcome(outcome)

    def _notify_linked_outcome(self, outcome: LinkedOperationOutcome) -> None:
        self.notify(
            outcome.message,
            severity="information" if outcome.succeeded else "error",
        )

    def _request_delete_link(self, repository_name: str) -> None:
        if not self.selected_worktree or not self.linked_repository_controller:
            return
        self.run_worker(self._prepare_delete_link(self.selected_worktree, repository_name))

    async def _prepare_delete_link(self, worktree: Worktree, repository_name: str) -> None:
        if await self.linked_repository_controller.has_changes(
            worktree, repository_name
        ):
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
        self._request_link_operation("unlink", repository_name, worktree)

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
        self.log_store.remove(deleted_name)

        self._sync_worktree_ui()
        main_wt = next(
            (w for w in self.project.worktrees.values() if w.is_main),
            None
        )
        if main_wt:
            self.selected_worktree = main_wt
            self.query_one(WorktreeListView).select_worktree(main_wt)
        self._show_worktree_list()

    def action_show_help(self) -> None:
        """Show help screen - '?' key."""
        self.push_screen(HelpScreen())

    def action_show_logs(self) -> None:
        """Show all logs for the selected worktree."""
        if not self.selected_worktree:
            return
        log_path = self.log_store.path_for(self.selected_worktree.name)
        self._clear_action_focus()
        self.push_screen(
            LogsScreen(
                self.selected_worktree.name,
                log_path,
                DockerManager(
                    self.selected_worktree.path,
                    self.selected_worktree.compose_project_name,
                ),
                {
                    container.name: container.service
                    for container in self.selected_worktree.containers.values()
                    if container.name and container.name != "-"
                },
                self.current_config_project.container_log_services,
                self.selected_worktree.linked_worktrees,
                self.current_config_project.name,
                self._show_worktree_list_from_logs,
                self._show_worktree_details_from_logs,
                wrap=self.wrap_logs,
            )
        )

    def _show_worktree_list_from_logs(self) -> None:
        self.pop_screen()
        self._show_worktree_list()

    def _show_worktree_details_from_logs(self) -> None:
        self.pop_screen()
        self._show_worktree_details()

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
