import asyncio
import json
from pathlib import Path

from ..models import Container, ContainerState


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

    async def get_containers(self) -> list[Container]:
        """
        Get status of all containers/services for this project.

        Returns:
            List of Container objects for all services (including non-running)
        """
        containers = []
        services_with_containers = set()

        # Get existing containers (running or stopped)
        returncode, stdout, stderr = await self._run_compose(
            "ps", "-a", "--format", "json"
        )

        if returncode == 0 and stdout.strip():
            # IMPORTANT: docker compose ps --format json outputs ONE JSON OBJECT
            # PER LINE, not a JSON array!
            for line in stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    service_name = data.get("Service", "")
                    services_with_containers.add(service_name)
                    container = Container(
                        id=data.get("ID", "")[:12],
                        name=data.get("Name", ""),
                        service=service_name,
                        image=data.get("Image", ""),
                        state=ContainerState.from_string(data.get("State", "")),
                        status=data.get("Status", ""),
                        ports=self._parse_ports(data.get("Ports", "")),
                    )
                    containers.append(container)
                except json.JSONDecodeError:
                    continue

        # Get all defined services and add placeholders for missing ones
        returncode, stdout, stderr = await self._run_compose(
            "config", "--services"
        )

        if returncode == 0 and stdout.strip():
            for service_name in stdout.strip().split("\n"):
                service_name = service_name.strip()
                if service_name and service_name not in services_with_containers:
                    # Add placeholder for service without container
                    container = Container(
                        id="",
                        name="-",
                        service=service_name,
                        image="",
                        state=ContainerState.EXITED,
                        status="-",
                        ports=[],
                    )
                    containers.append(container)

        # Sort by service name for consistent display
        containers.sort(key=lambda c: c.service)
        return containers

    def _parse_ports(self, ports_str: str) -> list[str]:
        """
        Parse port mappings and extract exposed host ports.

        Input examples:
          - "3000/tcp" → not exposed, returns []
          - "0.0.0.0:3406->3306/tcp" → exposed on 3406, returns ["3406"]
          - "0.0.0.0:3406->3306/tcp, [::]:3406->3306/tcp" → returns ["3406"]

        Returns:
            List of unique exposed host port numbers
        """
        if not ports_str:
            return []

        exposed_ports = set()
        for port_spec in ports_str.split(","):
            port_spec = port_spec.strip()
            # Look for host:port->container pattern
            # Examples: "0.0.0.0:3406->3306/tcp", "[::]:3406->3306/tcp"
            if "->" in port_spec:
                # Extract the host:port part before ->
                host_part = port_spec.split("->")[0]
                # Extract just the port number (after the last colon)
                if ":" in host_part:
                    host_port = host_part.rsplit(":", 1)[1]
                    exposed_ports.add(host_port)

        # Return sorted for consistent display
        return sorted(exposed_ports, key=lambda p: int(p) if p.isdigit() else 0)

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
