import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from flotte.config import (
    Config,
    LinkedRepository,
    PortRange,
    Project,
    load_config,
    preflight_config,
    save_config,
)


class ConfigTests(unittest.TestCase):
    def test_preflight_keeps_only_usable_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir) / "repository"
            repository.mkdir()
            project = Project(
                name="valid",
                repository_path=str(repository),
                worktree_path=str(Path(temp_dir) / "worktrees" / "{worktree}"),
            )
            missing = Project(
                name="missing",
                repository_path=str(Path(temp_dir) / "missing"),
                worktree_path=str(Path(temp_dir) / "worktrees" / "{worktree}"),
            )
            success = Mock(returncode=0, stdout=f"{repository}\n")
            compose_success = Mock(returncode=0, stdout="Docker Compose version")
            with (
                patch("flotte.config.shutil.which", return_value="/usr/bin/docker"),
                patch("flotte.config.subprocess.run", side_effect=[compose_success, success]),
            ):
                result = preflight_config(Config(projects=[project, missing]))

        self.assertEqual(result.projects, (project, missing))
        self.assertEqual(result.problems_for(project), ())
        self.assertEqual(
            result.problems_for(missing),
            (f"missing: repository does not exist: {missing.repository_path}",),
        )

    def test_preflight_blocks_projects_when_docker_compose_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Project("test", temp_dir, "/tmp/worktrees/{worktree}")
            git_success = Mock(returncode=0, stdout=f"{temp_dir}\n")
            with (
                patch("flotte.config.shutil.which", return_value=None),
                patch("flotte.config.subprocess.run", return_value=git_success),
            ):
                result = preflight_config(Config(projects=[project]))

        self.assertEqual(result.projects, (project,))
        self.assertEqual(
            result.problems_for(project),
            ("Docker Compose is unavailable. Start Docker or install the Compose plugin.",),
        )

    def test_preflight_rejects_a_worktree_template_without_a_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Project("test", temp_dir, f"{temp_dir}/worktrees")
            git_success = Mock(returncode=0, stdout=f"{temp_dir}\n")
            compose_success = Mock(returncode=0, stdout="Docker Compose version")
            with (
                patch("flotte.config.shutil.which", return_value="/usr/bin/docker"),
                patch("flotte.config.subprocess.run", side_effect=[compose_success, git_success]),
            ):
                result = preflight_config(Config(projects=[project]))

        self.assertEqual(result.projects, (project,))
        self.assertEqual(
            result.problems_for(project),
            ("test: worktree_path must include {worktree}",),
        )

    def test_save_preserves_linked_repository_pre_start_commands(self) -> None:
        repository = LinkedRepository(
            repository_path="/projects/frontend",
            worktree_path="/projects/frontend-{worktree}",
            ports=(PortRange("vite", 5100, 5199),),
            pre_start_commands=("./configure-link",),
        )
        config = Config(
            projects=[
                Project(
                    "Backend",
                    "/projects/backend",
                    "/projects/backend-{worktree}",
                    container_log_services=("rails", "mariadb"),
                    linked_repositories=(repository,),
                )
            ]
        )

        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory)
            config_file = config_dir / "config.yaml"
            with (
                patch("flotte.config.CONFIG_DIR", config_dir),
                patch("flotte.config.CONFIG_FILE", config_file),
            ):
                save_config(config)
                loaded = load_config()
                saved = yaml.safe_load(config_file.read_text())

        self.assertEqual(
            loaded.projects[0].linked_repositories[0].pre_start_commands,
            ("./configure-link",),
        )
        self.assertEqual(loaded.projects[0].linked_repositories[0].name, "frontend")
        self.assertEqual(
            loaded.projects[0].container_log_services, ("rails", "mariadb")
        )
        self.assertEqual(
            saved["projects"][0]["container_log_services"], ["rails", "mariadb"]
        )
        self.assertNotIn("name", saved["projects"][0]["linked_repositories"][0])
