import contextlib
import io
import asyncio
from datetime import datetime
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
import unittest

from flotte.__main__ import main
from flotte.app import FlotteApp, GREETING_TEMPLATES
from flotte.config import Config, LinkedRepository, PreflightResult, Project
from flotte.models import Container, GitStatus, LinkedWorktree, Worktree
from flotte.models.container import ContainerState
from flotte.screens import LogsScreen
from flotte.widgets import WebLink
from textual.widgets import Button, ContentSwitcher, RichLog, Static, TabbedContent


class MainTests(unittest.TestCase):
    def test_container_logs_load_recent_output_and_stop_when_hidden(self) -> None:
        async def exercise() -> None:
            config = Config(
                projects=[
                    Project(
                        "test",
                        "/tmp/test",
                        "/tmp/worktrees/{worktree}",
                        container_log_services=("rails", "mariadb"),
                    )
                ],
            )
            stream_closed = asyncio.Event()

            async def stream_logs(_manager, tail=200, services=()):
                self.assertEqual(tail, 200)
                self.assertEqual(services, ("rails", "mariadb"))
                try:
                    yield b"existing container output"
                    await asyncio.Future()
                finally:
                    stream_closed.set()

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
                patch(
                    "flotte.services.docker_manager.DockerManager.stream_logs",
                    stream_logs,
                ),
            ):
                app = FlotteApp()
                async with app.run_test() as pilot:
                    app.selected_worktree = Worktree(
                        "feature",
                        Path("/tmp/feature"),
                        compose_project_name="test-feature",
                    )
                    app.action_show_logs()
                    await pilot.pause()
                    tabs = app.screen.query_one("#logs-tabs", TabbedContent)
                    tabs.active = "containers"
                    await pilot.pause()

                    log = app.screen.query_one("#containers-log", RichLog)
                    self.assertEqual(len(log.lines), 1)
                    tabs.active = "flotte"
                    await pilot.pause()
                    self.assertTrue(stream_closed.is_set())

        asyncio.run(exercise())

    def test_unified_logs_follow_linked_process_output(self) -> None:
        async def exercise() -> None:
            config = Config(
                projects=[Project("test", "/tmp/test", "/tmp/worktrees/{worktree}")],
            )
            with tempfile.TemporaryDirectory() as directory:
                linked_path = Path(directory) / "frontend"
                linked_path.mkdir()
                log_path = Path(directory) / "frontend.log"
                log_path.write_text("ready\n")
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
                    async with app.run_test() as pilot:
                        worktree = Worktree("feature", Path(directory), "feature")
                        worktree.linked_worktrees = [
                            LinkedWorktree(
                                "frontend",
                                path=linked_path,
                                log_path=log_path,
                                process_pid=12345,
                            )
                        ]
                        app.selected_worktree = worktree

                        app.action_show_logs()
                        await pilot.pause()

                        self.assertIsInstance(app.screen, LogsScreen)
                        app.screen.query_one("#logs-tabs", TabbedContent).active = "linked-0"
                        await pilot.pause()
                        self.assertEqual(
                            app.screen.query_one("#log-breadcrumb-current", Static).render().plain,
                            "Logs · frontend · PID 12345",
                        )
                        log = app.screen.query_one("#linked-0-log", RichLog)
                        self.assertEqual(len(log.lines), 1)
                        with log_path.open("a") as log_file:
                            log_file.write("changed\n")
                        await pilot.pause(0.4)
                        self.assertEqual(len(log.lines), 2)
                        log_path.write_text("replacement\n")
                        await pilot.pause(0.4)
                        self.assertEqual(len(log.lines), 1)

        asyncio.run(exercise())

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
                patch("flotte.app.getuser", return_value="jean"),
                patch(
                    "flotte.app.choice", return_value="Bonjour {name}"
                ) as greeting_choice,
            ):
                app = FlotteApp()
                async with app.run_test(size=(100, 30), notifications=True) as pilot:
                    await pilot.pause()
                    notification = app.screen.query_one("HeaderNotification")
                    self.assertEqual(notification.render().plain, "Bonjour Jean")
                    self.assertEqual(len(GREETING_TEMPLATES), 20)
                    greeting_choice.assert_called_once_with(GREETING_TEMPLATES)

                    app.notify("First notification", timeout=30)
                    app.notify("Latest notification", timeout=30)
                    await pilot.pause()
                    notifications = list(app.screen.query("HeaderNotification"))
                    self.assertEqual(len(notifications), 1)
                    notification = notifications[0]
                    self.assertEqual(notification.render().plain, "Latest notification")
                    screenshot = app.export_screenshot()
                    self.assertIn("Latest&#160;notification", screenshot)
                    self.assertEqual(list(app.screen.query("Toast")), [])
                    self.assertGreaterEqual(
                        notification.region.x,
                        app.query_one("#app-title").region.right,
                    )
                    self.assertLessEqual(
                        notification.region.right,
                        app.query_one("#project-selector").region.x,
                    )
                    self.assertEqual(
                        notification.region.y,
                        app.query_one("#app-title").region.y,
                    )
                    left_gap = (
                        notification.region.x
                        - app.query_one("#app-title-group").region.right
                    )
                    right_gap = (
                        app.query_one("#project-selector").region.x
                        - notification.region.right
                    )
                    self.assertLessEqual(abs(left_gap - right_gap), 1)
                    self.assertGreater(
                        notification.content_region.width,
                        len("Latest notification"),
                    )

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
        valid = Project(
            "valid",
            "/tmp/valid",
            "/tmp/worktrees/{worktree}",
            linked_repositories=(
                LinkedRepository(
                    "/tmp/linked",
                    "/tmp/linked-worktrees/{worktree}",
                ),
            ),
        )
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
                    previous_project = app.project
                    app.selected_worktree = Worktree("selected", Path("/tmp/selected"))
                    self.assertIsNotNone(app.linked_repository_controller)

                    app.switch_project(invalid)

                    self.assertIs(app.current_config_project, invalid)
                    self.assertIsNot(app.project, previous_project)
                    self.assertIsNone(app.selected_worktree)
                    self.assertEqual(app.log_store.project_name, "invalid")
                    self.assertEqual(
                        app.worktree_manager.main_repo_path,
                        Path("/tmp/missing").resolve(),
                    )
                    self.assertIsNone(app.linked_repository_controller)
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
                        self.assertIsInstance(app.screen, LogsScreen)
                        app.pop_screen()
                        await pilot.pause()

                        app.log_store.record(
                            worktree.name, "Created worktree", 0.1, True
                        )
                        with app.log_store.path_for(worktree.name).open("a") as log_file:
                            log_file.write("malformed\n")
                        app._update_container_view()
                        logs_button = app.query_one("#btn-logs", Button)
                        self.assertFalse(logs_button.disabled)

                        app.action_show_logs()
                        await pilot.pause()
                        self.assertIsInstance(app.screen, LogsScreen)
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
                            f"DateTime {datetime.now().astimezone().tzname() or 'Local'}",
                        )
                        self.assertEqual(
                            app.screen.query_one("#worktree-log-label", Static).render().plain,
                            "Log",
                        )
                        log = app.screen.query_one("#flotte-log", RichLog)
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
