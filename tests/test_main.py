import contextlib
import io
import asyncio
from unittest.mock import AsyncMock, patch
import unittest

from flotte.__main__ import main
from flotte.app import FlotteApp
from flotte.config import Config, Project
from textual.widgets import ContentSwitcher


class MainTests(unittest.TestCase):
    def test_version_exits_without_starting_the_tui(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as error, contextlib.redirect_stdout(output):
            main(["--version"])

        self.assertEqual(error.exception.code, 0)
        self.assertTrue(output.getvalue().startswith("Flotte "))

    def test_help_exits_without_starting_the_tui(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as error, contextlib.redirect_stdout(output):
            main(["--help"])

        self.assertEqual(error.exception.code, 0)
        self.assertIn("--version", output.getvalue())

    def test_worktree_views_use_content_switcher(self) -> None:
        async def exercise() -> None:
            config = Config(
                projects=[
                    Project(
                        name="test",
                        path="/tmp/test",
                        worktree_path="/tmp/worktrees",
                        worktree_prefix="test-",
                    )
                ]
            )
            with (
                patch("flotte.app.load_config", return_value=config),
                patch.object(FlotteApp, "refresh_worktrees", new_callable=AsyncMock),
                patch("flotte.models.project.Project.start_polling"),
                patch("flotte.models.project.Project.shutdown", new_callable=AsyncMock),
            ):
                app = FlotteApp()
                async with app.run_test(size=(100, 30)) as pilot:
                    switcher = app.query_one("#view-switcher", ContentSwitcher)
                    self.assertEqual(switcher.current, "list-view")

                    app._set_view(show_details=True)
                    await pilot.pause()
                    self.assertEqual(switcher.current, "details-view")

                    app._set_view(show_details=False)
                    await pilot.pause()
                    self.assertEqual(switcher.current, "list-view")

        asyncio.run(exercise())
