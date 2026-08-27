import json
import os
import re
import subprocess
from pathlib import Path

from ..models import Worktree

PORT_OFFSET_INCREMENT = 100


class WorktreeManager:
    """Git worktree discovery, port allocation, and lifecycle management."""

    def __init__(
        self,
        main_repo_path: Path,
        worktree_path_template: str,
        clone_paths: tuple[str, ...] = (),
        env_file: str = ".env",
        post_create_commands: tuple[str, ...] = (),
        manage_environment: bool = True,
    ):
        self.main_repo_path = main_repo_path.resolve()
        if "{worktree}" not in worktree_path_template:
            raise ValueError("worktree_path_template must contain {worktree}")
        self.worktree_path_template = Path(worktree_path_template).expanduser().absolute()
        template_parts = self.worktree_path_template.parts
        placeholder_index = next(
            index for index, part in enumerate(template_parts) if "{worktree}" in part
        )
        self.worktree_root = Path(*template_parts[:placeholder_index])
        self.project_name = self.main_repo_path.name  # e.g., "ridewithgps"
        self.clone_paths = clone_paths
        self.env_file = env_file
        self.post_create_commands = post_create_commands
        self.manage_environment = manage_environment
        self._cached_volumes: list[str] | None = None

    def _worktree_name_from_path(self, path: Path) -> str | None:
        pattern = re.escape(str(self.worktree_path_template))
        pattern = pattern.replace(r"\{worktree\}", r"(?P<worktree>[^/]+)")
        match = re.fullmatch(pattern, str(path.absolute()))
        return match.group("worktree") if match else None

    def _worktree_path(self, worktree_name: str) -> Path:
        return Path(str(self.worktree_path_template).replace("{worktree}", worktree_name))

    def _run_command(
        self, *args: str, cwd: Path | None = None, timeout: float = 60.0
    ) -> tuple[int, str, str]:
        """Execute a command and return results."""
        try:
            result = subprocess.run(
                args,
                cwd=cwd or self.main_repo_path,
                env=os.environ,
                capture_output=True,
                timeout=timeout,
            )
            return (
                result.returncode,
                result.stdout.decode("utf-8", errors="replace"),
                result.stderr.decode("utf-8", errors="replace"),
            )
        except subprocess.TimeoutExpired:
            return (-1, "", "Command timed out")

    def discover_worktrees_sync(self) -> list[Worktree]:
        """
        Discover all git worktrees and their configurations (synchronous).

        Returns:
            List of Worktree objects
        """
        returncode, stdout, stderr = self._run_command(
            "git", "-C", str(self.main_repo_path), "worktree", "list"
        )

        if returncode != 0:
            return []

        worktrees = []
        # Parse '/path/to/worktree  hash [branch]' or '... (detached HEAD)'
        pattern = re.compile(r"^(\S+)\s+\w+\s+(\[.+?\]|\(.+?\))")

        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue

            match = pattern.match(line)
            if not match:
                continue

            path_str, ref = match.groups()
            branch = ref[1:-1] if ref.startswith("[") else ""
            path = Path(path_str)

            # Skip worktrees whose directories no longer exist
            if not path.exists():
                continue

            # Read .env if exists
            env_vars = self._parse_env(path)

            # Determine if this is the main repo
            is_main = path.resolve() == self.main_repo_path.resolve()

            # Determine the configured worktree name from its path.
            if is_main:
                name = "main"
            else:
                name = self._worktree_name_from_path(path)
                if name is None:
                    name = path.name

            # Get compose project name - default to directory name (what docker compose uses)
            compose_project_name = env_vars.get(
                "COMPOSE_PROJECT_NAME", path.name
            )

            worktree = Worktree(
                name=name,
                path=path,
                branch=branch,
                compose_project_name=compose_project_name,
                is_main=is_main,
            )
            worktrees.append(worktree)

        return worktrees

    async def discover_worktrees(self) -> list[Worktree]:
        """Discover all git worktrees and their configurations (async wrapper)."""
        import asyncio
        return await asyncio.to_thread(self.discover_worktrees_sync)

    def _parse_env(self, path: Path) -> dict[str, str]:
        """Parse the project's env file into dict."""
        env_file = path / self.env_file
        if not env_file.exists():
            return {}

        env_vars = {}
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and blank lines
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, value = line.split("=", 1)
                        env_vars[key.strip()] = value.strip()
        except (OSError, IOError):
            pass

        return env_vars

    def get_compose_project_prefix(self) -> str:
        """Get COMPOSE_PROJECT_NAME from main's env file, fallback to directory name."""
        main_env = self._parse_env(self.main_repo_path)
        return main_env.get("COMPOSE_PROJECT_NAME", self.project_name)

    def _get_port_offset(self, env_vars: dict[str, str]) -> int:
        """Calculate port offset by comparing a *_PORT variable to main's env file."""
        main_env = self._parse_env(self.main_repo_path)

        # Find first *_PORT variable that exists in both
        for key, value in env_vars.items():
            if key.endswith("_PORT") and key in main_env:
                try:
                    worktree_port = int(value)
                    main_port = int(main_env[key])
                    return worktree_port - main_port
                except ValueError:
                    continue
        return 0

    def find_next_port_offset(self) -> int:
        """
        Find the lowest available port offset.

        Discovers current worktrees to collect used offsets, then returns the
        first multiple of PORT_OFFSET_INCREMENT not already in use.
        """
        used_offsets: set[int] = set()

        for worktree in self.discover_worktrees_sync():
            if worktree.is_main:
                continue
            offset = self._get_port_offset(self._parse_env(worktree.path))
            if offset > 0:
                used_offsets.add(offset)

        candidate = PORT_OFFSET_INCREMENT
        while candidate in used_offsets:
            candidate += PORT_OFFSET_INCREMENT
        return candidate

    def _sanitize_branch_name(self, branch_name: str) -> str:
        """Sanitize branch name for use in directory and project names."""
        # Replace non-alphanumeric with dash
        sanitized = re.sub(r"[^a-zA-Z0-9]", "-", branch_name)
        # Remove leading/trailing dashes and collapse multiple dashes
        sanitized = re.sub(r"-+", "-", sanitized).strip("-")
        # Truncate to 30 chars
        return sanitized[:30].lower()

    def create_worktree_sync(
        self,
        branch_name: str,
        base_branch: str | None = "beta",
    ) -> Worktree:
        """
        Create a new worktree with its own port configuration (synchronous).

        Args:
            branch_name: Name for the new branch (or existing branch if base_branch is None)
            base_branch: Branch to base the new worktree on.
                         If None, use existing branch (no new branch created).

        Returns:
            The created Worktree object

        Raises:
            RuntimeError: If worktree creation fails
        """
        sanitized_name = self._sanitize_branch_name(branch_name)
        worktree_path = self._worktree_path(sanitized_name)

        # Ensure parent directory exists
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # Create git worktree
        if base_branch is None:
            # Existing branch mode: git worktree add <path> <existing-branch>
            returncode, stdout, stderr = self._run_command(
                "git",
                "-C",
                str(self.main_repo_path),
                "worktree",
                "add",
                str(worktree_path),
                branch_name,
            )
        else:
            # New branch mode: git worktree add -b <new-branch> <path> <base-branch>
            returncode, stdout, stderr = self._run_command(
                "git",
                "-C",
                str(self.main_repo_path),
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                base_branch,
            )

        if returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {stderr}")

        compose_project_name = ""
        if self.manage_environment:
            offset = self.find_next_port_offset()
            compose_project_name = f"{self.get_compose_project_prefix()}-{sanitized_name}"
            self._generate_env_file(worktree_path, compose_project_name, offset)

        return Worktree(
            name=sanitized_name,
            path=worktree_path,
            branch=branch_name,
            compose_project_name=compose_project_name,
            is_main=False,
        )

    async def create_worktree(
        self,
        branch_name: str,
        base_branch: str | None = "beta",
    ) -> Worktree:
        """
        Create a new worktree with its own port configuration (async wrapper).

        Args:
            branch_name: Name for the new branch (or existing branch if base_branch is None)
            base_branch: Branch to base the new worktree on.
                         If None, use existing branch (no new branch created).

        Returns:
            The created Worktree object

        Raises:
            RuntimeError: If worktree creation fails
        """
        import asyncio
        return await asyncio.to_thread(
            self.create_worktree_sync,
            branch_name,
            base_branch,
        )

    def _generate_env_file(
        self, worktree_path: Path, compose_project_name: str, offset: int
    ) -> None:
        """Generate the worktree's env file from main's, applying port offset."""
        main_env = self._parse_env(self.main_repo_path)

        # Build new env file content
        lines = [f"COMPOSE_PROJECT_NAME={compose_project_name}"]

        # Copy all variables from main, applying offset to *_PORT variables
        for key, value in main_env.items():
            if key == "COMPOSE_PROJECT_NAME":
                continue  # Already added above
            if key.endswith("_PORT"):
                try:
                    port = int(value)
                    lines.append(f"{key}={port + offset}")
                except ValueError:
                    lines.append(f"{key}={value}")
            else:
                lines.append(f"{key}={value}")

        # Must match what _parse_env reads, or flotte cannot resolve its own worktrees
        env_file = worktree_path / self.env_file
        env_file.parent.mkdir(parents=True, exist_ok=True)
        with open(env_file, "w") as f:
            f.write("\n".join(lines) + "\n")

    def get_volumes_sync(self) -> list[str]:
        """Get volume names from docker-compose.yml (synchronous)."""
        if self._cached_volumes is not None:
            return self._cached_volumes

        returncode, stdout, stderr = self._run_command(
            "docker", "compose", "config", "--format", "json",
            cwd=self.main_repo_path,
            timeout=30.0,
        )
        if returncode != 0:
            # Fallback to empty list if compose config fails
            return []

        try:
            config = json.loads(stdout)
            self._cached_volumes = list(config.get("volumes", {}).keys())
            return self._cached_volumes
        except json.JSONDecodeError:
            return []

    async def get_volumes(self) -> list[str]:
        """Get volume names from docker-compose.yml (async wrapper)."""
        if self._cached_volumes is not None:
            return self._cached_volumes
        import asyncio
        return await asyncio.to_thread(self.get_volumes_sync)

    def get_built_services_sync(self) -> list[str]:
        """Get service names that have a build directive in docker-compose.yml."""
        returncode, stdout, stderr = self._run_command(
            "docker", "compose", "config", "--format", "json",
            cwd=self.main_repo_path,
            timeout=30.0,
        )
        if returncode != 0:
            return []
        try:
            config = json.loads(stdout)
            return [
                name for name, svc in config.get("services", {}).items()
                if "build" in svc
            ]
        except json.JSONDecodeError:
            return []

    def tag_images_sync(
        self, source_project: str, target_project: str, services: list[str]
    ) -> list[tuple[str, str]]:
        """Tag source project images for target project.

        Returns list of (service, error) for failures.
        """
        failures = []
        for service in services:
            source_image = f"{source_project}-{service}:latest"
            target_image = f"{target_project}-{service}:latest"
            returncode, _, stderr = self._run_command(
                "docker", "tag", source_image, target_image
            )
            if returncode != 0:
                failures.append((service, stderr.strip()))
        return failures

    def get_gitignored_bind_mounts_sync(self) -> list[str]:
        """Get gitignored bind mount paths from docker-compose.yml (synchronous).

        Returns relative paths like 'files' or 'config/local.yml' (without ./ prefix).
        Includes both files and directories. Follows symlinks (copies target contents).

        Returns empty list if docker compose config fails (e.g., Docker not running,
        no docker-compose.yml, invalid config) - this is intentional to allow
        worktree creation to proceed without bind mount cloning.
        """
        returncode, stdout, stderr = self._run_command(
            "docker", "compose", "config", "--format", "json",
            cwd=self.main_repo_path,
            timeout=30.0,
        )
        if returncode != 0:
            return []

        try:
            config = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        # Extract bind mount paths from all services
        bind_mounts = set()
        for service in config.get("services", {}).values():
            for volume in service.get("volumes", []):
                # docker compose config --format json outputs long-form:
                # {"type": "bind", "source": "/absolute/path", "target": "/container/path"}
                if isinstance(volume, dict) and volume.get("type") == "bind":
                    source = volume.get("source", "")
                    # Convert absolute path to relative if within repo
                    try:
                        rel_path = Path(source).relative_to(self.main_repo_path)
                        # Skip repo root mount (.)
                        if str(rel_path) != ".":
                            bind_mounts.add(str(rel_path))
                    except ValueError:
                        # Path is outside repo, skip
                        pass

        if not bind_mounts:
            return []

        # Filter to only gitignored paths
        returncode, stdout, stderr = self._run_command(
            "git", "check-ignore", *bind_mounts,
            cwd=self.main_repo_path,
        )
        # git check-ignore returns ignored paths (exit 0) or nothing (exit 1)
        if stdout.strip():
            return stdout.strip().split("\n")
        return []

    async def get_gitignored_bind_mounts(self) -> list[str]:
        """Get gitignored bind mount paths from docker-compose.yml (async wrapper)."""
        import asyncio
        return await asyncio.to_thread(self.get_gitignored_bind_mounts_sync)

    def run_post_create_command_sync(
        self,
        command: str,
        worktree: Worktree,
        timeout: float = 300.0,
    ) -> tuple[bool, str]:
        """
        Run a configured setup command inside a newly created worktree.

        The command goes through `sh -c`, so shell operators, globs and variable
        expansion work. It runs with the worktree as cwd and receives the same
        PROJECT_PATH / PROJECT_NAME env vars as ride_command, plus MAIN_REPO_PATH
        so commands can copy files out of the main repo.

        Returns:
            (success, error_message) - error_message is empty string on success
        """
        env = {
            **os.environ,
            "PROJECT_PATH": str(worktree.path),
            "PROJECT_NAME": worktree.name,
            "MAIN_REPO_PATH": str(self.main_repo_path),
        }
        try:
            result = subprocess.run(
                ["sh", "-c", command],
                cwd=worktree.path,
                env=env,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return (False, "Command timed out")
        except Exception as e:
            return (False, str(e))

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if len(stderr) > 300:
                stderr = "..." + stderr[-300:]  # tail: build tools put the real error last
            return (False, stderr or f"exited with code {result.returncode}")
        return (True, "")

    def get_all_clone_paths(self) -> list[str]:
        """Return clone_paths that exist in the main repo."""
        return [p for p in self.clone_paths if (self.main_repo_path / p).exists()]

    def clone_path_sync(
        self,
        source: Path,
        target: Path,
    ) -> tuple[bool, str]:
        """
        Clone a single bind mount (file or directory) using Docker/Alpine.

        Follows symlinks (copies the target contents, not the symlink itself).
        Uses cp -a to preserve permissions, ownership, and timestamps.

        Args:
            source: Absolute path to source file/directory in main worktree
            target: Absolute path to target file/directory in new worktree

        Returns:
            (success, error_message) - error_message is empty string on success
        """
        # Pre-create parent directory as current user (not root)
        target.parent.mkdir(parents=True, exist_ok=True)

        uid = os.getuid()
        gid = os.getgid()

        if source.is_dir():
            # Create target directory as current user before Docker mounts it
            target.mkdir(exist_ok=True)
            # Copy directory contents, then chown to current user
            returncode, stdout, stderr = self._run_command(
                "docker", "run", "--rm",
                "-v", f"{source}:/source:ro",
                "-v", f"{target}:/dest",
                "alpine", "sh", "-c",
                f"cp -a /source/. /dest/ && chown -R {uid}:{gid} /dest/",
                timeout=300.0,
            )
        else:
            # Copy single file, then chown to current user
            returncode, stdout, stderr = self._run_command(
                "docker", "run", "--rm",
                "-v", f"{source}:/source/file:ro",
                "-v", f"{target.parent}:/dest",
                "alpine", "sh", "-c",
                f"cp -a /source/file /dest/{target.name} && chown {uid}:{gid} /dest/{target.name}",
                timeout=60.0,
            )

        if returncode != 0:
            return False, stderr.strip() or f"Docker copy failed with code {returncode}"
        return True, ""

    def clone_volume_sync(
        self,
        source_project: str,
        target_project: str,
        volume_name: str,
    ) -> tuple[bool, str]:
        """Clone one named volume into a worktree's Compose project."""
        source_volume = f"{source_project}_{volume_name}"
        target_volume = f"{target_project}_{volume_name}"
        returncode, _, stderr = self._run_command(
            "docker", "volume", "create", target_volume
        )
        if returncode != 0:
            return False, stderr.strip() or "Docker volume creation failed"

        returncode, _, stderr = self._run_command(
            "docker", "run", "--rm",
            "-v", f"{source_volume}:/source:ro",
            "-v", f"{target_volume}:/dest",
            "alpine", "sh", "-c", "cp -a /source/. /dest/",
            timeout=300.0,
        )
        if returncode != 0:
            return False, stderr.strip() or f"Docker copy failed with code {returncode}"
        return True, ""

    def cleanup_docker_sync(self, worktree: Worktree) -> bool:
        """
        Clean up Docker resources for a worktree (synchronous).

        Keeps the git worktree and code intact.

        Args:
            worktree: The worktree to clean up

        Returns:
            True if successful

        Raises:
            RuntimeError: If cleanup fails
        """
        # Stop and remove containers
        compose_file = worktree.path / "docker-compose.yml"
        if not compose_file.exists():
            # No compose file means no containers to stop - just skip
            return True

        returncode, stdout, stderr = self._run_command(
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "-p",
            worktree.compose_project_name,
            "down",
            "--volumes",
            "--remove-orphans",
            cwd=worktree.path,
            timeout=120.0,  # 2 minutes for compose down
        )

        if returncode != 0:
            raise RuntimeError(f"docker compose down failed: {stderr}")

        # Explicitly remove all associated volumes (ignore errors - some may not exist)
        volumes = self.get_volumes_sync()
        for volume_name in volumes:
            full_volume_name = f"{worktree.compose_project_name}_{volume_name}"
            self._run_command(
                "docker", "volume", "rm", "-f", full_volume_name
            )

        # Remove tagged images for built services
        built_services = self.get_built_services_sync()
        for service in built_services:
            image_name = f"{worktree.compose_project_name}-{service}"
            self._run_command("docker", "rmi", image_name)

        return True

    async def cleanup_docker(self, worktree: Worktree) -> bool:
        """
        Clean up Docker resources for a worktree (async wrapper).

        Keeps the git worktree and code intact.

        Args:
            worktree: The worktree to clean up

        Returns:
            True if successful

        Raises:
            RuntimeError: If cleanup fails
        """
        import asyncio
        return await asyncio.to_thread(self.cleanup_docker_sync, worktree)

    def commit_all_changes_sync(self, worktree: Worktree, message: str) -> bool:
        """
        Commit all changes in a worktree (synchronous).

        Args:
            worktree: The worktree to commit in
            message: Commit message

        Returns:
            True if successful

        Raises:
            RuntimeError: If commit fails
        """
        # Stage all changes
        returncode, stdout, stderr = self._run_command(
            "git", "add", "-A",
            cwd=worktree.path,
        )
        if returncode != 0:
            raise RuntimeError(f"git add failed: {stderr}")

        # Commit
        returncode, stdout, stderr = self._run_command(
            "git", "commit", "-m", message,
            cwd=worktree.path,
        )
        if returncode != 0:
            raise RuntimeError(f"git commit failed: {stderr}")

        return True

    async def commit_all_changes(self, worktree: Worktree, message: str) -> bool:
        """Commit all changes in a worktree (async wrapper)."""
        import asyncio
        return await asyncio.to_thread(self.commit_all_changes_sync, worktree, message)

    def remove_worktree_sync(self, worktree: Worktree) -> bool:
        """
        Remove a git worktree (synchronous, keeps the branch).

        Args:
            worktree: The worktree to remove

        Returns:
            True if successful

        Raises:
            RuntimeError: If removal fails
        """
        # Docker may have created root-owned files. Clean them up using Docker.
        if worktree.path.exists():
            self._run_command(
                "docker", "run", "--rm",
                "-v", f"{worktree.path}:/worktree",
                "alpine", "rm", "-rf", "/worktree",
                timeout=60.0,
            )

        # If directory still exists (docker cleanup failed), try regular rm
        if worktree.path.exists():
            self._run_command(
                "rm", "-rf", str(worktree.path),
                timeout=30.0,
            )

        self.prune_empty_worktree_parents(worktree.path)

        # Prune dangling worktree references
        self._run_command(
            "git", "worktree", "prune",
            cwd=self.main_repo_path,
        )

        return True

    def prune_empty_worktree_parents(self, worktree_path: Path) -> None:
        path = worktree_path.absolute()
        try:
            path.relative_to(self.worktree_root)
        except ValueError:
            return

        parent = path.parent
        while parent != self.worktree_root:
            try:
                parent.rmdir()
            except OSError:
                return
            parent = parent.parent
