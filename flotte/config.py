import yaml
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "flotte"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


@dataclass(frozen=True)
class PortRange:
    """A named inclusive range from which linked worktrees receive a port."""
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class LinkedRepository:
    """A repository whose worktrees are paired with a primary project."""
    repository_path: str
    worktree_path: str
    ports: tuple[PortRange, ...] = ()
    post_create_commands: tuple[str, ...] = ()
    post_delete_commands: tuple[str, ...] = ()
    pre_start_commands: tuple[str, ...] = ()
    start_command: str = ""
    status_port_env: str = ""
    status_port_file: str = ".env.local"
    status_port_label: str = "Port"
    open_url_path: str = ""

    @property
    def name(self) -> str:
        return Path(self.repository_path).name


@dataclass(frozen=True)
class Project:
    """A configured project with its settings."""
    name: str
    repository_path: str
    worktree_path: str  # Destination template containing {worktree}
    post_create_commands: tuple[str, ...] = ()  # Setup commands run once in each new worktree
    ride_command: str = ""
    # Env file flotte reads and writes per worktree, relative to the worktree root.
    # Only ".env" is auto-loaded by docker compose; other values need --env-file.
    env_file: str = ".env"
    clone_paths: tuple[str, ...] = ()
    container_log_services: tuple[str, ...] = ()
    linked_repositories: tuple[LinkedRepository, ...] = ()


@dataclass
class Config:
    """Application configuration with sensible defaults."""

    # UI settings
    theme: str = "onedark"  # "onedark" or "onelight" (or any .tcss in styles/themes/)

    # Projects list
    projects: list[Project] = field(default_factory=list)


@dataclass(frozen=True)
class PreflightResult:
    """Configured projects and their startup validation problems."""

    projects: tuple[Project, ...]
    project_problems: tuple[tuple[Project, tuple[str, ...]], ...]

    def problems_for(self, project: Project) -> tuple[str, ...]:
        for configured_project, problems in self.project_problems:
            if configured_project == project:
                return problems
        return ()


def ensure_config_dir() -> None:
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _writable_parent(path: Path) -> Path | None:
    """Find the existing directory that would contain path."""
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate if candidate.is_dir() else None


