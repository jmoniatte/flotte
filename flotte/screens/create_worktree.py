import asyncio
import re
from dataclasses import dataclass

from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Input, Select, Checkbox, Button, Static, TabbedContent, TabPane
from textual.app import ComposeResult

from ..services import WorktreeManager
from ..models import Worktree


@dataclass
class CreateWorktreeParams:
    """Parameters for creating a new worktree."""
    branch_name: str
    base_branch: str | None  # None if using existing branch
    clone_data: bool


@dataclass
class CreateWorktreeResult:
    """Result of worktree creation."""
    worktree: Worktree
    params: CreateWorktreeParams


class CreateWorktreeScreen(ModalScreen[CreateWorktreeResult | None]):
    """Modal screen for creating new worktrees."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, worktree_manager: WorktreeManager):
        super().__init__()
        self.worktree_manager = worktree_manager
        self._all_branches: list[str] = []
        self._existing_worktree_branches: set[str] = set()
        self._is_new_branch_mode: bool = True

    def compose(self) -> ComposeResult:
        with Vertical(id="create-dialog"):
            yield Static("New Worktree", id="dialog-title")
            yield Static("", id="title-separator")

            with TabbedContent(id="branch-mode"):
                with TabPane("New branch", id="tab-new"):
                    yield Static("Branch name", classes="field-label")
                    yield Input(placeholder="feature/my-feature", id="branch-input")
                    yield Static("Base branch", classes="field-label")
                    yield Select([], id="base-branch", prompt="")
                with TabPane("Existing branch", id="tab-existing"):
                    yield Static("Select branch", classes="field-label")
                    yield Select([], id="existing-branch", prompt="")

            yield Checkbox("Clone volumes from main", id="clone-data", value=True)

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
        self._all_branches = branches

        # Get branches that already have worktrees
        self._existing_worktree_branches = {
            wt.branch for wt in self.worktree_manager.worktrees.values()
        }

        # Populate base-branch select (all branches for new branch mode)
        base_select = self.query_one("#base-branch", Select)
        if branches:
            base_select._allow_blank = False
            base_select.set_options([(b, b) for b in branches])
            base_select.value = branches[0]

        # Populate existing-branch select (only branches without worktrees)
        available_branches = [
            b for b in branches if b not in self._existing_worktree_branches
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

    async def _do_create(self, params: CreateWorktreeParams) -> None:
        """Perform the actual worktree creation."""
        try:
            # Create git worktree (uses asyncio.to_thread internally)
            self._update_status("Creating git worktree...")
            worktree = await self.worktree_manager.create_worktree(
                branch_name=params.branch_name,
                base_branch=params.base_branch,
            )

            # Clone volumes if requested
            if params.clone_data:
                self._update_status("Cloning data volumes...")
                main_env = self.worktree_manager._parse_env(
                    self.worktree_manager.main_repo_path
                )
                source_project = main_env.get(
                    "COMPOSE_PROJECT_NAME", self.worktree_manager.project_name
                )
                volumes = await self.worktree_manager.get_volumes()
                for i, vol in enumerate(volumes):
                    self._update_status(f"Cloning volume {i+1}/{len(volumes)}: {vol}...")
                    source_vol = f"{source_project}_{vol}"
                    target_vol = f"{worktree.compose_project_name}_{vol}"
                    # Use asyncio.to_thread to release event loop for UI updates
                    await asyncio.to_thread(
                        self.worktree_manager._run_command,
                        "docker", "volume", "create", target_vol
                    )
                    await asyncio.to_thread(
                        self.worktree_manager._run_command,
                        "docker", "run", "--rm",
                        "-v", f"{source_vol}:/source:ro",
                        "-v", f"{target_vol}:/dest",
                        "alpine", "sh", "-c", "cp -a /source/. /dest/",
                        timeout=300.0,
                    )

            # Dismiss with result
            self.dismiss(CreateWorktreeResult(worktree=worktree, params=params))

        except Exception as e:
            self.notify(f"Creation failed: {e}", severity="error")
            self.dismiss(None)
