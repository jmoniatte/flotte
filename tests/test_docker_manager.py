import asyncio
import json
import tempfile
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
    def test_compose_config_drives_volumes_images_and_bind_mounts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "volumes": {"database": {}},
                "services": {
                    "web": {
                        "build": ".",
                        "volumes": [
                            {
                                "type": "bind",
                                "source": str(root / "files"),
                                "target": "/app/files",
                            },
                            {
                                "type": "bind",
                                "source": "/outside",
                                "target": "/outside",
                            },
                        ],
                    }
                },
            }
            manager = DockerManager(root, "acme")
            with patch.object(
                manager,
                "_run_sync",
                return_value=(0, json.dumps(config), ""),
            ) as run:
                self.assertEqual(manager.get_volumes_sync(), ["database"])
                self.assertEqual(manager.get_built_services_sync(), ["web"])
                self.assertEqual(manager.get_bind_mounts_sync(), ["files"])

            self.assertEqual(run.call_count, 3)

    def test_only_volume_metadata_is_cached(self) -> None:
        manager = DockerManager(Path("/tmp/project"), "acme")
        first = {
            "volumes": {"database": {}},
            "services": {"web": {"build": "."}},
        }
        second = {
            "volumes": {"replacement": {}},
            "services": {"worker": {"build": "."}},
        }
        with patch.object(
            manager,
            "_run_sync",
            side_effect=(
                (0, json.dumps(first), ""),
                (0, json.dumps(second), ""),
            ),
        ) as run:
            self.assertEqual(manager.get_volumes_sync(), ["database"])
            self.assertEqual(manager.get_built_services_sync(), ["worker"])
            self.assertEqual(manager.get_volumes_sync(), ["database"])

        self.assertEqual(run.call_count, 2)

    def test_failed_volume_config_is_retried(self) -> None:
        manager = DockerManager(Path("/tmp/project"), "acme")
        with patch.object(
            manager,
            "_run_sync",
            side_effect=(
                (1, "", "Docker unavailable"),
                (0, '{"volumes":{"database":{}}}', ""),
            ),
        ) as run:
            self.assertEqual(manager.get_volumes_sync(), [])
            self.assertEqual(manager.get_volumes_sync(), ["database"])

        self.assertEqual(run.call_count, 2)

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
