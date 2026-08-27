from textual.containers import Horizontal
from textual.widgets import Button, Static
from textual.reactive import reactive
from textual.css.query import NoMatches

from ..models.worktree import WorktreeStatus
from .web_link import WebLink


class ContainerControls(Horizontal):
    """Control buttons for container actions."""

    status: reactive[WorktreeStatus] = reactive(WorktreeStatus.UNKNOWN)
    operation_active: reactive[bool] = reactive(False)

    def compose(self):
        yield Button("Start", id="btn-container-start", variant="success")
        yield Button("Stop", id="btn-container-stop", variant="error")
        yield Button("Restart", id="btn-container-restart", variant="warning")
        yield WebLink(id="container-url")
        yield Static("", classes="spacer")
        yield Button("Delete", id="btn-delete-worktree", variant="warning")

    def watch_status(self, value: WorktreeStatus) -> None:
        """Enable/disable buttons based on status."""
        self._update_button_states()

    def watch_operation_active(self, value: bool) -> None:
        """Lock buttons while an operation is running."""
        self._update_button_states()

    def _update_button_states(self) -> None:
        """Update container lifecycle buttons based on status."""
        try:
            start_btn = self.query_one("#btn-container-start", Button)
            stop_btn = self.query_one("#btn-container-stop", Button)
            restart_btn = self.query_one("#btn-container-restart", Button)
        except NoMatches:
            return  # Widgets not mounted yet

        status = self.status

        # An in-flight operation locks everything until it settles
        if self.operation_active:
            start_btn.disabled = True
            stop_btn.disabled = True
            restart_btn.disabled = True
        elif status == WorktreeStatus.STOPPED:
            start_btn.disabled = False
            stop_btn.disabled = True
            restart_btn.disabled = True
        elif status == WorktreeStatus.RUNNING:
            start_btn.disabled = True
            stop_btn.disabled = False
            restart_btn.disabled = False
        elif status in (WorktreeStatus.STARTING, WorktreeStatus.STOPPING):
            # STARTING/STOPPING here means containers are stuck part-way with no
            # operation running - the user needs the controls to recover
            start_btn.disabled = False
            stop_btn.disabled = False
            restart_btn.disabled = False
        else:  # UNKNOWN
            start_btn.disabled = False
            stop_btn.disabled = True
            restart_btn.disabled = True
