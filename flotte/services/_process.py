"""Shared synchronous process execution."""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 60.0,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            tuple(args),
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        message = (
            "Command timed out"
            if isinstance(error, subprocess.TimeoutExpired)
            else str(error)
        )
        return -1, "", message
    return (
        result.returncode,
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
    )
