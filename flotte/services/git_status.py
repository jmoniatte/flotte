"""Read and parse Git status for any repository path."""

import asyncio
import subprocess
from pathlib import Path

from ..models.git_status import GitStatus


def parse_porcelain(output: str) -> GitStatus:
    """Summarize the two-column codes from ``git status --porcelain``."""
    staged = 0
    unstaged = 0
    untracked = 0

    for line in output.splitlines():
        if len(line) < 2:
            continue
        index_state, worktree_state = line[:2]
        if (index_state, worktree_state) == ("?", "?"):
            untracked += 1
            continue
        if (index_state, worktree_state) == ("!", "!"):
            continue
        if index_state != " ":
            staged += 1
        if worktree_state != " ":
            unstaged += 1

    return GitStatus(staged=staged, unstaged=unstaged, untracked=untracked)


def _run_git(path: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ("git", *args),
            cwd=path,
            capture_output=True,
            text=True,
            timeout=60.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def get_git_status_sync(path: Path) -> GitStatus:
    """Read file changes and upstream divergence for a Git worktree."""
    status_result = _run_git(path, "status", "--porcelain")
    status = (
        parse_porcelain(status_result.stdout)
        if status_result is not None and status_result.returncode == 0
        else GitStatus()
    )

    divergence_result = _run_git(
        path,
        "rev-list",
        "--left-right",
        "--count",
        "@{upstream}...HEAD",
    )
    if divergence_result is None or divergence_result.returncode != 0:
        return status

    try:
        behind, ahead = (int(value) for value in divergence_result.stdout.split())
    except ValueError:
        return status
    return GitStatus(
        staged=status.staged,
        unstaged=status.unstaged,
        untracked=status.untracked,
        ahead=ahead,
        behind=behind,
    )


async def get_git_status(path: Path) -> GitStatus:
    """Read Git status without blocking the event loop."""
    return await asyncio.to_thread(get_git_status_sync, path)
