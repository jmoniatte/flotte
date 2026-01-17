import asyncio
import os
from pathlib import Path
from typing import AsyncIterator


class RideWrapper:
    """Wrapper for Docker compose commands."""

    def __init__(self, worktree_path: Path, project_name: str | None = None):
        self.worktree_path = worktree_path
        self.project_name = project_name

    def _base_cmd(self) -> list[str]:
        """Get base docker compose command with project name."""
        cmd = ["docker", "compose"]
        if self.project_name:
            cmd.extend(["-p", self.project_name])
        return cmd

    async def _run(self, *args: str, timeout: float = 300.0) -> tuple[int, str, str]:
        """Execute a docker compose command."""
        cmd = self._base_cmd() + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.worktree_path,
            env=os.environ,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            proc.kill()
            return (-1, "", "Command timed out")

    async def start(self) -> tuple[int, str, str]:
        """Start Docker containers."""
        return await self._run("up", "-d")

    async def stop(self) -> tuple[int, str, str]:
        """Stop Docker containers."""
        return await self._run("down")

    async def restart(self) -> tuple[int, str, str]:
        """Restart Docker containers."""
        await self.stop()
        return await self.start()

    async def status(self) -> tuple[int, str, str]:
        """Get container status."""
        return await self._run("ps", timeout=30.0)

    async def logs(self, services: list[str] | None = None) -> AsyncIterator[str]:
        """Stream logs from containers."""
        cmd = self._base_cmd() + ["logs", "-f", "--tail", "100"]
        if services:
            cmd.extend(services)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.worktree_path,
            env=os.environ,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            assert proc.stdout is not None
            async for line in proc.stdout:
                yield line.decode("utf-8", errors="replace").rstrip("\n")
        except asyncio.CancelledError:
            proc.terminate()
            await proc.wait()
            raise
        finally:
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()
