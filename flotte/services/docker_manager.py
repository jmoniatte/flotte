import asyncio
from collections.abc import AsyncIterator
import json
import os
from pathlib import Path

from ._process import run_command

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


def _parse_labels(labels_str: str) -> dict[str, str]:
    labels = {}
    for part in labels_str.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            labels[key] = value
    return labels


async def get_all_containers_by_project() -> dict[str, list[dict]]:
    """List every compose container on the host with a single docker ps call.

    Returns:
        Dict mapping compose project name to container dicts shaped like
        docker compose ps output (Service, ID, Name, Image, State, Status, Ports).
    """
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "-a",
        "--filter",
        f"label={COMPOSE_PROJECT_LABEL}",
        "--format",
        "{{json .}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {}

    if proc.returncode != 0:
        return {}

    by_project: dict[str, list[dict]] = {}
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        labels = _parse_labels(data.get("Labels", ""))
        project = labels.get(COMPOSE_PROJECT_LABEL)
        service = labels.get(COMPOSE_SERVICE_LABEL)
        if not project or not service:
            continue
        by_project.setdefault(project, []).append(
            {
                "Service": service,
                "ID": data.get("ID", ""),
                "Name": data.get("Names", ""),
                "Image": data.get("Image", ""),
                "State": data.get("State", ""),
                "Status": data.get("Status", ""),
                "Ports": data.get("Ports", ""),
            }
        )
    return by_project


