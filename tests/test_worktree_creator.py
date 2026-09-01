import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from flotte.models import Worktree
from flotte.services.docker_manager import DockerManager
from flotte.services.environment_manager import EnvironmentManager
from flotte.services.worktree_creator import WorktreeCreator


class WorktreeCreatorTests(unittest.TestCase):
    def test_create_prepares_data_reports_failures_and_skips_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            main_path = Path(directory) / "main"
            worktree_path = Path(directory) / "worktree"
            main_path.mkdir()
            worktree_path.mkdir()
            (main_path / "bind").mkdir()
            (main_path / "extra").mkdir()
            worktree = Worktree(
                "feature",
                worktree_path,
                "feature",
                "project-feature",
            )
            manager = Mock()
            manager.main_repo_path = main_path
            manager.post_create_commands = ("setup",)
            manager.create_worktree = AsyncMock(return_value=worktree)
            manager.discover_worktrees = AsyncMock(return_value=[worktree])
            environment = Mock(spec=EnvironmentManager)
            warnings = (
                "Failed to clone volume database: copy failed",
                "Failed to tag image for web: image missing",
                "Failed to copy extra: permission denied",
                "Command failed: setup: setup failed",
            )
            environment.provision = AsyncMock(return_value=warnings)
            log_store = Mock()
            progress: list[str] = []

            result = asyncio.run(
                WorktreeCreator(manager, environment, log_store).create(
                    "feature",
                    "beta",
                    clone_data=True,
                    on_progress=progress.append,
                )
            )

        self.assertIs(result.worktree, worktree)
        environment.configure.assert_called_once_with(worktree, [worktree])
        self.assertEqual(result.warnings, warnings)
        environment.provision.assert_awaited_once_with(
            worktree,
            clone_data=True,
            on_progress=progress.append,
        )
        self.assertEqual(progress[0], "Creating git worktree...")
        self.assertEqual(
            [call.args[1] for call in log_store.record_elapsed.call_args_list],
            ["Created worktree"],
        )

    def test_create_without_cloning_still_runs_post_create_commands(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"), "feature")
        manager = Mock()
        manager.create_worktree = AsyncMock(return_value=worktree)
        manager.discover_worktrees = AsyncMock(return_value=[worktree])
        environment = Mock(spec=EnvironmentManager)
        environment.provision = AsyncMock(return_value=())
        log_store = Mock()

        result = asyncio.run(
            WorktreeCreator(manager, environment, log_store).create(
                "feature",
                None,
                clone_data=False,
            )
        )

        self.assertEqual(result.warnings, ())
        environment.configure.assert_called_once_with(worktree, [worktree])
        environment.provision.assert_awaited_once_with(
            worktree,
            clone_data=False,
            on_progress=None,
        )

    def test_clone_volume_reports_creation_and_copy_failures(self) -> None:
        manager = DockerManager(Path("/tmp/main"), "source")
        with patch.object(
            manager,
            "_run_sync",
            side_effect=((1, "", "create failed"),),
        ) as run_command:
            self.assertEqual(
                manager.clone_volume_sync("target", "database"),
                (False, "create failed"),
            )
            self.assertEqual(run_command.call_count, 1)

        with patch.object(
            manager,
            "_run_sync",
            side_effect=((0, "", ""), (1, "", "copy failed")),
        ) as run_command:
            self.assertEqual(
                manager.clone_volume_sync("target", "database"),
                (False, "copy failed"),
            )
            self.assertEqual(run_command.call_count, 2)
