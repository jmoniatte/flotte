import csv
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from time import perf_counter

LOG_DIR = Path.home() / ".local" / "state" / "flotte" / "logs"
logger = logging.getLogger(__name__)


class WorktreeLogStore:
    """Persist a worktree's lifecycle history."""

    def __init__(self, project_name: str):
        self.project_name = self._slug(project_name)

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
        return slug or "project"

    def path_for(self, worktree_name: str) -> Path:
        return LOG_DIR / f"{self.project_name}-{self._slug(worktree_name)}.csv"

    def record(
        self,
        worktree_name: str,
        action: str,
        duration_seconds: float,
        succeeded: bool,
    ) -> None:
        try:
            log_path = self.path_for(worktree_name)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            write_header = not log_path.exists()
            with log_path.open("a", encoding="utf-8", newline="") as log_file:
                writer = csv.DictWriter(
                    log_file,
                    fieldnames=("timestamp", "action", "status", "duration_seconds"),
                )
                if write_header:
                    writer.writeheader()
                writer.writerow(
                    {
                        "timestamp": timestamp,
                        "action": action,
                        "status": "success" if succeeded else "failed",
                        "duration_seconds": f"{duration_seconds:.6f}",
                    }
                )
        except OSError:
            logger.warning("Unable to write worktree log", exc_info=True)

    def record_elapsed(
        self,
        worktree_name: str,
        action: str,
        started_at: float,
        succeeded: bool,
    ) -> None:
        self.record(worktree_name, action, perf_counter() - started_at, succeeded)

    @staticmethod
    def format_duration(duration_seconds: float) -> str:
        if duration_seconds < 1:
            return f"{duration_seconds:.1f}s"
        if duration_seconds < 60:
            return f"{round(duration_seconds)}s"
        minutes, seconds = divmod(round(duration_seconds), 60)
        return f"{minutes}m {seconds}s"

    def remove(self, worktree_name: str) -> None:
        try:
            self.path_for(worktree_name).unlink(missing_ok=True)
        except OSError:
            logger.warning("Unable to remove worktree log", exc_info=True)
