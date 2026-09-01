import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

from flotte.models import Worktree
from flotte.services.environment_provisioner import EnvironmentProvisioner


class EnvironmentProvisionerTests(unittest.TestCase):
    def test_provision_reports_failures_and_skips_duplicate_paths(self) -> None:
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
                compose_project_name="project-feature",
            )
            log_store = Mock()
            provisioner = EnvironmentProvisioner(
                main_path,
                "project",
                ("bind", "extra", "extra"),
                ("setup",),
                log_store,
            )
            provisioner.docker.get_volumes = AsyncMock(return_value=["database"])
            provisioner.docker.clone_volume_sync = Mock(
                return_value=(False, "copy failed")
            )
            provisioner.docker.get_built_services_sync = Mock(return_value=["web"])
            provisioner.docker.tag_images_sync = Mock(
                return_value=[("web", "image missing")]
            )
            provisioner.docker.get_bind_mounts_sync = Mock(return_value=["bind"])
            provisioner.docker.clone_path_sync = Mock(
                side_effect=((True, ""), (False, "permission denied"))
            )
            progress: list[str] = []

            with (
                patch.object(
                    provisioner.git,
                    "run",
                    return_value=(0, "bind\n", ""),
                ),
                patch.object(
                    provisioner,
                    "_run_post_create_command_sync",
                    return_value=(False, "setup failed"),
                ),
            ):
                warnings = asyncio.run(
                    provisioner.provision(
                        worktree,
                        clone_data=True,
                        on_progress=progress.append,
                    )
                )

        self.assertEqual(
            warnings,
            (
                "Failed to clone volume database: copy failed",
                "Failed to tag image for web: image missing",
                "Failed to copy extra: permission denied",
                "Command failed: setup: setup failed",
            ),
        )
        self.assertEqual(
            provisioner.docker.clone_path_sync.call_args_list,
            [
                call(main_path / "bind", worktree_path / "bind"),
                call(main_path / "extra", worktree_path / "extra"),
            ],
        )
        self.assertEqual(progress[0], "Cloning volume 1/1: database...")
        self.assertEqual(progress[-1], "Running command 1/1: setup...")
        self.assertEqual(
            [item.args[1] for item in log_store.record_elapsed.call_args_list],
            [
                "Cloned volume database",
                "Tagged images",
                "Copied bind mount bind",
                "Copied extra path extra",
                "Ran post-create command: setup",
            ],
        )

    def test_without_clone_data_only_runs_post_create_commands(self) -> None:
        worktree = Worktree("feature", Path("/tmp/feature"))
        provisioner = EnvironmentProvisioner(
            Path("/tmp/main"),
            "project",
            (),
            ("setup",),
            None,
        )
        provisioner._run_post_create_command_sync = Mock(return_value=(True, ""))

        warnings = asyncio.run(
            provisioner.provision(worktree, clone_data=False)
        )

        self.assertEqual(warnings, ())
        provisioner._run_post_create_command_sync.assert_called_once_with(
            "setup",
            worktree,
        )
