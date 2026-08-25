"""Persistent state and process-safe port allocation for linked worktrees."""

import fcntl
import socket
from pathlib import Path

import yaml


STATE_FILE = Path.home() / ".local" / "state" / "flotte" / "linked-worktrees.yaml"


class LinkStateStore:
    """Persist link lifecycle state and allocate its ports under one lock."""

    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file

    def allocate(self, link_key: str, ranges: dict[str, tuple[int, int]]) -> dict[str, int]:
        """Return the existing allocation for a link or allocate ports atomically."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "a+") as state_handle:
            fcntl.flock(state_handle.fileno(), fcntl.LOCK_EX)
            state_handle.seek(0)
            data = yaml.safe_load(state_handle) or {}
            links = data.setdefault("links", {})
            record = links.setdefault(link_key, {})
            existing = record.get("ports", {})
            if existing and all(name in existing for name in ranges):
                return {name: int(existing[name]) for name in ranges}

            used = {
                int(port)
                for other_key, other in links.items()
                if other_key != link_key
                for port in other.get("ports", {}).values()
            }
            allocated: dict[str, int] = {}
            for name, (start, end) in ranges.items():
                port = next(
                    (candidate for candidate in range(start, end + 1)
                     if candidate not in used and candidate not in allocated.values()
                     and self._is_available(candidate)),
                    None,
                )
                if port is None:
                    raise RuntimeError(f"No available port in configured range {start}-{end} for {name}")
                allocated[name] = port

            record["ports"] = allocated
            self._write_locked(state_handle, data)
            return allocated

    def get_record(self, link_key: str) -> dict:
        if not self.state_file.exists():
            return {}
        with open(self.state_file, "r") as state_handle:
            fcntl.flock(state_handle.fileno(), fcntl.LOCK_SH)
            return (yaml.safe_load(state_handle) or {}).get("links", {}).get(link_key, {})

    def update_record(self, link_key: str, **values: object) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "a+") as state_handle:
            fcntl.flock(state_handle.fileno(), fcntl.LOCK_EX)
            state_handle.seek(0)
            data = yaml.safe_load(state_handle) or {}
            record = data.setdefault("links", {}).setdefault(link_key, {})
            record.update(values)
            self._write_locked(state_handle, data)

    def release(self, link_key: str) -> None:
        if not self.state_file.exists():
            return
        with open(self.state_file, "r+") as state_handle:
            fcntl.flock(state_handle.fileno(), fcntl.LOCK_EX)
            data = yaml.safe_load(state_handle) or {}
            data.get("links", {}).pop(link_key, None)
            self._write_locked(state_handle, data)

    @staticmethod
    def _is_available(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    @staticmethod
    def _write_locked(state_handle, data: dict) -> None:
        state_handle.seek(0)
        state_handle.truncate()
        yaml.safe_dump(data, state_handle, default_flow_style=False)
        state_handle.flush()