class DockerManager:
    """Run Docker Compose commands for one worktree."""

    def __init__(self, worktree_path: Path, project_name: str):
        """
        Initialize manager for a specific worktree.

        Args:
            worktree_path: Path to worktree containing docker-compose.yml
            project_name: Docker Compose project name (from COMPOSE_PROJECT_NAME)
        """
        self.worktree_path = worktree_path
        self.project_name = project_name
        self.compose_file = worktree_path / "docker-compose.yml"
        self._cached_volumes: list[str] | None = None

    def _run_sync(
        self,
        *args: str,
        timeout: float = 60.0,
    ) -> tuple[int, str, str]:
        return run_command(
            args,
            cwd=self.worktree_path,
            timeout=timeout,
        )

    def _read_config_sync(self) -> dict | None:
        returncode, stdout, _ = self._run_sync(
            "docker",
            "compose",
            "config",
            "--format",
            "json",
            timeout=30.0,
        )
        if returncode != 0:
            return None
        try:
            config = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        return config if isinstance(config, dict) else None

    def get_config_sync(self) -> dict:
        return self._read_config_sync() or {}

    def get_volumes_sync(self) -> list[str]:
        if self._cached_volumes is None:
            config = self._read_config_sync()
            if config is None:
                return []
            self._cached_volumes = list(config.get("volumes", {}).keys())
        return self._cached_volumes

    async def get_volumes(self) -> list[str]:
        return await asyncio.to_thread(self.get_volumes_sync)

    def get_built_services_sync(self) -> list[str]:
        return [
            name
            for name, service in self.get_config_sync().get("services", {}).items()
            if "build" in service
        ]

    def get_bind_mounts_sync(self) -> list[str]:
        bind_mounts: set[str] = set()
        for service in self.get_config_sync().get("services", {}).values():
            for volume in service.get("volumes", []):
                if not isinstance(volume, dict) or volume.get("type") != "bind":
                    continue
                try:
                    relative = Path(volume.get("source", "")).relative_to(
                        self.worktree_path
                    )
                except ValueError:
                    continue
                if str(relative) != ".":
                    bind_mounts.add(str(relative))
        return sorted(bind_mounts)

    def tag_images_sync(
        self,
        target_project: str,
        services: list[str],
    ) -> list[tuple[str, str]]:
        failures = []
        for service in services:
            source_image = f"{self.project_name}-{service}:latest"
            target_image = f"{target_project}-{service}:latest"
            returncode, _, stderr = self._run_sync(
                "docker", "tag", source_image, target_image
            )
            if returncode != 0:
                failures.append((service, stderr.strip()))
        return failures

    def clone_path_sync(self, source: Path, target: Path) -> tuple[bool, str]:
        target.parent.mkdir(parents=True, exist_ok=True)
        uid = os.getuid()
        gid = os.getgid()
        if source.is_dir():
            target.mkdir(exist_ok=True)
            args = (
                "docker", "run", "--rm",
                "-v", f"{source}:/source:ro",
                "-v", f"{target}:/dest",
                "alpine", "sh", "-c",
                f"cp -a /source/. /dest/ && chown -R {uid}:{gid} /dest/",
            )
            timeout = 300.0
        else:
            args = (
                "docker", "run", "--rm",
                "-v", f"{source}:/source/file:ro",
                "-v", f"{target.parent}:/dest",
                "alpine", "sh", "-c",
                f"cp -a /source/file /dest/{target.name} && chown {uid}:{gid} /dest/{target.name}",
            )
            timeout = 60.0
        returncode, _, stderr = self._run_sync(*args, timeout=timeout)
        if returncode != 0:
            return False, stderr.strip() or f"Docker copy failed with code {returncode}"
        return True, ""

    def clone_volume_sync(
        self,
        target_project: str,
        volume_name: str,
    ) -> tuple[bool, str]:
        source_volume = f"{self.project_name}_{volume_name}"
        target_volume = f"{target_project}_{volume_name}"
        returncode, _, stderr = self._run_sync(
            "docker", "volume", "create", target_volume
        )
        if returncode != 0:
            return False, stderr.strip() or "Docker volume creation failed"
        returncode, _, stderr = self._run_sync(
            "docker", "run", "--rm",
            "-v", f"{source_volume}:/source:ro",
            "-v", f"{target_volume}:/dest",
            "alpine", "sh", "-c", "cp -a /source/. /dest/",
            timeout=300.0,
        )
        if returncode != 0:
            return False, stderr.strip() or f"Docker copy failed with code {returncode}"
        return True, ""

    def cleanup_sync(self) -> None:
        if not self.compose_file.exists():
            return
        returncode, _, stderr = self._run_sync(
            *self._compose_args(),
            "down",
            "--volumes",
            "--remove-orphans",
            timeout=120.0,
        )
        if returncode != 0:
            raise RuntimeError(f"docker compose down failed: {stderr}")
        for volume_name in self.get_volumes_sync():
            self._run_sync(
                "docker", "volume", "rm", "-f", f"{self.project_name}_{volume_name}"
            )
        for service in self.get_built_services_sync():
            self._run_sync("docker", "rmi", f"{self.project_name}-{service}")

    def make_worktree_removable_sync(self) -> None:
        if not self.worktree_path.exists():
            return
        returncode, _, stderr = self._run_sync(
            "docker",
            "run",
            "--rm",
            "-v",
            f"{self.worktree_path}:/worktree",
            "alpine",
            "chown",
            "-R",
            f"{os.getuid()}:{os.getgid()}",
            "/worktree",
        )
        if returncode != 0:
            raise RuntimeError(f"Could not make worktree removable: {stderr}")

    def _compose_args(self) -> list[str]:
        """Base arguments for all docker compose commands."""
        return [
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "-p",
            self.project_name,
        ]

    async def _run_compose(
        self, *args: str, timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Execute a docker compose command."""
        cmd = self._compose_args() + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return (-1, "", "Command timed out")

    async def start(self) -> tuple[int, str, str]:
        """Start the worktree's containers."""
        return await self._run_compose("up", "-d", timeout=300.0)

    async def stop(self) -> tuple[int, str, str]:
        """Stop the worktree's containers."""
        return await self._run_compose("down", timeout=300.0)

    async def get_services(self) -> list[str]:
        """Get all service names defined in the compose file."""
        returncode, stdout, _ = await self._run_compose("config", "--services")
        if returncode != 0:
            return []
        return [line.strip() for line in stdout.strip().split("\n") if line.strip()]

    async def stream_logs(
        self, tail: int = 200, services: tuple[str, ...] = ()
    ) -> AsyncIterator[bytes]:
        """Yield recent and live Docker Compose output until the consumer stops."""
        proc = await asyncio.create_subprocess_exec(
            *self._compose_args(),
            "logs",
            "--follow",
            "--tail",
            str(tail),
            *services,
            cwd=self.worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            assert proc.stdout is not None
            while line := await proc.stdout.readline():
                yield line.removesuffix(b"\n")
        finally:
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
