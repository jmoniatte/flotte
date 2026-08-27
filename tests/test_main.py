import contextlib
import io
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import unittest

from flotte.__main__ import main
from flotte.app import FlotteApp
from flotte.config import Config, PreflightResult, Project
from flotte.models import Container, GitStatus, Worktree
from flotte.models.container import ContainerState
from flotte.screens import WorktreeLogScreen
from flotte.widgets import WebLink
from textual.widgets import Button, ContentSwitcher, RichLog, Static


class MainTests(unittest.TestCase):
    def test_no_config_screen_uses_yaml_guidance(self) -> None:
        async def exercise() -> None:
            config = Config()
            with (
                patch("flotte.app.load_config", return_value=config),
                patch(
                    "flotte.app.preflight_config",
                    return_value=PreflightResult((), ()),
                ),
            ):
                app = FlotteApp()
                async with app.run_test():
                    help_text = app.query_one("#no-config-help", Static).render().plain
                    self.assertIn("projects:", help_text)
                    self.assertNotIn("[[projects]]", help_text)
                    self.assertIn("worktree_path", help_text)

        asyncio.run(exercise())

    def test_link_lifecycle_logs_the_process_id_and_failures(self) -> None:
        async def exercise() -> None:
            app = Mock()
            app.linked_worktree_manager.start_link = AsyncMock(
                return_value=Mock(pid=12345)
            )
            app.linked_worktree_manager.stop_link = AsyncMock(
                side_effect=RuntimeError("stop failed")
            )
            worktree = Worktree("feature", Path("/tmp/feature"))

            await FlotteApp._run_link_lifecycle(
                app,
                worktree,
                "rwgps-ui",
                "start",
            )
            action = app.log_store.record_elapsed.call_args.args
            self.assertEqual(action[0], "feature")
            self.assertEqual(action[1], "Started rwgps-ui (PID: 12345)")
            self.assertTrue(action[3])

            app.log_store.record_elapsed.reset_mock()
            await FlotteApp._run_link_lifecycle(
                app,
                worktree,
                "rwgps-ui",
                "stop",
            )
            action = app.log_store.record_elapsed.call_args.args
            self.assertEqual(action[0], "feature")
            self.assertEqual(action[1], "Stopped rwgps-ui")
            self.assertFalse(action[3])

        asyncio.run(exercise())

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
                patch(
                    "flotte.app.preflight_config",
                    return_value=PreflightResult(
                        tuple(config.projects), ((config.projects[0], ()),)
                    ),
                ),
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
                    self.assertEqual(container_table.columns["indicator"].width, 3)
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
                    web_container.state = ContainerState.EXITED
                    web_container.ports = ["3200"]
                    worktree.containers[web_container.service] = web_container
                    worktree.git_status = GitStatus(staged=1, unstaged=2)
                    app.selected_worktree = worktree
                    app._update_container_view()
                    await pilot.pause()
                    self.assertTrue(app.query_one("#container-loading", Static).display)
                    self.assertFalse(container_table.display)
                    worktree.has_polled = True
                    app._update_container_view()
                    await pilot.pause()
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

    def test_preflight_problems_follow_the_selected_project(self) -> None:
        valid = Project("valid", "/tmp/valid", "/tmp/worktrees/{worktree}")
        invalid = Project("invalid", "/tmp/missing", "/tmp/worktrees/{worktree}")
        config = Config(projects=[valid, invalid])
        problem = "invalid: repository does not exist: /tmp/missing"
        async def exercise() -> None:
            with (
                patch("flotte.app.load_config", return_value=config),
                patch(
                    "flotte.app.preflight_config",
                    return_value=PreflightResult(
                        tuple(config.projects), ((valid, ()), (invalid, (problem,)))
                    ),
                ),
                patch.object(FlotteApp, "refresh_worktrees", new_callable=AsyncMock),
                patch("flotte.models.project.Project.start_polling"),
                patch("flotte.models.project.Project.shutdown", new_callable=AsyncMock),
            ):
                app = FlotteApp()
                async with app.run_test():
                    self.assertFalse(app.query_one("#project-problems", Static).display)
                    app.switch_project(invalid)
                    self.assertEqual(
                        app.query_one("#project-problems", Static).render().plain,
                        problem,
                    )
                    self.assertTrue(app.query_one("#project-problems", Static).display)
                    self.assertFalse(app.query_one("#worktrees-box").display)
                    self.assertFalse(app.query_one("#btn-new-worktree", Button).display)
                    self.assertFalse(app.query_one("#btn-refresh", Button).display)
                    self.assertTrue(app.query_one("#btn-new-worktree", Button).disabled)

        asyncio.run(exercise())

    def test_logs_button_opens_the_selected_worktree_log(self) -> None:
        async def exercise() -> None:
            config = Config(
                projects=[Project("test", "/tmp/test", "/tmp/worktrees/{worktree}")]
            )
            with tempfile.TemporaryDirectory() as directory:
                with (
                    patch("flotte.app.load_config", return_value=config),
                    patch(
                        "flotte.app.preflight_config",
                        return_value=PreflightResult(
                            tuple(config.projects), ((config.projects[0], ()),)
                        ),
                    ),
                    patch("flotte.services.worktree_log.LOG_DIR", Path(directory)),
                    patch.object(FlotteApp, "refresh_worktrees", new_callable=AsyncMock),
                    patch.object(FlotteApp, "_fetch_git_status", new_callable=AsyncMock),
                    patch("flotte.models.project.Project.start_polling"),
                    patch("flotte.models.project.Project.shutdown", new_callable=AsyncMock),
                ):
                    app = FlotteApp()
                    async with app.run_test() as pilot:
                        worktree = Worktree("feature", Path("/tmp/feature"))
                        app.selected_worktree = worktree
                        self.assertFalse(app.query_one("#btn-logs", Button).disabled)
                        app.action_show_logs()
                        await pilot.pause()
                        self.assertIsInstance(app.screen, WorktreeLogScreen)
                        app.pop_screen()
                        await pilot.pause()

                        app.log_store.record(
                            worktree.name, "Create worktree", 0.1, True
                        )
                        with app.log_store.path_for(worktree.name).open("a") as log_file:
                            log_file.write("malformed\n")
                        app._update_container_view()
                        logs_button = app.query_one("#btn-logs", Button)
                        self.assertFalse(logs_button.disabled)

                        app.action_show_logs()
                        await pilot.pause()
                        self.assertIsInstance(app.screen, WorktreeLogScreen)
                        self.assertIn(
                            "Logs",
                            app.screen.query_one("#log-breadcrumb-current", Static).render().plain,
                        )
                        self.assertEqual(
                            app.screen.query_one("#project-name", Static).render().plain,
                            "test",
                        )
                        self.assertEqual(
                            app.screen.query_one("#worktree-log-datetime", Static).render().plain,
                            "DateTime",
                        )
                        self.assertEqual(
                            app.screen.query_one("#worktree-log-label", Static).render().plain,
                            "Log",
                        )
                        log = app.screen.query_one("#worktree-log", RichLog)
                        self.assertEqual(len(log.lines), 2)
                        await pilot.click("#log-breadcrumb-worktree")
                        await pilot.pause()
                        self.assertEqual(
                            app.query_one("#view-switcher", ContentSwitcher).current,
                            "details-view",
                        )

                        app.action_show_logs()
                        await pilot.pause()
                        await pilot.click("#log-breadcrumb-worktrees")
                        await pilot.pause()
                        self.assertEqual(
                            app.query_one("#view-switcher", ContentSwitcher).current,
                            "list-view",
                        )

        asyncio.run(exercise())
