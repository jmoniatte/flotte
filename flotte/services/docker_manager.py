import asyncio
import json
from pathlib import Path

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
