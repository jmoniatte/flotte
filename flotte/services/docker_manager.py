import asyncio
import json
from pathlib import Path


class DockerManager:
    """Direct Docker Compose interaction for status and service control."""

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
            return (-1, "", "Command timed out")

    async def get_container_data(self) -> tuple[list[dict], list[str]]:
        """Get raw container data and all service names.

        Returns:
            Tuple of:
            - List of dicts from docker compose ps (container data)
            - List of all service names from docker compose config
        """
        container_data: list[dict] = []
        all_services: list[str] = []

        # Get existing containers (running or stopped)
        returncode, stdout, stderr = await self._run_compose(
            "ps", "-a", "--format", "json"
        )

        if returncode == 0 and stdout.strip():
            # docker compose ps --format json outputs ONE JSON OBJECT PER LINE
            for line in stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    container_data.append(data)
                except json.JSONDecodeError:
                    continue

        # Get all defined services
        returncode, stdout, stderr = await self._run_compose(
            "config", "--services"
        )

        if returncode == 0 and stdout.strip():
            for service_name in stdout.strip().split("\n"):
                service_name = service_name.strip()
                if service_name:
                    all_services.append(service_name)

        return container_data, all_services

    async def start_service(self, service: str) -> bool:
        """
        Start a specific service.

        Returns:
            True if successful, False otherwise
        """
        returncode, _, _ = await self._run_compose("up", "-d", service)
        return returncode == 0

    async def stop_service(self, service: str) -> bool:
        """
        Stop a specific service.

        Returns:
            True if successful, False otherwise
        """
        returncode, _, _ = await self._run_compose("stop", service)
        return returncode == 0

    async def restart_service(self, service: str) -> bool:
        """
        Restart a specific service.

        Returns:
            True if successful, False otherwise
        """
        returncode, _, _ = await self._run_compose("restart", service)
        return returncode == 0
