from dataclasses import dataclass

from ..models.worktree import WorktreeStatus


@dataclass
class TransientState:
    """Transient operation state for a worktree."""

    status: WorktreeStatus
    expected: WorktreeStatus | None = None


class TransientStateManager:
    """Central store for transient operation states, keyed by worktree name.

    This solves the "status flash" bug where object replacement during polling
    caused transient state to be lost. By storing state centrally keyed by name,
    object replacement becomes irrelevant.
    """

    def __init__(self):
        self._states: dict[str, TransientState] = {}

    def start_operation(
        self, name: str, transient: WorktreeStatus, expected: WorktreeStatus | None = None
    ) -> None:
        """Begin operation with transient status.

        Args:
            name: Worktree name
            transient: Status to show during operation (STOPPING, STARTING, etc.)
            expected: Status that clears the transient when reached (STOPPED, RUNNING).
                      If None, transient must be cleared manually.
        """
        self._states[name] = TransientState(transient, expected)

    def clear_operation(self, name: str) -> None:
        """Clear transient status (operation completed or failed)."""
        self._states.pop(name, None)

    def get_transient(self, name: str) -> WorktreeStatus | None:
        """Get transient status for a worktree, if any."""
        state = self._states.get(name)
        return state.status if state else None

    def get_expected(self, name: str) -> WorktreeStatus | None:
        """Get expected status for a worktree, if any."""
        state = self._states.get(name)
        return state.expected if state else None

    def is_operation_pending(self, name: str) -> bool:
        """True if an operation is in progress for this worktree."""
        return name in self._states

    def check_and_clear(self, name: str, actual: WorktreeStatus) -> bool:
        """Clear if actual matches expected. Returns True if cleared."""
        state = self._states.get(name)
        if state and state.expected == actual:
            del self._states[name]
            return True
        return False
