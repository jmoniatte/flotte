"""Read and parse Git status for any repository path."""

import asyncio
from pathlib import Path

from ..models.git_status import GitStatus
from .git_client import GitClient


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


def _get_git_status_sync(path: Path, *, fail_on_status_error: bool) -> GitStatus:
    git = GitClient(path)
    status_code, status_output, status_error = git.run("status", "--porcelain")
    if status_code != 0 and fail_on_status_error:
        detail = status_error.strip() or f"git exited with code {status_code}"
        raise RuntimeError(f"Could not inspect {path}: {detail}")
    status = (
        parse_porcelain(status_output)
        if status_code == 0
        else GitStatus()
    )

    divergence_code, divergence_output, _ = git.run(
        "rev-list",
        "--left-right",
        "--count",
        "@{upstream}...HEAD",
    )
    if divergence_code != 0:
        return status

    try:
        behind, ahead = (int(value) for value in divergence_output.split())
    except ValueError:
        return status
    return GitStatus(
        staged=status.staged,
        unstaged=status.unstaged,
        untracked=status.untracked,
        ahead=ahead,
        behind=behind,
    )


def get_git_status_sync(path: Path) -> GitStatus:
    """Read Git status, returning an empty status when Git is unavailable."""
    return _get_git_status_sync(path, fail_on_status_error=False)


def get_git_status_strict_sync(path: Path) -> GitStatus:
    """Read Git status, raising when working-tree changes cannot be inspected."""
    return _get_git_status_sync(path, fail_on_status_error=True)


async def get_git_status(path: Path) -> GitStatus:
    """Read Git status without blocking the event loop."""
    return await asyncio.to_thread(get_git_status_sync, path)


async def get_git_status_strict(path: Path) -> GitStatus:
    """Read Git status without allowing an inspection failure to look clean."""
    return await asyncio.to_thread(get_git_status_strict_sync, path)
