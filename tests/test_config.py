import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from flotte.config import Config, LinkedRepository, PortRange, Project, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_save_preserves_linked_repository_pre_start_commands(self) -> None:
        repository = LinkedRepository(
            repository_path="/projects/frontend",
            worktree_path="/projects/frontend-{worktree}",
            ports=(PortRange("vite", 5100, 5199),),
            pre_start_commands=("./configure-link",),
        )
        config = Config(projects=[Project("Backend", "/projects/backend", "/projects/backend-{worktree}", linked_repositories=(repository,))])

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
        self.assertNotIn("name", saved["projects"][0]["linked_repositories"][0])
