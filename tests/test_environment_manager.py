import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flotte.models import Worktree
from flotte.models.container import ContainerState
from flotte.models.worktree import WorktreeStatus
from flotte.services.environment_manager import (
    EnvironmentManager,
)


class EnvironmentManagerTests(unittest.TestCase):
    def test_cleanup_without_a_compose_file_does_not_require_docker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree_path = root / "feature"
            worktree_path.mkdir()
            worktree = Worktree(
                "feature",
                worktree_path,
                compose_project_name="project-feature",
            )
            manager = EnvironmentManager(root)

            with patch(
                "flotte.services.environment_manager.DockerManager._run_sync"
            ) as run:
                asyncio.run(manager.cleanup(worktree))

            run.assert_not_called()

    def test_reconcile_updates_containers_and_completes_transient_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docker-compose.yml").write_text("services: {}\n")
            worktree = Worktree(
                "feature",
                root,
                compose_project_name="flotte-feature",
            )
            worktree.start_operation(
                WorktreeStatus.STARTING,
                WorktreeStatus.RUNNING,
            )
            manager = EnvironmentManager(root)
            containers = {
                "flotte-feature": [
                    {
                        "Service": "web",
                        "State": "running",
                        "Status": "Up",
                        "Ports": "0.0.0.0:3000->3000/tcp",
                    }
                ]
            }

            with (
                patch(
                    "flotte.services.environment_manager.get_all_containers_by_project",
                    new=AsyncMock(return_value=containers),
                ),
                patch(
                    "flotte.services.environment_manager.DockerManager.get_services",
                    new=AsyncMock(return_value=["web", "worker"]),
                ) as services,
            ):
                first = asyncio.run(manager.reconcile([worktree]))[0]
                second = asyncio.run(manager.reconcile([worktree]))[0]

            self.assertTrue(first.changed)
            self.assertEqual(first.completed_operation, WorktreeStatus.STARTING)
            self.assertEqual(worktree.status, WorktreeStatus.RUNNING)
            self.assertEqual(worktree.containers["web"].ports, ["3000"])
            self.assertEqual(
                worktree.containers["worker"].state,
                ContainerState.EXITED,
            )
            self.assertFalse(second.changed)
            self.assertIsNone(second.completed_operation)
            services.assert_awaited_once_with()

    def test_configure_allocates_ports_and_attaches_compose_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main_path = root / "main"
            existing_path = root / "existing"
            created_path = root / "created"
            main_path.mkdir()
            existing_path.mkdir()
            created_path.mkdir()
            (main_path / ".env").write_text(
                "COMPOSE_PROJECT_NAME=flotte\nAPP_PORT=3000\nNAME=test\n"
            )
            (existing_path / ".env").write_text(
                "COMPOSE_PROJECT_NAME=flotte-existing\nAPP_PORT=3100\n"
            )
            existing = Worktree("existing", existing_path)
            created = Worktree("created", created_path)
            manager = EnvironmentManager(main_path)

            manager.configure(created, [existing])
            manager.attach(existing)

            self.assertEqual(created.compose_project_name, "flotte-created")
            self.assertEqual(existing.compose_project_name, "flotte-existing")
            self.assertEqual(
                (created_path / ".env").read_text(),
                "COMPOSE_PROJECT_NAME=flotte-created\nAPP_PORT=3200\nNAME=test\n",
            )
