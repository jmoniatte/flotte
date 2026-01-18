from textual.containers import Horizontal
from textual.widgets import Button, Static
from textual.reactive import reactive
from textual.css.query import NoMatches

from ..models.worktree import WorktreeStatus


class ContainerControls(Horizontal):
    """Control buttons for container actions."""

    DEFAULT_CSS = """
    ContainerControls {
        height: auto;
        padding: 1 1;
        align: left middle;
    }

    ContainerControls Button {
        margin: 0 1 0 0;
        min-width: 10;
        padding: 0 2;
    }

    ContainerControls .spacer {
        width: 1fr;
    }
    """

    status: reactive[WorktreeStatus] = reactive(WorktreeStatus.UNKNOWN)
    is_main: reactive[bool] = reactive(False)

    def compose(self):
        yield Button("Start", id="btn-container-start", variant="success")
        yield Button("Stop", id="btn-container-stop", variant="error")
        yield Button("Restart", id="btn-container-restart", variant="warning")
        yield Button("Go Ride", id="btn-ride")
        yield Static("", classes="spacer")
        yield Button("Delete", id="btn-delete-worktree", variant="warning")

    def watch_status(self, value: WorktreeStatus) -> None:
        """Enable/disable buttons based on status."""
        self._update_button_states()

    def watch_is_main(self, value: bool) -> None:
        """Hide delete button for main worktree."""
        try:
            delete_btn = self.query_one("#btn-delete-worktree", Button)
            delete_btn.display = not value
        except NoMatches:
            pass
        self._update_button_states()

    def _update_button_states(self) -> None:
        """Update all button states based on status and is_main."""
        try:
            start_btn = self.query_one("#btn-container-start", Button)
            stop_btn = self.query_one("#btn-container-stop", Button)
            restart_btn = self.query_one("#btn-container-restart", Button)
            ride_btn = self.query_one("#btn-ride", Button)
            delete_btn = self.query_one("#btn-delete-worktree", Button)
        except NoMatches:
            return  # Widgets not mounted yet

        status = self.status

        if status == WorktreeStatus.STOPPED:
            start_btn.disabled = False
            stop_btn.disabled = True
            restart_btn.disabled = True
            ride_btn.disabled = True
            delete_btn.disabled = self.is_main
        elif status == WorktreeStatus.RUNNING:
            start_btn.disabled = False
            stop_btn.disabled = False
            restart_btn.disabled = False
            ride_btn.disabled = False
            delete_btn.disabled = True
        elif status in (WorktreeStatus.STARTING, WorktreeStatus.STOPPING,
                       WorktreeStatus.CREATING, WorktreeStatus.DELETING,
                       WorktreeStatus.ERROR):
            start_btn.disabled = True
            stop_btn.disabled = True
            restart_btn.disabled = True
            ride_btn.disabled = True
            delete_btn.disabled = True
        else:  # UNKNOWN
            start_btn.disabled = False
            stop_btn.disabled = True
            restart_btn.disabled = True
            ride_btn.disabled = True
            delete_btn.disabled = True
