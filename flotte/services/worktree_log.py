import csv
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import shutil
from time import perf_counter

LOG_DIR = Path.home() / ".local" / "state" / "flotte" / "logs"
logger = logging.getLogger(__name__)


class WorktreeLogStore:
    """Persist a worktree's lifecycle history."""

    def __init__(self, project_name: str, log_dir: Path | None = None):
        self.project_name = self._slug(project_name)
        self.log_dir = log_dir or LOG_DIR

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
        return slug or "project"

    @staticmethod
    def _single_line(value: str) -> str:
        return " ".join(value.split())

    def path_for(self, worktree_name: str) -> Path:
        return self.directory_for(worktree_name) / "flotte.csv"

    def directory_for(self, worktree_name: str) -> Path:
        return self.log_dir / self.project_name / self._slug(worktree_name)

    def linked_path_for(self, worktree_name: str, repository_name: str) -> Path:
        return self.directory_for(worktree_name) / f"{self._slug(repository_name)}.log"

    def remove_linked(self, worktree_name: str, repository_name: str) -> None:
        try:
            self.linked_path_for(worktree_name, repository_name).unlink(missing_ok=True)
        except OSError:
            logger.warning("Unable to remove linked process log", exc_info=True)

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
                        "action": self._single_line(action),
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
            shutil.rmtree(self.directory_for(worktree_name))
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Unable to remove worktree log", exc_info=True)
