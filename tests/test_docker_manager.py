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


class _LogOutput:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = iter(lines)

    async def readline(self) -> bytes:
        return next(self.lines, b"")


class _LogProcess:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = _LogOutput(lines)
        self.returncode = None
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


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

    async def test_stream_logs_includes_recent_output_and_follows(self) -> None:
        process = _LogProcess([b"existing\n", b"new\n"])
        manager = DockerManager(Path("/tmp/project"), "acme-feature")

        with patch("asyncio.create_subprocess_exec", return_value=process) as spawn:
            lines = [
                line
                async for line in manager.stream_logs(services=("rails", "mariadb"))
            ]

        self.assertEqual(lines, [b"existing", b"new"])
        spawn.assert_called_once_with(
            "docker",
            "compose",
            "-f",
            "/tmp/project/docker-compose.yml",
            "-p",
            "acme-feature",
            "logs",
            "--follow",
            "--tail",
            "200",
            "rails",
            "mariadb",
            cwd=Path("/tmp/project"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self.assertTrue(process.terminated)
