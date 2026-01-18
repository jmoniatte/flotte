from enum import Enum


class ContainerState(Enum):
    """Container states as reported by docker compose ps."""

    RUNNING = "running"
    EXITED = "exited"
    PAUSED = "paused"
    RESTARTING = "restarting"
    DEAD = "dead"
    CREATED = "created"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "ContainerState":
        """Parse docker state string to enum, defaulting to UNKNOWN."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.UNKNOWN


class Container:
    """Docker container state.

    Persisted across polls, updated in place via update_from_docker().
    """

    def __init__(self, service: str):
        """Create container for a service.

        Args:
            service: Service name from docker-compose.yml
        """
        self.service = service
        self.id: str = ""
        self.name: str = ""
        self.image: str = ""
        self.state: ContainerState = ContainerState.UNKNOWN
        self.status: str = ""  # Human-readable (e.g., "Up 11 hours")
        self.ports: list[str] = []

    def update_from_docker(self, data: dict) -> None:
        """Update state from docker compose ps JSON output.

        Args:
            data: Dict from docker compose ps --format json
        """
        self.id = data.get("ID", "")[:12] if data.get("ID") else ""
        self.name = data.get("Name", "")
        self.image = data.get("Image", "")
        self.state = ContainerState.from_string(data.get("State", "unknown"))
        self.status = data.get("Status", "")
        self.ports = self._parse_ports(data.get("Ports", ""))

    def mark_exited(self) -> None:
        """Mark container as exited (for services without containers)."""
        self.id = ""
        self.name = "-"
        self.image = ""
        self.state = ContainerState.EXITED
        self.status = "-"
        self.ports = []

    @staticmethod
    def _parse_ports(ports_str: str) -> list[str]:
        """Parse port mappings and extract exposed host ports.

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

    @property
    def is_healthy(self) -> bool:
        """Container is considered healthy if running."""
        return self.state == ContainerState.RUNNING
