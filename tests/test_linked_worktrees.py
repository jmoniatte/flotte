import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flotte.config import LinkedRepository, PortRange
from flotte.models import Worktree
from flotte.services.linked_worktree_manager import LinkedWorktreeManager
from flotte.services.link_state_store import LinkStateStore


class LinkedWorktreeManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.frontend = self.root / "frontend"
        self._create_repository(self.frontend)
        self.primary_path = self.root / "rails-feature"
        self.primary_path.mkdir()
        self.primary = Worktree("feature-test", self.primary_path, "feature/test")
        self.repository = LinkedRepository(
            name="Frontend",
            path=str(self.frontend),
            worktree_path=str(self.root / "worktrees"),
            worktree_prefix="frontend-",
            ports=(PortRange("dev_server", 55100, 55109),),
            post_create_commands=("test -n \"$FLOTTE_PORT_DEV_SERVER\"",),
            pre_start_commands=("echo VITE_PORT=55100 > .env.local",),
            post_delete_commands=("test -d \"$FLOTTE_LINKED_PATH\"",),
            start_command="sleep 30",
            status_port_env="VITE_PORT",
            status_port_label="Vite",
        )
        self.manager = LinkedWorktreeManager((self.repository,))
        self.manager.link_state = LinkStateStore(self.root / "state.yaml")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_retry_and_remove_linked_worktree(self) -> None:
        created = self.manager._create_link_sync(self.primary, self.repository)

        self.assertEqual(created.state, "linked")
        self.assertTrue(created.path and created.path.exists())
        self.assertIn("dev_server", created.ports)
        self.assertEqual(created.process_status, "running")

        (created.path / ".env.local").write_text("VITE_PORT=55100\n")
        self.manager.attach(self.primary)
        self.assertEqual(self.primary.linked_worktrees[0].ports["Vite"], 55100)

        retried = self.manager._create_link_sync(self.primary, self.repository)
        self.assertEqual(retried.path, created.path)
        self.assertEqual(retried.ports["dev_server"], created.ports["dev_server"])
        self.assertEqual(retried.ports["Vite"], 55100)
        self.assertEqual(retried.process_status, "running")

        restarted = asyncio.run(self.manager.restart_link(self.primary, self.repository.name))
        self.assertEqual(restarted.process_status, "running")
        self.assertEqual(restarted.process_status, "running")

        stopped = asyncio.run(self.manager.stop_link(self.primary, self.repository.name))
        self.assertEqual(stopped.process_status, "stopped")
        self.assertEqual(stopped.process_status, "stopped")

        asyncio.run(self.manager.remove_links(self.primary))
        self.assertFalse(created.path.exists())
        self.assertEqual(
            self.manager.link_state.get_record(self.manager._key(self.primary, self.repository)),
            {},
        )

    def test_started_process_does_not_inherit_terminal_input(self) -> None:
        process = Mock(pid=12345)
        identity = {
            "pid": 12345,
            "process_group": 12345,
            "session": 12345,
            "started_at": 1,
        }
        with (
            patch("flotte.services.linked_worktree_manager.subprocess.Popen", return_value=process) as popen,
            patch("flotte.services.linked_worktree_manager.capture_process_identity", return_value=identity),
            patch.object(self.manager, "_run_commands"),
        ):
            self.manager._start_process(
                self.primary,
                self.repository,
                self.frontend,
                {},
                self.manager._key(self.primary, self.repository),
            )

        self.assertIs(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_main_checkout_process_is_managed_without_removing_the_repository(self) -> None:
        main = Worktree("main", self.frontend, "main", is_main=True)

        self.manager.attach(main)
        attached = main.linked_worktrees[0]
        self.assertEqual(attached.path, self.frontend)
        self.assertEqual(attached.process_status, "stopped")

        started = asyncio.run(self.manager.start_link(main, self.repository.name))
        self.assertEqual(started.process_status, "running")
        self.assertEqual(started.ports["Vite"], 55100)

        stopped = asyncio.run(self.manager.stop_link(main, self.repository.name))
        self.assertEqual(stopped.process_status, "stopped")

        asyncio.run(self.manager.remove_link(main, self.repository.name))
        self.assertTrue(self.frontend.exists())
        self.assertEqual(
            self.manager.link_state.get_record(self.manager._key(main, self.repository)),
            {},
        )

    @staticmethod
    def _create_repository(path: Path) -> None:
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
        (path / "README.md").write_text("test\n")
        subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-qm", "Initial"], check=True)
