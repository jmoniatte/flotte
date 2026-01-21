from textual.widgets import Static
from textual.reactive import reactive

from ..models.worktree import WorktreeStatus
from ..theme import get_status_style, WORKTREE_STATUS_TEXT, DEFAULT_COLORS


class StatusLine(Static):
    """Shows the current worktree status above the container table."""

    status: reactive[WorktreeStatus] = reactive(WorktreeStatus.UNKNOWN)

    def watch_status(self, value: WorktreeStatus) -> None:
        """Update display when status changes."""
        # Guard: app may not be available during early reactive updates
        if hasattr(self, 'app') and self.app:
            colors = self.app.theme_colors
        else:
            colors = DEFAULT_COLORS

        icon, color = get_status_style(value, colors)
        text = WORKTREE_STATUS_TEXT.get(value, WORKTREE_STATUS_TEXT[WorktreeStatus.UNKNOWN])
        self.update(f"[{color}]{icon}[/{color}]  {text}")
