"""Application workflows for linked repositories."""

from dataclasses import dataclass
from time import perf_counter

from ..models import GitStatus, Worktree
from .linked_worktree_manager import LinkedWorktreeManager
from .worktree_log import WorktreeLogStore


@dataclass(frozen=True, slots=True)
class LinkedOperationOutcome:
    succeeded: bool
    message: str


class LinkedRepositoryController:
    """Run linked-repository operations and record their outcomes."""

    def __init__(
        self,
        manager: LinkedWorktreeManager,
        log_store: WorktreeLogStore,
    ) -> None:
        self._manager = manager
        self._log_store = log_store

    def attach(self, worktree: Worktree) -> None:
        self._manager.attach(worktree)

    async def statuses(
        self,
        worktree: Worktree,
        *,
        strict: bool = False,
    ) -> dict[str, GitStatus]:
        return await self._manager.linked_statuses(worktree, strict=strict)

    async def remove_all(self, worktree: Worktree) -> None:
        await self._manager.remove_links(worktree)

    async def link(
        self, worktree: Worktree, repository_name: str
    ) -> LinkedOperationOutcome:
        started_at = perf_counter()
        try:
            linked = await self._manager.create_link(worktree, repository_name)
            if linked.state == "error":
                message = "Link setup failed"
                if linked.error:
                    message += f": {linked.error}"
                outcome = LinkedOperationOutcome(False, message)
            else:
                outcome = LinkedOperationOutcome(True, f"Linked {repository_name}")
        except Exception as error:
            outcome = LinkedOperationOutcome(False, f"Link setup failed: {error}")

        self._log_store.record_elapsed(
            worktree.name,
            f"Linked {repository_name}",
            started_at,
            outcome.succeeded,
        )
        return outcome

    async def run_lifecycle(
        self,
        worktree: Worktree,
        repository_name: str,
        action: str,
    ) -> LinkedOperationOutcome:
        operations = {
            "start": self._manager.start_link,
            "stop": self._manager.stop_link,
            "restart": self._manager.restart_link,
        }
        messages = {
            "start": ("Started", "Failed to start"),
            "stop": ("Stopped", "Failed to stop"),
            "restart": ("Restarted", "Failed to restart"),
        }
        if action not in operations:
            raise ValueError(f"Unknown linked-repository action: {action}")

        past_tense, failure = messages[action]
        started_at = perf_counter()
        try:
            result = await operations[action](worktree, repository_name)
            outcome = LinkedOperationOutcome(True, f"{past_tense} {repository_name}")
            log_message = f"{outcome.message} (PID: {result.pid})"
        except Exception as error:
            outcome = LinkedOperationOutcome(
                False,
                f"{failure} {repository_name}: {error}",
            )
            log_message = f"{past_tense} {repository_name}"

        self._log_store.record_elapsed(
            worktree.name,
            log_message,
            started_at,
            outcome.succeeded,
        )
        return outcome

    async def unlink(
        self, worktree: Worktree, repository_name: str
    ) -> LinkedOperationOutcome:
        started_at = perf_counter()
        try:
            await self._manager.remove_link(worktree, repository_name)
            self.attach(worktree)
            outcome = LinkedOperationOutcome(True, f"Unlinked {repository_name}")
        except Exception as error:
            outcome = LinkedOperationOutcome(
                False,
                f"Failed to unlink {repository_name}: {error}",
            )

        self._log_store.record_elapsed(
            worktree.name,
            f"Unlinked {repository_name}",
            started_at,
            outcome.succeeded,
        )
        return outcome

    async def has_changes(self, worktree: Worktree, repository_name: str) -> bool:
        status = (await self.statuses(worktree)).get(repository_name)
        return bool(status and status.has_changes)

    async def changed_repositories(self, worktree: Worktree) -> list[str]:
        statuses = await self.statuses(worktree, strict=True)
        return [name for name, status in statuses.items() if status.has_changes]
