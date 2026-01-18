import tomllib
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "flotte"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass(frozen=True)
class Project:
    """A configured project with its settings."""
    name: str
    path: str
    ride_command: str = ""


@dataclass
class Config:
    """Application configuration with sensible defaults."""

    # Polling settings
    poll_interval: int = 5  # Seconds between status polls

    # UI settings
    auto_discover: bool = True  # Discover worktrees on startup
    theme: str = "onedark"  # "onedark" or "onelight" (or any .tcss in styles/themes/)

    # Projects list
    projects: list[Project] = field(default_factory=list)


def ensure_config_dir() -> None:
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """Load configuration from file, falling back to defaults."""
    config = Config()

    if not CONFIG_FILE.exists():
        ensure_config_dir()
        save_config(config)
        return config

    try:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)

        # Load global settings
        if "poll_interval" in data and isinstance(data["poll_interval"], int):
            config.poll_interval = data["poll_interval"]
        if "auto_discover" in data and isinstance(data["auto_discover"], bool):
            config.auto_discover = data["auto_discover"]
        if "theme" in data and isinstance(data["theme"], str):
            config.theme = data["theme"]

        # Load projects array
        if "projects" in data and isinstance(data["projects"], list):
            for proj_data in data["projects"]:
                if isinstance(proj_data, dict) and "name" in proj_data and "path" in proj_data:
                    config.projects.append(Project(
                        name=str(proj_data["name"]),
                        path=str(proj_data["path"]),
                        ride_command=str(proj_data.get("ride_command", "")),
                    ))
                else:
                    logger.warning(f"Skipping invalid project entry: {proj_data}")

    except tomllib.TOMLDecodeError as e:
        logger.warning(f"Invalid config file: {e}")
    except Exception as e:
        logger.warning(f"Error loading config: {e}")

    return config


def save_config(config: Config) -> None:
    """Save configuration to file in TOML format."""
    ensure_config_dir()

    lines = [
        "# Flotte Configuration",
        "",
        "# Polling interval in seconds",
        f"poll_interval = {config.poll_interval}",
        "",
        "# Discover worktrees on startup",
        f"auto_discover = {'true' if config.auto_discover else 'false'}",
        "",
        "# Color theme: onedark, onelight (or any .tcss file in styles/themes/)",
        f'theme = "{config.theme}"',
        "",
    ]

    for project in config.projects:
        lines.extend([
            "[[projects]]",
            f'name = "{project.name}"',
            f'path = "{project.path}"',
            f'ride_command = "{project.ride_command}"',
            "",
        ])

    with open(CONFIG_FILE, "w") as f:
        f.write("\n".join(lines))
