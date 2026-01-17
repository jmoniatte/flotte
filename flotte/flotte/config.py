import tomllib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "flotte"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class Config:
    """Application configuration with sensible defaults."""

    # Polling settings
    poll_interval: int = 5  # Seconds between status polls

    # Paths - main_repo_path is the only required path
    # parent_dir and project_name are derived from it
    main_repo_path: str = ""  # Must be set in config or via CLI

    # UI settings
    auto_discover: bool = True  # Discover worktrees on startup

    # External command for "Go Ride" button (receives PROJECT_PATH and PROJECT_NAME env vars)
    ride_command: str = ""


def ensure_config_dir() -> None:
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """
    Load configuration from file, falling back to defaults.

    Returns:
        Config object with merged settings
    """
    config = Config()  # Start with defaults

    if not CONFIG_FILE.exists():
        # Create default config file on first run
        ensure_config_dir()
        save_config(config)
        return config

    try:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)

        # Merge loaded values with defaults
        config = _merge_config(config, data)

    except tomllib.TOMLDecodeError as e:
        logger.warning(f"Invalid config file, using defaults: {e}")
    except Exception as e:
        logger.warning(f"Error loading config, using defaults: {e}")

    return config


def _merge_config(config: Config, data: dict[str, Any]) -> Config:
    """Merge loaded data into config, validating types."""
    unknown_keys = []
    for key, value in data.items():
        if hasattr(config, key):
            expected_type = type(getattr(config, key))

            # Handle list specially
            if expected_type == list and isinstance(value, list):
                setattr(config, key, value)
            # Validate type matches
            elif isinstance(value, expected_type):
                setattr(config, key, value)
            else:
                logger.warning(
                    f"Config key '{key}' has wrong type, using default"
                )
        else:
            unknown_keys.append(key)

    # Clean up stale keys by re-saving config
    if unknown_keys:
        logger.debug(f"Removing stale config keys: {unknown_keys}")
        save_config(config)

    return config


def save_config(config: Config) -> None:
    """
    Save configuration to file in TOML format.

    Uses simple string formatting since tomli_w is not stdlib.
    """
    ensure_config_dir()

    lines = [
        "# Flotte Configuration",
        "",
        "# Polling interval in seconds",
        f"poll_interval = {config.poll_interval}",
        "",
        "# Path to main repo (worktrees are created as siblings)",
        f'main_repo_path = "{config.main_repo_path}"',
        "",
        "# Discover worktrees on startup",
        f"auto_discover = {'true' if config.auto_discover else 'false'}",
        "",
        "# External command for 'Go Ride' button (receives PROJECT_PATH and PROJECT_NAME env vars)",
        f'ride_command = "{config.ride_command}"',
        "",
    ]

    with open(CONFIG_FILE, "w") as f:
        f.write("\n".join(lines))
