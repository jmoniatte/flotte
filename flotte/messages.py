from __future__ import annotations

from textual.message import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models.worktree import Worktree


class WorktreeStatusChanged(Message):
    """Posted when a worktree's status changes during polling."""

    def __init__(self, worktree: Worktree):
        self.worktree = worktree
        super().__init__()
