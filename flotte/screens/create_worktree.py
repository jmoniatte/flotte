import re
from collections.abc import Collection
from dataclasses import dataclass

from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Input, Select, Checkbox, Button, Static, TabbedContent, TabPane
from textual.app import ComposeResult

from ..services import WorktreeCreationResult, WorktreeCreator

# Failures scroll by while the user watches creation, so they outlast the 5s default
FAILURE_TOAST_TIMEOUT = 20.0


@dataclass
class CreateWorktreeParams:
    """Parameters for creating a new worktree."""
    branch_name: str
    base_branch: str | None  # None if using existing branch
    clone_data: bool


class CreateWorktreeScreen(ModalScreen[WorktreeCreationResult | None]):
    """Modal screen for creating new worktrees."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        creator: WorktreeCreator,
        existing_branches: Collection[str],
    ):
        super().__init__()
        self.creator = creator
        self.worktree_manager = creator.manager
        self.existing_branches = frozenset(existing_branches)
        self._is_new_branch_mode: bool = True

    def compose(self) -> ComposeResult:
        with Vertical(id="create-dialog"):
            yield Static("New Worktree", id="dialog-title")

            with TabbedContent(id="branch-mode"):
                with TabPane("New branch", id="tab-new"):
                    with Horizontal(classes="form-row"):
                        yield Static("Branch name", classes="field-label")
                        yield Input(placeholder="feature/my-feature", id="branch-input")
                    with Horizontal(classes="form-row"):
                        yield Static("Base branch", classes="field-label")
                        yield Select([], id="base-branch", prompt="")
                with TabPane("Existing branch", id="tab-existing"):
                    with Horizontal(classes="form-row"):
                        yield Static("Select branch", classes="field-label")
                        yield Select([], id="existing-branch", prompt="")

            yield Checkbox("Clone volumes and bind mounts from main", id="clone-data", value=True)

            # Status area (hidden initially)
            with Horizontal(id="status-area"):
                yield Static("⟳", id="loading-icon")
                yield Static("Creating...", id="status-text")

            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Create", id="create-btn")

    def on_mount(self) -> None:
        # Hide status area initially
        self.query_one("#status-area").display = False
        self.query_one("#branch-input", Input).focus()
        self.run_worker(self._load_branches())

    async def _load_branches(self) -> None:
        """Fetch local git branches and populate both select widgets."""
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "--format=%(refname:short)",
            cwd=self.worktree_manager.main_repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        branches = []
        for line in stdout.decode().strip().split("\n"):
            branch = line.strip()
            if branch:
                branches.append(branch)

        # Sort with common branches first
        priority = ["beta", "master", "main", "develop"]
        def sort_key(b):
            try:
                return (0, priority.index(b))
            except ValueError:
                return (1, b.lower())

        branches.sort(key=sort_key)

        # Populate base-branch select (all branches for new branch mode)
        base_select = self.query_one("#base-branch", Select)
        if branches:
            base_select._allow_blank = False
            base_select.set_options([(b, b) for b in branches])
            base_select.value = branches[0]

        # Populate existing-branch select (only branches without worktrees)
        available_branches = [
            branch for branch in branches if branch not in self.existing_branches
        ]
        existing_select = self.query_one("#existing-branch", Select)
        if available_branches:
            existing_select._allow_blank = False
            existing_select.set_options([(b, b) for b in available_branches])
            existing_select.value = available_branches[0]
        else:
            existing_select.prompt = "No branches available"

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab switch between new and existing branch modes."""
        self._is_new_branch_mode = event.pane.id == "tab-new"

    def _validate_branch_name(self, value: str) -> bool:
        if not value or not value.strip():
            return False
        # Allow alphanumeric, dash, underscore, slash
        return bool(re.match(r'^[a-zA-Z0-9/_-]+$', value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()  # Prevent bubbling to app

        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return

        if event.button.id == "create-btn":
            clone_checkbox = self.query_one("#clone-data", Checkbox)

            if self._is_new_branch_mode:
                # New branch mode - validate and create new branch
                branch_input = self.query_one("#branch-input", Input)
                base_select = self.query_one("#base-branch", Select)

                branch_name = branch_input.value.strip()

                if not branch_name:
                    self.notify("Branch name is required", severity="error")
                    branch_input.focus()
                    return

                if not self._validate_branch_name(branch_name):
                    self.notify(
                        "Invalid branch name (use letters, numbers, -, _, /)",
                        severity="error"
                    )
                    branch_input.focus()
                    return

                params = CreateWorktreeParams(
                    branch_name=branch_name,
                    base_branch=str(base_select.value),
                    clone_data=clone_checkbox.value,
                )
            else:
                # Existing branch mode - use selected branch
                existing_select = self.query_one("#existing-branch", Select)

                if existing_select.value is None or existing_select.value == Select.BLANK:
                    self.notify("Please select a branch", severity="error")
                    existing_select.focus()
                    return

                params = CreateWorktreeParams(
                    branch_name=str(existing_select.value),
                    base_branch=None,  # None signals existing branch mode
                    clone_data=clone_checkbox.value,
                )

            self._show_creating_status()
            # Defer worker start to allow UI to update first
            self.call_later(lambda: self.run_worker(self._do_create(params)))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _show_creating_status(self) -> None:
        """Show creating status and disable controls."""
        # Hide form fields
        self.query_one("#branch-mode").display = False
        self.query_one("#clone-data").display = False
        self.query_one("#dialog-buttons").display = False
        # Show status
        self.query_one("#status-area").display = True
        # Force refresh
        self.refresh(layout=True)

    def _update_status(self, message: str) -> None:
        """Update status message."""
        self.query_one("#status-text", Static).update(message)

    def _notify_failure(self, message: str, severity: str = "warning") -> None:
        """Toast a failure that carries interpolated command output."""
        # markup=False: stderr and shell syntax contain [brackets] that break Textual markup
        self.notify(
            message,
            severity=severity,
            timeout=FAILURE_TOAST_TIMEOUT,
            markup=False,
        )

    async def _do_create(self, params: CreateWorktreeParams) -> None:
        """Perform the actual worktree creation."""
        try:
            result = await self.creator.create(
                params.branch_name,
                params.base_branch,
                clone_data=params.clone_data,
                on_progress=self._update_status,
            )
            for warning in result.warnings:
                self._notify_failure(warning)
            self.dismiss(result)
        except Exception as e:
            self._notify_failure(f"Creation failed: {e}", severity="error")
            self.dismiss(None)