def _project_problems(project: Project) -> list[str]:
    problems: list[str] = []
    repository_path = Path(project.repository_path).expanduser()
    if not repository_path.is_dir():
        return [f"{project.name}: repository does not exist: {repository_path}"]

    try:
        result = subprocess.run(
            ["git", "-C", str(repository_path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if (
        result is None
        or result.returncode != 0
        or Path(result.stdout.strip()).resolve() != repository_path.resolve()
    ):
        problems.append(f"{project.name}: repository is not a Git worktree: {repository_path}")

    if "{worktree}" not in project.worktree_path:
        problems.append(f"{project.name}: worktree_path must include {{worktree}}")
    else:
        template = Path(project.worktree_path).expanduser()
        destination_parent = _writable_parent(template.parent)
        if destination_parent is None:
            problems.append(f"{project.name}: worktree destination has no usable parent")
        elif not os.access(destination_parent, os.W_OK | os.X_OK):
            problems.append(
                f"{project.name}: worktree destination is not writable: {destination_parent}"
            )
    return problems


def preflight_config(config: Config) -> PreflightResult:
    """Validate local prerequisites before a project is selected."""
    docker_available = shutil.which("docker") is not None
    if docker_available:
        try:
            docker_check = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            docker_available = docker_check.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            docker_available = False
    docker_problem = "Docker Compose is unavailable. Start Docker or install the Compose plugin."
    project_problems: list[tuple[Project, tuple[str, ...]]] = []
    for project in config.projects:
        problems = _project_problems(project)
        if not docker_available:
            problems.insert(0, docker_problem)
        project_problems.append((project, tuple(problems)))

    return PreflightResult(tuple(config.projects), tuple(project_problems))


def _commands(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(str(command) for command in value if str(command).strip())


def _container_log_services(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return ()
    return tuple(str(service).strip() for service in value if str(service).strip())


def _linked_repositories(value: object) -> tuple[LinkedRepository, ...]:
    if not isinstance(value, list):
        return ()

    repositories: list[LinkedRepository] = []
    required = ("repository_path", "worktree_path")
    for item in value:
        if not isinstance(item, dict):
            logger.warning("Skipping invalid linked repository entry: %s", item)
            continue
        missing = [field for field in required if field not in item]
        if missing:
            logger.warning("Skipping linked repository missing fields %s: %s", missing, item)
            continue
        if "{worktree}" not in str(item["worktree_path"]):
            logger.warning("Skipping linked repository without {worktree} in worktree_path: %s", item)
            continue

        ports: list[PortRange] = []
        raw_ports = item.get("ports", {})
        if isinstance(raw_ports, dict):
            for name, port_range in raw_ports.items():
                if not isinstance(port_range, str) or "-" not in port_range:
                    logger.warning("Skipping invalid port range for %s: %s", name, port_range)
                    continue
                try:
                    start, end = (int(part.strip()) for part in port_range.split("-", 1))
                except ValueError:
                    logger.warning("Skipping invalid port range for %s: %s", name, port_range)
                    continue
                if not 1 <= start <= end <= 65535:
                    logger.warning("Skipping out-of-range ports for %s: %s", name, port_range)
                    continue
                ports.append(PortRange(str(name), start, end))

        repositories.append(LinkedRepository(
            repository_path=str(item["repository_path"]),
            worktree_path=str(item["worktree_path"]),
            ports=tuple(ports),
            post_create_commands=_commands(item.get("post_create_commands", [])),
            post_delete_commands=_commands(item.get("post_delete_commands", [])),
            pre_start_commands=_commands(item.get("pre_start_commands", [])),
            start_command=str(item.get("start_command", "")).strip(),
            status_port_env=str(item.get("status_port_env", "")),
            status_port_file=str(item.get("status_port_file", ".env.local")),
            status_port_label=str(item.get("status_port_label", "Port")),
            open_url_path=str(item.get("open_url_path", "")).strip(),
        ))
    return tuple(repositories)


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
        required_fields = ("name", "repository_path", "worktree_path")
        if "projects" in data and isinstance(data["projects"], list):
            for proj_data in data["projects"]:
                if not isinstance(proj_data, dict):
                    logger.warning(f"Skipping invalid project entry: {proj_data}")
                    continue
                missing = [f for f in required_fields if f not in proj_data]
                if missing:
                    logger.warning(f"Skipping project missing required fields {missing}: {proj_data}")
                    continue
                if "{worktree}" not in str(proj_data["worktree_path"]):
                    logger.warning("Skipping project without {worktree} in worktree_path: %s", proj_data)
                    continue
                raw_clone_paths = proj_data.get("clone_paths", [])
                clone_paths_list: list[str] = []
                if isinstance(raw_clone_paths, list):
                    clone_paths_list = [str(p) for p in raw_clone_paths]

                config.projects.append(Project(
                    name=str(proj_data["name"]),
                    repository_path=str(proj_data["repository_path"]),
                    worktree_path=str(proj_data["worktree_path"]),
                    post_create_commands=_commands(proj_data.get("post_create_commands", [])),
                    ride_command=str(proj_data.get("ride_command", "")),
                    env_file=str(proj_data.get("env_file") or ".env"),
                    clone_paths=tuple(clone_paths_list),  # flat list of relative paths
                    container_log_services=_container_log_services(
                        proj_data.get("container_log_services", [])
                    ),
                    linked_repositories=_linked_repositories(proj_data.get("linked_repositories", [])),
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
                "repository_path": project.repository_path,
                "worktree_path": project.worktree_path,
                "ride_command": project.ride_command,
                "env_file": project.env_file,
            }
            if project.post_create_commands:
                proj_dict["post_create_commands"] = list(project.post_create_commands)
            if project.clone_paths:
                proj_dict["clone_paths"] = list(project.clone_paths)
            if project.container_log_services:
                proj_dict["container_log_services"] = list(
                    project.container_log_services
                )
            if project.linked_repositories:
                proj_dict["linked_repositories"] = [
                    {
                        "repository_path": linked.repository_path,
                        "worktree_path": linked.worktree_path,
                        "ports": {
                            port.name: f"{port.start}-{port.end}"
                            for port in linked.ports
                        },
                        "post_create_commands": list(linked.post_create_commands),
                        "post_delete_commands": list(linked.post_delete_commands),
                        "pre_start_commands": list(linked.pre_start_commands),
                        "start_command": linked.start_command,
                        "status_port_env": linked.status_port_env,
                        "status_port_file": linked.status_port_file,
                        "status_port_label": linked.status_port_label,
                        "open_url_path": linked.open_url_path,
                    }
                    for linked in project.linked_repositories
                ]
            projects_list.append(proj_dict)
        data["projects"] = projects_list

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
