import asyncio
from pathlib import Path
import unittest

from textual.app import App, ComposeResult

from flotte.models import Worktree
from flotte.theme import DEFAULT_COLORS
from flotte.widgets.worktree_header import WorktreeHeader, WorktreeTable


class WorktreeHeaderApp(App):
    CSS = (
        Path("flotte/styles/themes/onedark.tcss").read_text()
        + "\n"
        + Path("flotte/styles/base.tcss").read_text()
    )
    theme_colors = DEFAULT_COLORS

    def compose(self) -> ComposeResult:
        yield WorktreeHeader(id="worktree-header")


class WorktreeHeaderTests(unittest.TestCase):
    def test_worktree_table_expands_without_scrollbar_chrome(self) -> None:
        async def exercise() -> None:
            app = WorktreeHeaderApp()
            async with app.run_test(size=(100, 30)) as pilot:
                header = app.query_one("#worktree-header", WorktreeHeader)
                worktrees = [
                    Worktree(f"branch-{index}", Path(f"/tmp/branch-{index}"))
                    for index in range(12)
                ]
                header.refresh_worktrees(worktrees)
                await pilot.pause()

                table = app.query_one("#worktree-table", WorktreeTable)
                self.assertEqual(table.row_count, 12)
                self.assertEqual(header.size.height, 13)
                self.assertEqual(table.styles.scrollbar_size_horizontal, 0)
                self.assertEqual(table.styles.scrollbar_size_vertical, 0)

        asyncio.run(exercise())
