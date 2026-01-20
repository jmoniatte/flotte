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
        worktree_parent: Path,
        worktree_prefix: str,
    ):
        self.main_repo_path = main_repo_path.resolve()
        self.parent_dir = worktree_parent.resolve()
        self.project_name = self.main_repo_path.name  # e.g., "ridewithgps"
        self.worktree_prefix = worktree_prefix  # "" = no prefix
        self.worktrees: dict[str, Worktree] = {}
        self._cached_volumes: list[str] | None = None

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

    async def discover_worktrees(self) -> list[Worktree]:
        """
        Discover all git worktrees and their configurations.

        Returns:
            List of Worktree objects
        """
        returncode, stdout, stderr = self._run_command(
            "git", "-C", str(self.main_repo_path), "worktree", "list"
        )

        if returncode != 0:
            return []

        worktrees = []
        # Parse format: '/path/to/worktree  hash [branch]'
        pattern = re.compile(r"^(\S+)\s+\w+\s+\[(.+?)\]")

        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue

            match = pattern.match(line)
            if not match:
                continue

            path_str, branch = match.groups()
            path = Path(path_str)

            # Skip worktrees whose directories no longer exist
            if not path.exists():
                continue

            # Read .env if exists
            env_vars = self._parse_env(path)

            # Determine if this is the main repo
            is_main = path.resolve() == self.main_repo_path.resolve()

            # Sanitize name from path
            if is_main:
                name = "main"
            elif self.worktree_prefix:
                name = path.name.removeprefix(self.worktree_prefix)
            else:
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
            self.worktrees[name] = worktree

        return worktrees

    def _parse_env(self, path: Path) -> dict[str, str]:
        """Parse .env file into dict."""
        env_file = path / ".env"
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
        """Get COMPOSE_PROJECT_NAME from main's .env, fallback to directory name."""
        main_env = self._parse_env(self.main_repo_path)
        return main_env.get("COMPOSE_PROJECT_NAME", self.project_name)

    def _get_port_offset(self, env_vars: dict[str, str]) -> int:
        """Calculate port offset by comparing a *_PORT variable to main's .env."""
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
        Find the next available port offset.

        Scans existing worktrees to find max offset and returns max + 100.
        """
        max_offset = 0

        # Scan all {worktree_prefix}-* directories
        if self.parent_dir.exists() and self.worktree_prefix:
            for path in self.parent_dir.iterdir():
                if path.is_dir() and path.name.startswith(self.worktree_prefix):
                    env_vars = self._parse_env(path)
                    offset = self._get_port_offset(env_vars)
                    if offset > max_offset:
                        max_offset = offset

        return max_offset + PORT_OFFSET_INCREMENT

    def _sanitize_branch_name(self, branch_name: str) -> str:
        """Sanitize branch name for use in directory and project names."""
        # Replace non-alphanumeric with dash
        sanitized = re.sub(r"[^a-zA-Z0-9]", "-", branch_name)
        # Remove leading/trailing dashes and collapse multiple dashes
        sanitized = re.sub(r"-+", "-", sanitized).strip("-")
        # Truncate to 30 chars
        return sanitized[:30].lower()

    def create_worktree_sync(
        self, branch_name: str, base_branch: str | None = "beta"
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
        if self.worktree_prefix:
            worktree_path = self.parent_dir / f"{self.worktree_prefix}{sanitized_name}"
        else:
            worktree_path = self.parent_dir / sanitized_name

        # Ensure parent directory exists
        self.parent_dir.mkdir(parents=True, exist_ok=True)

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

        # Get next port offset and generate .env
        offset = self.find_next_port_offset()
        compose_project_name = f"{self.get_compose_project_prefix()}-{sanitized_name}"
        self._generate_env_local(worktree_path, compose_project_name, offset)

        # Create and cache worktree object
        worktree = Worktree(
            name=sanitized_name,
            path=worktree_path,
            branch=branch_name,
            compose_project_name=compose_project_name,
            is_main=False,
        )
        self.worktrees[sanitized_name] = worktree
        return worktree

    async def create_worktree(
        self, branch_name: str, base_branch: str | None = "beta"
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
            self.create_worktree_sync, branch_name, base_branch
        )

    def _generate_env_local(
        self, worktree_path: Path, compose_project_name: str, offset: int
    ) -> None:
        """Generate .env file by reading main repo's .env and applying port offset."""
        # Read main repo's .env
        main_env = self._parse_env(self.main_repo_path)

        # Build new .env content
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

        # Write to .env (docker compose reads this automatically)
        env_file = worktree_path / ".env"
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

    async def clone_volumes(
        self,
        source_project: str,
        target_project: str,
        on_progress: callable = None,
    ) -> bool:
        """
        Clone Docker volumes from source project to target project.

        Args:
            source_project: Source compose project name (e.g., 'myproject')
            target_project: Target compose project name (e.g., 'myproject-feature')
            on_progress: Optional callback(volume_name, current, total) for progress

        Returns:
            True if successful
        """
        volumes = await self.get_volumes()
        total = len(volumes)

        for i, volume_name in enumerate(volumes):
            source_vol = f"{source_project}_{volume_name}"
            target_vol = f"{target_project}_{volume_name}"

            if on_progress:
                on_progress(volume_name, i + 1, total)

            # Create target volume
            self._run_command(
                "docker", "volume", "create", target_vol
            )

            # Copy data using alpine container
            returncode, stdout, stderr = self._run_command(
                "docker", "run", "--rm",
                "-v", f"{source_vol}:/source:ro",
                "-v", f"{target_vol}:/dest",
                "alpine",
                "sh", "-c", "cp -a /source/. /dest/",
                timeout=300.0,  # 5 min per volume
            )

            if returncode != 0:
                # Log error but continue with other volumes
                pass

        return True

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

    async def commit_all_changes(self, worktree: Worktree, message: str) -> bool:
        """
        Commit all changes in a worktree (staged, modified, and untracked).

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

        # Prune dangling worktree references
        self._run_command(
            "git", "worktree", "prune",
            cwd=self.main_repo_path,
        )

        # Remove from cache
        if worktree.name in self.worktrees:
            del self.worktrees[worktree.name]

        return True

    async def remove_worktree(self, worktree: Worktree) -> bool:
        """
        Remove a git worktree (async wrapper, keeps the branch).

        Args:
            worktree: The worktree to remove

        Returns:
            True if successful

        Raises:
            RuntimeError: If removal fails
        """
        import asyncio
        return await asyncio.to_thread(self.remove_worktree_sync, worktree)

    async def get_git_status(self, worktree: Worktree) -> dict:
        """
        Get git status for a worktree.

        Returns dict with:
            - modified: number of modified files
            - untracked: number of untracked files
            - staged: number of staged files
            - ahead: commits ahead of upstream
            - behind: commits behind upstream
        """
        result = {
            "modified": 0,
            "untracked": 0,
            "staged": 0,
            "ahead": 0,
            "behind": 0,
        }

        # Get status --porcelain for file counts
        returncode, stdout, _ = self._run_command(
            "git", "status", "--porcelain",
            cwd=worktree.path,
        )
        if returncode == 0 and stdout.strip():
            for line in stdout.strip().split("\n"):
                if not line:
                    continue
                status = line[:2]
                if status[0] in "MADRC":  # Staged
                    result["staged"] += 1
                if status[1] == "M":  # Modified in working tree
                    result["modified"] += 1
                if status == "??":  # Untracked
                    result["untracked"] += 1

        # Get ahead/behind counts
        returncode, stdout, _ = self._run_command(
            "git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD",
            cwd=worktree.path,
        )
        if returncode == 0 and stdout.strip():
            parts = stdout.strip().split()
            if len(parts) == 2:
                result["behind"] = int(parts[0])
                result["ahead"] = int(parts[1])

        return result
