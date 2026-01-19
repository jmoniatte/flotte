from __future__ import annotations

from textual.message import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models.worktree import Worktree, WorktreeStatus


class WorktreeStatusChanged(Message):
    """Posted when a worktree's status changes during polling."""

    def __init__(self, worktree: Worktree):
        self.worktree = worktree
        super().__init__()


class OperationCompleted(Message):
    """Posted when a start/stop/restart operation completes successfully."""

    def __init__(self, worktree: Worktree, operation: WorktreeStatus):
        self.worktree = worktree
        self.operation = operation  # STARTING or STOPPING
        super().__init__()
