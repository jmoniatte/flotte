from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button, Static

from ...formatters import format_git_status
from ...models import Worktree, WorktreeStatus
from ..container_controls import ContainerControls
from ..container_table import ContainerTable
from ..linked_repositories import LinkedRepositories
from ..table_rules import DashedTableFooter
from ..web_link import WebLink


class WorktreeDetailView(Container):
    """Container and linked-repository controls for one worktree."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="breadcrumbs"):
            yield Static("Worktrees", id="breadcrumb-worktrees")
            yield Static(">", id="breadcrumb-separator")
            yield Static("", id="breadcrumb-worktree")
            yield Static("", id="breadcrumb-git-status")
            yield Static("", classes="spacer")
            yield Button("Logs", id="btn-logs")
            yield Button("Go Ride", id="btn-ride")
        with Container(id="containers-box"):
            yield ContainerTable(id="container-table")
            yield DashedTableFooter(id="container-table-footer-rule")
            yield Static("Loading containers...", id="container-loading")
            yield ContainerControls(id="container-controls")
            yield LinkedRepositories(id="linked-repositories")

    def reset_worktree(self) -> None:
        self.query_one("#container-table", ContainerTable).worktree = None
        controls = self.query_one("#container-controls", ContainerControls)
        controls.status = WorktreeStatus.UNKNOWN
        controls.operation_active = False
        self.update_breadcrumb(None)

    def sync_worktree(
        self,
        worktree: Worktree | None,
        *,
        busy: bool,
        refresh_linked_repositories: bool = False,
    ) -> None:
        table = self.query_one("#container-table", ContainerTable)
        if worktree is None:
            table.worktree = None
        elif table.worktree is None or table.worktree.name != worktree.name:
            table.worktree = worktree
        else:
            table.sync_worktree(worktree)

        status = worktree.status if worktree else WorktreeStatus.UNKNOWN
        containers_loaded = bool(worktree and worktree.has_polled)
        table.display = containers_loaded
        self.query_one("#container-table-footer-rule").display = containers_loaded
        self.query_one("#container-loading", Static).display = not containers_loaded

        controls = self.query_one("#container-controls", ContainerControls)
        controls.status = status
        controls.operation_active = busy
        self.query_one("#btn-ride", Button).disabled = busy
        self.query_one("#container-url", WebLink).set_url(
            worktree.web_url if worktree else None
        )

        delete_button = self.query_one("#btn-delete-worktree", Button)
        delete_button.display = bool(
            worktree
            and not worktree.is_main
            and status == WorktreeStatus.STOPPED
            and all(
                link.path is None
                or not link.can_start
                or link.process_status == "stopped"
                for link in worktree.linked_worktrees
            )
            and not busy
        )
        delete_button.disabled = False

        self.update_breadcrumb(worktree)
        if refresh_linked_repositories:
            self.refresh_linked_repositories(worktree)

    def update_breadcrumb(self, worktree: Worktree | None) -> None:
        self.query_one("#breadcrumb-worktree", Static).update(
            worktree.name if worktree else ""
        )
        self.query_one("#breadcrumb-git-status", Static).update(
            format_git_status(
                worktree.git_status if worktree else None,
                self.app.theme_colors,
                prefix="· ",
            )
        )

    def refresh_linked_repositories(self, worktree: Worktree | None) -> None:
        widget = self.query_one("#linked-repositories", LinkedRepositories)
        if not widget.update_worktree(worktree):
            self._mount_linked_repositories(worktree)

    @work(group="linked-repositories", exclusive=True)
    async def _mount_linked_repositories(self, worktree: Worktree | None) -> None:
        await self.query_one(
            "#linked-repositories", LinkedRepositories
        ).show_worktree(worktree)
