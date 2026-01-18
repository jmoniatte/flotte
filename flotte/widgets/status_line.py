from textual.widgets import Static
from textual.reactive import reactive

from ..models.worktree import WorktreeStatus


STATUS_TEXT = {
    WorktreeStatus.STOPPED: ("○", "Services stopped", "red"),
    WorktreeStatus.STARTING: ("◐", "Services starting...", "green"),
    WorktreeStatus.RUNNING: ("●", "Services running", "green"),
    WorktreeStatus.STOPPING: ("◐", "Services stopping...", "yellow"),
    WorktreeStatus.CREATING: ("◐", "Services creating...", "cyan"),
    WorktreeStatus.DELETING: ("◐", "Services deleting...", "red"),
    WorktreeStatus.ERROR: ("✗", "Error", "red"),
    WorktreeStatus.UNKNOWN: ("?", "Unknown", "dim"),
}


class StatusLine(Static):
    """Shows the current worktree status above the container table."""

    status: reactive[WorktreeStatus] = reactive(WorktreeStatus.UNKNOWN)

    def watch_status(self, value: WorktreeStatus) -> None:
        """Update display when status changes."""
        icon, text, color = STATUS_TEXT.get(
            value, STATUS_TEXT[WorktreeStatus.UNKNOWN]
        )
        self.update(f"[{color}]{icon}[/{color}]  {text}")
