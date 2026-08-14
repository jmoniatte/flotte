import yaml
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "flotte"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


@dataclass(frozen=True)
class Project:
    """A configured project with its settings."""
    name: str
    path: str
    worktree_path: str  # Directory where new worktrees are created
    worktree_prefix: str  # Prefix for worktree dirs (use "" for no prefix)
    post_create_commands: tuple[str, ...] = ()  # Setup commands run once in each new worktree
    ride_command: str = ""
    # Env file flotte reads and writes per worktree, relative to the worktree root.
    # Only ".env" is auto-loaded by docker compose; other values need --env-file.
    env_file: str = ".env"
    clone_paths: tuple[str, ...] = ()


@dataclass
class Config:
    """Application configuration with sensible defaults."""

    # UI settings
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
        with open(CONFIG_FILE, "r") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            return config

        # Load global settings
        if "theme" in data and isinstance(data["theme"], str):
            config.theme = data["theme"]

        # Load projects array
        required_fields = ("name", "path", "worktree_path", "worktree_prefix")
        if "projects" in data and isinstance(data["projects"], list):
            for proj_data in data["projects"]:
                if not isinstance(proj_data, dict):
                    logger.warning(f"Skipping invalid project entry: {proj_data}")
                    continue
                missing = [f for f in required_fields if f not in proj_data]
                if missing:
                    logger.warning(f"Skipping project missing required fields {missing}: {proj_data}")
                    continue
                raw_clone_paths = proj_data.get("clone_paths", [])
                clone_paths_list: list[str] = []
                if isinstance(raw_clone_paths, list):
                    clone_paths_list = [str(p) for p in raw_clone_paths]

                raw_post_create_commands = proj_data.get("post_create_commands", [])
                if isinstance(raw_post_create_commands, str):
                    raw_post_create_commands = [raw_post_create_commands]
                post_create_commands_list: list[str] = []
                if isinstance(raw_post_create_commands, list):
                    post_create_commands_list = [str(c) for c in raw_post_create_commands if str(c).strip()]

                config.projects.append(Project(
                    name=str(proj_data["name"]),
                    path=str(proj_data["path"]),
                    worktree_path=str(proj_data["worktree_path"]),
                    worktree_prefix=str(proj_data["worktree_prefix"]),
                    post_create_commands=tuple(post_create_commands_list),
                    ride_command=str(proj_data.get("ride_command", "")),
                    env_file=str(proj_data.get("env_file") or ".env"),
                    clone_paths=tuple(clone_paths_list),  # flat list of relative paths
                ))

    except yaml.YAMLError as e:
        logger.warning(f"Invalid config file: {e}")
    except Exception as e:
        logger.warning(f"Error loading config: {e}")

    return config


def save_config(config: Config) -> None:
    """Save configuration to file in YAML format."""
    ensure_config_dir()

    data: dict = {"theme": config.theme}

    if config.projects:
        projects_list = []
        for project in config.projects:
            proj_dict: dict = {
                "name": project.name,
                "path": project.path,
                "worktree_path": project.worktree_path,
                "worktree_prefix": project.worktree_prefix,
                "ride_command": project.ride_command,
                "env_file": project.env_file,
            }
            if project.post_create_commands:
                proj_dict["post_create_commands"] = list(project.post_create_commands)
            if project.clone_paths:
                proj_dict["clone_paths"] = list(project.clone_paths)
            projects_list.append(proj_dict)
        data["projects"] = projects_list

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
