import asyncio
from pathlib import Path
import unittest

from textual.app import App, ComposeResult

from flotte.models import Worktree
from flotte.app import load_stylesheet
from flotte.colors import DEFAULT_COLORS
from tui_kit.theme import load_palette
from flotte.widgets.worktree_header import WorktreeHeader, WorktreeOpened, WorktreeTable


class WorktreeHeaderApp(App):
    CSS = load_stylesheet()
    theme_colors = DEFAULT_COLORS

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **load_palette("onedark")}

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
                self.assertEqual(table.get_cell("branch-0", "state").plain, "Loading")
                worktrees[0].has_polled = True
                header.update_worktree_status(worktrees[0])
                self.assertEqual(table.get_cell("branch-0", "state").plain, "Stopped")
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


class DashedHeaderRuleTests(unittest.TestCase):
    """The rule under the header is drawn by hand, so it must carry a background."""

    def test_rule_matches_the_surrounding_background(self) -> None:
        async def main() -> tuple[str, str]:
            app = WorktreeHeaderApp()
            async with app.run_test(size=(50, 6)) as pilot:
                app.query_one(WorktreeHeader).refresh_worktrees(
                    [Worktree("main", Path("/tmp/main"), is_main=True)]
                )
                await pilot.pause()
                strips = app.screen._compositor.render_strips()
                rule = next(
                    segment
                    for segment in strips[1]
                    if segment.text.strip().startswith("-")
                )
                body = next(
                    segment for segment in strips[0] if segment.style.bgcolor
                )
                return (
                    rule.style.bgcolor.triplet.hex,
                    body.style.bgcolor.triplet.hex,
                )

        rule_background, body_background = asyncio.run(main())
        palette = load_palette("onedark")
        self.assertEqual(rule_background, body_background)
        self.assertEqual(rule_background, palette["bg"])
