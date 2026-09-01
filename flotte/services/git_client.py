"""Low-level Git command execution for one repository."""

import os
from pathlib import Path

from ._process import run_command


class GitClient:
    def __init__(self, repository_path: Path) -> None:
        self.repository_path = repository_path.resolve()

    def run(
        self,
        *args: str,
        cwd: Path | None = None,
        timeout: float = 60.0,
    ) -> tuple[int, str, str]:
        return run_command(
            ("git", "-C", str(cwd or self.repository_path), *args),
            env={**os.environ, "LC_ALL": "C"},
            timeout=timeout,
        )

    def branch_exists(self, branch: str) -> bool:
        returncode, _, _ = self.run(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        )
        return returncode == 0

    def local_branches(self) -> list[str]:
        returncode, stdout, _ = self.run("branch", "--format=%(refname:short)")
        if returncode != 0:
            return []
        return [branch.strip() for branch in stdout.splitlines() if branch.strip()]

    def remove_worktree(self, path: Path, *, force: bool = False) -> tuple[int, str, str]:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        return self.run(*args)
