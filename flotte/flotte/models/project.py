from pathlib import Path

from .worktree import Worktree


class Project:
    """Project that owns worktrees.

    Initialized from config data (name, path, ride_command).
    Owns and manages its worktrees, creating them on demand.
    """

    def __init__(self, name: str, path: str, ride_command: str = ""):
        self.name = name
        self.path = Path(path)
        self.ride_command = ride_command
        self.worktrees: dict[str, Worktree] = {}

    def get_or_create_worktree(
        self,
        name: str,
        path: Path,
        branch: str = "",
        compose_project_name: str = "",
        is_main: bool = False,
    ) -> Worktree:
        """Get existing worktree or create new one.

        Args:
            name: Worktree name (e.g., 'feature-xyz')
            path: Absolute path to worktree
            branch: Git branch name
            compose_project_name: Docker Compose project name
            is_main: True only for main repo (cannot delete)

        Returns:
            Existing or newly created Worktree
        """
        if name not in self.worktrees:
            self.worktrees[name] = Worktree(
                name=name,
                path=path,
                branch=branch,
                compose_project_name=compose_project_name,
                is_main=is_main,
            )
        return self.worktrees[name]

    def remove_worktree(self, name: str) -> None:
        """Remove worktree from project."""
        self.worktrees.pop(name, None)
