from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LinkedWorktree:
    """The state of one companion worktree for a primary worktree."""
    repository_name: str
    path: Path | None = None
    branch: str = ""
    ports: dict[str, int] = field(default_factory=dict)
    state: str = "missing"
    error: str = ""
    open_url_path: str = ""
    can_start: bool = False
    process_status: str = "external"
    git_status: dict | None = None
