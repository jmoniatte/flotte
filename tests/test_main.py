import contextlib
import io
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
import unittest

from flotte.__main__ import main
from flotte.app import FlotteApp
from flotte.config import Config, Project
from flotte.models import Container, Worktree
from flotte.widgets import WebLink
from textual.widgets import Button, ContentSwitcher, Static


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
                        repository_path="/tmp/test",
                        worktree_path="/tmp/worktrees/test-{worktree}",
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
                    list_title_y = app.query_one("#worktrees-title").region.y

                    app._set_view(show_details=True)
                    await pilot.pause()
                    self.assertEqual(switcher.current, "details-view")
                    self.assertEqual(
                        app.query_one("#breadcrumbs").region.y, list_title_y
                    )
                    breadcrumbs = app.query_one("#breadcrumbs")
                    self.assertEqual(
                        app.query_one("#container-table").region.y,
                        breadcrumbs.region.bottom + 1,
                    )
                    container_table = app.query_one("#container-table")
                    self.assertEqual(container_table.cursor_type, "none")
                    self.assertEqual(container_table.header_height, 2)
                    self.assertEqual(container_table.columns["service"].width, 20)
                    self.assertEqual(container_table.columns["ports"].width, 10)
                    self.assertEqual(container_table.columns["state"].width, 12)
                    self.assertEqual(container_table.columns["status"].width, 20)
                    self.assertEqual(
                        app.query_one("#container-table-footer-rule").region.y,
                        app.query_one("#container-table").region.bottom,
                    )
                    self.assertEqual(
                        app.query_one("#container-url", WebLink).render().plain, ""
                    )
                    worktree = Worktree("feature", Path("/tmp/feature"))
                    web_container = Container("nginx")
                    web_container.ports = ["3200"]
                    worktree.containers[web_container.service] = web_container
                    worktree.git_status = {
                        "staged": 1,
                        "modified": 2,
                        "untracked": 0,
                        "ahead": 0,
                        "behind": 0,
                    }
                    app.selected_worktree = worktree
                    app._update_container_view()
                    await pilot.pause()
                    self.assertTrue(app.query_one("#container-loading", Static).display)
                    self.assertFalse(container_table.display)
                    worktree.has_polled = True
                    app._update_container_view()
                    self.assertFalse(app.query_one("#container-loading", Static).display)
                    self.assertTrue(container_table.display)
                    app._update_breadcrumb()
                    self.assertEqual(
                        app.query_one("#breadcrumb-worktree").render().plain, "feature"
                    )
                    self.assertEqual(
                        app.query_one("#container-url", WebLink).render().plain,
                        "localhost:3200",
                    )
                    self.assertEqual(
                        app.query_one("#breadcrumb-git-status", Static).render().plain,
                        "· +1 ~2 ",
                    )
                    self.assertEqual(
                        app.query_one("#btn-delete-worktree", Button).region.y,
                        app.query_one("#btn-container-start", Button).region.y,
                    )

                    await pilot.click("#breadcrumb-worktrees")
                    await pilot.pause()
                    self.assertEqual(switcher.current, "list-view")

        asyncio.run(exercise())
