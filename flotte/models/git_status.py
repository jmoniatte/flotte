"""Typed Git repository status values."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GitStatus:
    """Summary of repository changes and upstream divergence."""

    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    ahead: int = 0
    behind: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.staged or self.unstaged or self.untracked)
