from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Static

from ..models.worktree import WorktreeStatus


class StatusLine(Horizontal):
    """Shows the Containers subtitle and worktree-level actions."""

    status: reactive[WorktreeStatus] = reactive(WorktreeStatus.UNKNOWN)

    def compose(self):
        yield Static("Containers", classes="containers-title")
        yield Static("", classes="spacer")
        delete_button = Button("Delete", id="btn-delete-worktree", variant="warning")
        delete_button.active_effect_duration = 0
        yield delete_button
