from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from ...models import GitStatus, Worktree
from ..worktree_header import WorktreeHeader


class WorktreeListView(Container):
    """Worktree browser and its project-level state."""

    def __init__(self, warnings: Iterable[str] = (), **kwargs) -> None:
        super().__init__(**kwargs)
        self._warnings = tuple(warnings)

    def compose(self) -> ComposeResult:
        yield Static("Worktrees", id="worktrees-title")
        if self._warnings:
            yield Static("\n".join(self._warnings), id="config-warnings")
        yield Static("", id="project-problems")
        with Container(id="worktrees-box"):
            yield WorktreeHeader(id="worktree-header")
        with Horizontal(id="worktree-controls"):
            yield Button("New", id="btn-new-worktree", variant="primary")
            yield Button("Refresh", id="btn-refresh", variant="default")
            yield Static("", classes="spacer")
            yield Button("Help", id="btn-help", variant="default")

    def show_project_problems(self, problems: Iterable[str]) -> None:
        problems = tuple(problems)
        problem_view = self.query_one("#project-problems", Static)
        problem_view.update("\n".join(problems))
        problem_view.display = bool(problems)
        self.query_one("#worktrees-box").display = not problems
        for button_id in ("#btn-new-worktree", "#btn-refresh"):
            button = self.query_one(button_id, Button)
            button.display = not problems
            button.disabled = bool(problems)

    def reset_worktrees(self) -> None:
        self.header.refresh_worktrees([])

    def refresh_worktrees(self, worktrees: list[Worktree]) -> None:
        self.header.refresh_worktrees(worktrees)

    def select_worktree(self, worktree: Worktree) -> None:
        self.header.select_worktree(worktree)

    def update_worktree_status(self, worktree: Worktree) -> None:
        self.header.update_worktree_status(worktree)

    def update_git_status(
        self, worktree_name: str, git_status: GitStatus | None
    ) -> None:
        self.header.update_git_status(worktree_name, git_status)

    @property
    def header(self) -> WorktreeHeader:
        return self.query_one("#worktree-header", WorktreeHeader)
