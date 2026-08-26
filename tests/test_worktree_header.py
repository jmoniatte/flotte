import asyncio
from pathlib import Path
import unittest

from textual.app import App, ComposeResult

from flotte.models import Worktree
from flotte.theme import DEFAULT_COLORS
from flotte.widgets.worktree_header import WorktreeHeader, WorktreeOpened, WorktreeTable


class WorktreeHeaderApp(App):
    CSS = (
        Path("flotte/styles/themes/onedark.tcss").read_text()
        + "\n"
        + Path("flotte/styles/base.tcss").read_text()
    )
    theme_colors = DEFAULT_COLORS

    def __init__(self) -> None:
        super().__init__()
        self.opened_worktrees: list[str] = []

    def compose(self) -> ComposeResult:
        yield WorktreeHeader(id="worktree-header")

    def on_worktree_opened(self, event: WorktreeOpened) -> None:
        self.opened_worktrees.append(event.worktree.name)


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
                header.select_worktree(worktrees[0])
                await pilot.pause()

                table = app.query_one("#worktree-table", WorktreeTable)
                self.assertIs(app.focused, table)
                self.assertEqual(table.row_count, 12)
                self.assertEqual(header.size.height, 15)
                self.assertEqual(table.styles.scrollbar_size_horizontal, 0)
                self.assertEqual(table.styles.scrollbar_size_vertical, 0)
                footer_rule = app.query_one("#worktree-table-footer-rule")
                self.assertTrue(footer_rule.render().plain.lstrip().startswith("-"))

        asyncio.run(exercise())

    def test_single_click_opens_a_worktree(self) -> None:
        async def exercise() -> None:
            app = WorktreeHeaderApp()
            async with app.run_test(size=(100, 30)) as pilot:
                header = app.query_one("#worktree-header", WorktreeHeader)
                header.refresh_worktrees([Worktree("branch", Path("/tmp/branch"))])
                await pilot.pause()

                await pilot.click("#worktree-table", offset=(10, 2))
                await pilot.pause()

                self.assertEqual(app.opened_worktrees, ["branch"])

        asyncio.run(exercise())

    def test_j_and_k_move_the_worktree_cursor(self) -> None:
        async def exercise() -> None:
            app = WorktreeHeaderApp()
            async with app.run_test(size=(100, 30)) as pilot:
                header = app.query_one("#worktree-header", WorktreeHeader)
                worktrees = [
                    Worktree("main", Path("/tmp/main"), is_main=True),
                    Worktree("second", Path("/tmp/second")),
                ]
                header.refresh_worktrees(worktrees)
                header.select_worktree(worktrees[0])
                await pilot.pause()

                table = app.query_one("#worktree-table", WorktreeTable)
                self.assertIs(app.focused, table)
                self.assertEqual(table.cursor_row, 0)

                await pilot.press("j")
                self.assertEqual(table.cursor_row, 1)

                await pilot.press("k")
                self.assertEqual(table.cursor_row, 0)

                await pilot.press("down")
                self.assertEqual(table.cursor_row, 1)

                await pilot.hover("#worktree-table", offset=(10, 2))
                await pilot.pause()
                self.assertEqual(table.cursor_row, 0)
                self.assertEqual(header.selected_worktree.name, "main")

                await pilot.hover("#worktree-table", offset=(10, 3))
                await pilot.pause()
                self.assertEqual(table.cursor_row, 1)
                self.assertEqual(header.selected_worktree.name, "second")

        asyncio.run(exercise())
