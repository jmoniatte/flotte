import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

from flotte.models import Worktree
from flotte.services.worktree_creator import WorktreeCreator
from flotte.services.worktree_manager import WorktreeManager


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
            manager.get_compose_project_prefix.return_value = "project"
            manager.get_volumes = AsyncMock(return_value=["database"])
            manager.clone_volume_sync.return_value = (False, "copy failed")
            manager.get_built_services_sync.return_value = ["web"]
            manager.tag_images_sync.return_value = [("web", "image missing")]
            manager.get_gitignored_bind_mounts = AsyncMock(return_value=["bind"])
            manager.get_all_clone_paths.return_value = ["bind", "extra", "extra"]
            manager.clone_path_sync.side_effect = ((True, ""), (False, "permission denied"))
            manager.run_post_create_command_sync.return_value = (False, "setup failed")
            log_store = Mock()
            progress: list[str] = []

            result = asyncio.run(
                WorktreeCreator(manager, log_store).create(
                    "feature",
                    "beta",
                    clone_data=True,
                    on_progress=progress.append,
                )
            )

        self.assertIs(result.worktree, worktree)
        self.assertEqual(
            result.warnings,
            (
                "Failed to clone volume database: copy failed",
                "Failed to tag image for web: image missing",
                "Failed to copy extra: permission denied",
                "Command failed: setup: setup failed",
            ),
        )
        self.assertEqual(
            manager.clone_path_sync.call_args_list,
            [
                call(main_path / "bind", worktree_path / "bind"),
                call(main_path / "extra", worktree_path / "extra"),
            ],
        )
        self.assertEqual(progress[0], "Creating git worktree...")
        self.assertEqual(progress[-1], "Running command 1/1: setup...")
        self.assertEqual(
            [call.args[1] for call in log_store.record_elapsed.call_args_list],
            [
                "Created worktree",
                "Cloned volume database",
                "Tagged images",
                "Copied bind mount bind",
                "Copied extra path extra",
                "Ran post-create command: setup",
            ],
        )

    def test_create_without_cloning_still_runs_post_create_commands(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"), "feature")
        manager = Mock()
        manager.post_create_commands = ("setup",)
        manager.create_worktree = AsyncMock(return_value=worktree)
        manager.run_post_create_command_sync.return_value = (True, "")
        log_store = Mock()

        result = asyncio.run(
            WorktreeCreator(manager, log_store).create(
                "feature",
                None,
                clone_data=False,
            )
        )

        self.assertEqual(result.warnings, ())
        manager.get_volumes.assert_not_called()
        manager.run_post_create_command_sync.assert_called_once_with("setup", worktree)

    def test_clone_volume_reports_creation_and_copy_failures(self) -> None:
        manager = WorktreeManager(Path("/tmp/main"), "/tmp/{worktree}")
        with patch.object(
            manager,
            "_run_command",
            side_effect=((1, "", "create failed"),),
        ) as run_command:
            self.assertEqual(
                manager.clone_volume_sync("source", "target", "database"),
                (False, "create failed"),
            )
            self.assertEqual(run_command.call_count, 1)

        with patch.object(
            manager,
            "_run_command",
            side_effect=((0, "", ""), (1, "", "copy failed")),
        ) as run_command:
            self.assertEqual(
                manager.clone_volume_sync("source", "target", "database"),
                (False, "copy failed"),
            )
            self.assertEqual(run_command.call_count, 2)

    def test_port_allocation_uses_fresh_worktree_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main_path = root / "main"
            existing_path = root / "feature"
            main_path.mkdir()
            existing_path.mkdir()
            (main_path / ".env").write_text("APP_PORT=3000\n")
            (existing_path / ".env").write_text("APP_PORT=3100\n")
            manager = WorktreeManager(main_path, str(root / "{worktree}"))
            with patch.object(
                manager,
                "discover_worktrees_sync",
                return_value=(
                    Worktree("main", main_path, is_main=True),
                    Worktree("feature", existing_path),
                ),
            ) as discover:
                self.assertEqual(manager.find_next_port_offset(), 200)
                discover.assert_called_once_with()
