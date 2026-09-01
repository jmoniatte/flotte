import asyncio
import re
from pathlib import Path

from ..models import Worktree
from .git_client import GitClient


class WorktreeManager:
    """Discover and manage Git worktrees for one repository."""

    def __init__(
        self,
        main_repo_path: Path,
        worktree_path_template: str,
        git: GitClient | None = None,
    ):
        self.main_repo_path = main_repo_path.resolve()
        self.git = git or GitClient(self.main_repo_path)
        if "{worktree}" not in worktree_path_template:
            raise ValueError("worktree_path_template must contain {worktree}")
        self.worktree_path_template = Path(worktree_path_template).expanduser().absolute()
        template_parts = self.worktree_path_template.parts
        placeholder_index = next(
            index for index, part in enumerate(template_parts) if "{worktree}" in part
        )
        self.worktree_root = Path(*template_parts[:placeholder_index])

    def _worktree_name_from_path(self, path: Path) -> str | None:
        pattern = re.escape(str(self.worktree_path_template))
        pattern = pattern.replace(r"\{worktree\}", r"(?P<worktree>[^/]+)")
        match = re.fullmatch(pattern, str(path.absolute()))
        return match.group("worktree") if match else None

    def _worktree_path(self, worktree_name: str) -> Path:
        return Path(str(self.worktree_path_template).replace("{worktree}", worktree_name))

    def discover_worktrees_sync(self) -> list[Worktree]:
        """
        Discover all Git worktrees for the repository.

        Returns:
            List of Worktree objects
        """
        returncode, stdout, stderr = self.git.run("worktree", "list")

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

            # Determine if this is the main repo
            is_main = path.resolve() == self.main_repo_path.resolve()

            # Determine the configured worktree name from its path.
            if is_main:
                name = "main"
            else:
                name = self._worktree_name_from_path(path)
                if name is None:
                    name = path.name

            worktree = Worktree(
                name=name,
                path=path,
                branch=branch,
                is_main=is_main,
            )
            worktrees.append(worktree)

        return worktrees

    async def discover_worktrees(self) -> list[Worktree]:
        """Discover all Git worktrees without blocking the event loop."""
        return await asyncio.to_thread(self.discover_worktrees_sync)

    async def branches(self) -> list[str]:
        return await asyncio.to_thread(self.git.local_branches)

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
        Create a new Git worktree.

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
            returncode, stdout, stderr = self.git.run(
                "worktree",
                "add",
                str(worktree_path),
                branch_name,
            )
        else:
            # New branch mode: git worktree add -b <new-branch> <path> <base-branch>
            returncode, stdout, stderr = self.git.run(
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                base_branch,
            )

        if returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {stderr}")

        return Worktree(
            name=sanitized_name,
            path=worktree_path,
            branch=branch_name,
            is_main=False,
        )

    async def create_worktree(
        self,
        branch_name: str,
        base_branch: str | None = "beta",
    ) -> Worktree:
        """
        Create a new Git worktree without blocking the event loop.

        Args:
            branch_name: Name for the new branch (or existing branch if base_branch is None)
            base_branch: Branch to base the new worktree on.
                         If None, use existing branch (no new branch created).

        Returns:
            The created Worktree object

        Raises:
            RuntimeError: If worktree creation fails
        """
        return await asyncio.to_thread(
            self.create_worktree_sync,
            branch_name,
            base_branch,
        )

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
        returncode, stdout, stderr = self.git.run(
            "add", "-A",
            cwd=worktree.path,
        )
        if returncode != 0:
            raise RuntimeError(f"git add failed: {stderr}")

        # Commit
        returncode, stdout, stderr = self.git.run(
            "commit", "-m", message,
            cwd=worktree.path,
        )
        if returncode != 0:
            raise RuntimeError(f"git commit failed: {stderr}")

        return True

    async def commit_all_changes(self, worktree: Worktree, message: str) -> bool:
        """Commit all changes in a worktree (async wrapper)."""
        return await asyncio.to_thread(self.commit_all_changes_sync, worktree, message)

    def remove_worktree_sync(self, worktree: Worktree) -> bool:
        """Remove a Git worktree while keeping its branch."""
        returncode, _, error = self.git.remove_worktree(worktree.path, force=True)
        if returncode != 0:
            raise RuntimeError(f"Failed to remove worktree: {error}")
        self.prune_empty_worktree_parents(worktree.path)
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
