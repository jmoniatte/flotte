import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from flotte.messages import OperationCompleted, WorktreeStatusChanged
from flotte.models import Worktree
from flotte.models.project import Project
from flotte.models.worktree import WorktreeStatus
from flotte.services.environment_manager import (
    EnvironmentManager,
    EnvironmentReconciliation,
)


class ProjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_delegates_reconciliation_and_posts_state_messages(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        environment = Mock(spec=EnvironmentManager)
        environment.reconcile = AsyncMock(
            return_value=[
                EnvironmentReconciliation(
                    worktree,
                    changed=True,
                    completed_operation=WorktreeStatus.STARTING,
                )
            ]
        )
        project = Project(environment)
        project.worktrees[worktree.name] = worktree
        project._app = Mock()

        await project.poll_once()

        environment.reconcile.assert_awaited_once_with([worktree])
        messages = [item.args[0] for item in project._app.post_message.call_args_list]
        self.assertIsInstance(messages[0], WorktreeStatusChanged)
        self.assertIsInstance(messages[1], OperationCompleted)
