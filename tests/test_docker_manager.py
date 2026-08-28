import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flotte.services.docker_manager import DockerManager


class _TimedOutProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if not self.killed:
            await asyncio.Future()
        self.returncode = -9
        return b"", b""

    def kill(self) -> None:
        self.killed = True


class DockerManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_lifecycle_commands_share_the_compose_runner(self) -> None:
        manager = DockerManager(Path("/tmp/project"), "acme-feature")
        manager._run_compose = AsyncMock(return_value=(0, "", ""))

        await manager.start()
        await manager.stop()

        self.assertEqual(
            manager._run_compose.await_args_list,
            [
                unittest.mock.call("up", "-d", timeout=300.0),
                unittest.mock.call("down", timeout=300.0),
            ],
        )

    async def test_compose_timeout_kills_and_reaps_the_process(self) -> None:
        process = _TimedOutProcess()
        manager = DockerManager(Path("/tmp/project"), "acme-feature")

        with patch("asyncio.create_subprocess_exec", return_value=process):
            result = await manager._run_compose("up", "-d", timeout=0)

        self.assertEqual(result, (-1, "", "Command timed out"))
        self.assertTrue(process.killed)
        self.assertEqual(process.returncode, -9)
