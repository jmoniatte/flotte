from dataclasses import dataclass
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


@dataclass
class Container:
    """Represents a Docker container from docker compose ps."""

    id: str  # Short container ID (12 chars)
    name: str  # Full container name
    service: str  # Service name from docker-compose.yml
    image: str  # Image name
    state: ContainerState  # Current container state
    status: str  # Human-readable status (e.g., "Up 11 hours")
    ports: list[str]  # List of port mappings (e.g., ["3000->3000/tcp"])

    @property
    def is_healthy(self) -> bool:
        """Container is considered healthy if running."""
        return self.state == ContainerState.RUNNING
