import contextlib
import io
import asyncio
import threading
from datetime import datetime
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import unittest

from flotte.__main__ import main
from flotte.app import (
    FlotteApp,
    GREETING_TEMPLATES,
    RESTART_OPERATION,
    START_OPERATION,
)
from flotte.config import Config, LinkedRepository, PreflightResult, Project
from flotte.models import Container, GitStatus, LinkedWorktree, Worktree
from flotte.models.container import ContainerState
from flotte.models.worktree import WorktreeStatus
from flotte.services.docker_manager import DockerManager
from flotte.screens import HelpScreen, LogsScreen
from flotte.screens.create_worktree import CreateWorktreeScreen
from flotte.widgets import AppHeader, WebLink, WorktreeHeader
from flotte.widgets.worktree_header import WorktreeTable
from flotte import shortcuts
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    DataTable,
    RichLog,
    Static,
    TabbedContent,
    Tabs,
)


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
                        # Both screens mount the same header widget
                        self.assertIsInstance(
                            app.screen.query_one("#app-header"), AppHeader
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

    @staticmethod
    def _single_project_config() -> Config:
        return Config(
            projects=[Project("test", "/tmp/test", "/tmp/worktrees/{worktree}")]
        )

    def _patched_app(self, config: Config):
        return (
            patch("flotte.app.load_config", return_value=config),
            patch(
                "flotte.app.preflight_config",
                return_value=PreflightResult(
                    tuple(config.projects), ((config.projects[0], ()),)
                ),
            ),
            patch.object(FlotteApp, "refresh_worktrees", new_callable=AsyncMock),
            patch.object(FlotteApp, "_fetch_git_status", new_callable=AsyncMock),
            patch("flotte.models.project.Project.start_polling"),
            patch("flotte.models.project.Project.shutdown", new_callable=AsyncMock),
        )

    def test_an_operation_locks_only_its_own_worktree(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                app = FlotteApp()
                async with app.run_test() as pilot:
                    first = Worktree("feature", Path("/tmp/feature"))
                    second = Worktree("bugfix", Path("/tmp/bugfix"))
                    app.project.worktrees.update({wt.name: wt for wt in (first, second)})
                    app.selected_worktree = first
                    await pilot.pause()

                    self.assertTrue(app._acquire_operation_lock("start", first.name))
                    self.assertTrue(app._acquire_operation_lock("start", second.name))
                    self.assertFalse(app._acquire_operation_lock("stop", first.name))
                    self.assertTrue(app._is_worktree_busy(first.name))
                    self.assertTrue(app.query_one("#btn-ride", Button).disabled)

                    # Controls follow the selected worktree, not the busiest one
                    app.selected_worktree = second
                    app._release_operation_lock(second.name)
                    self.assertFalse(app.query_one("#btn-ride", Button).disabled)
                    self.assertFalse(app._is_worktree_busy(second.name))
                    self.assertTrue(app._is_worktree_busy(first.name))
                    self.assertTrue(app._is_any_operation_running())

                    app._release_operation_lock(first.name)
                    app._release_operation_lock(first.name)  # idempotent
                    self.assertFalse(app._is_any_operation_running())

        asyncio.run(exercise())

    def test_list_git_statuses_are_read_concurrently(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                app = FlotteApp()
                async with app.run_test() as pilot:
                    worktrees = [
                        Worktree(f"wt-{index}", Path(f"/tmp/wt-{index}"))
                        for index in range(3)
                    ]
                    app.project.worktrees.update({wt.name: wt for wt in worktrees})
                    app.query_one("#worktree-header", WorktreeHeader).refresh_worktrees(
                        worktrees
                    )
                    await pilot.pause()

                    in_flight = 0
                    peak = 0
                    all_started = asyncio.Event()

                    async def fake_git_status(path: Path) -> GitStatus:
                        nonlocal in_flight, peak
                        in_flight += 1
                        peak = max(peak, in_flight)
                        if in_flight == len(worktrees):
                            all_started.set()
                        # A serial fetch never releases this, so the wait times out
                        await all_started.wait()
                        in_flight -= 1
                        return GitStatus(staged=1)

                    with patch("flotte.app.get_git_status", new=fake_git_status):
                        await asyncio.wait_for(
                            app._fetch_list_git_statuses(), timeout=10
                        )

                    self.assertEqual(peak, len(worktrees))
                    self.assertEqual(
                        [wt.git_status for wt in worktrees],
                        [GitStatus(staged=1)] * len(worktrees),
                    )

        asyncio.run(exercise())

    def test_help_screen_documents_every_binding(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                app = FlotteApp()
                async with app.run_test(size=(100, 34)) as pilot:
                    await pilot.pause()
                    await pilot.press("?")
                    await pilot.pause()
                    self.assertIsInstance(app.screen, HelpScreen)

                    documented = {}
                    for row in app.screen.query(".shortcut-row"):
                        key, description = row.query(Static)
                        documented[key.render().plain] = description
                    self.assertEqual(
                        [title.render().plain for title in app.screen.query(".section-title")],
                        ["ACTIONS", "GENERAL"],
                    )

                    # Focus movement is the only deliberately undocumented binding
                    table_extras = WorktreeTable.BINDINGS[len(DataTable.BINDINGS):]
                    for binding in list(FlotteApp.BINDINGS) + list(table_extras):
                        if binding.key in ("tab", "shift+tab"):
                            self.assertNotIn(binding.key, documented)
                            continue
                        key = binding.key_display or binding.key
                        self.assertIn(key, documented, key)
                        self.assertEqual(
                            documented[key].render().plain, binding.description, key
                        )
                        # A longer description than the column would be clipped
                        self.assertLessEqual(
                            len(binding.description),
                            documented[key].region.width,
                            key,
                        )

                    self.assertEqual(documented["o"].render().plain, "Open web URL")
                    self.assertIn("j", documented)
                    self.assertEqual(shortcuts.SECTIONS, ("Actions", "General"))

        asyncio.run(exercise())

    def test_config_warnings_reach_the_no_config_screen(self) -> None:
        async def exercise() -> None:
            config = Config(warnings=["Project entry 1: not a mapping. Skipped."])
            with (
                patch("flotte.app.load_config", return_value=config),
                patch(
                    "flotte.app.preflight_config",
                    return_value=PreflightResult((), ()),
                ),
            ):
                app = FlotteApp()
                async with app.run_test():
                    self.assertEqual(
                        app.query_one("#no-config-warnings", Static).render().plain,
                        "Project entry 1: not a mapping. Skipped.",
                    )

        asyncio.run(exercise())

    def test_config_warnings_show_beside_a_loaded_project(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            config.warnings = ["First problem.", "Second problem."]
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                app = FlotteApp()
                async with app.run_test(size=(100, 30), notifications=True) as pilot:
                    await pilot.pause()
                    self.assertEqual(
                        app.query_one("#config-warnings", Static).render().plain,
                        "First problem.\nSecond problem.",
                    )
                    # The warning takes the greeting's place in the header
                    self.assertEqual(
                        app.screen.query_one("HeaderNotification").render().plain,
                        "2 problems in your config file",
                    )

        asyncio.run(exercise())

    def test_a_clean_config_greets_and_shows_no_warning_panel(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                stack.enter_context(
                    patch("flotte.app.choice", return_value="Bonjour {name}")
                )
                stack.enter_context(patch("flotte.app.getuser", return_value="jean"))
                app = FlotteApp()
                async with app.run_test(size=(100, 30), notifications=True) as pilot:
                    await pilot.pause()
                    self.assertEqual(list(app.query("#config-warnings")), [])
                    self.assertEqual(
                        app.screen.query_one("HeaderNotification").render().plain,
                        "Bonjour Jean",
                    )

        asyncio.run(exercise())

    def test_preflight_runs_after_the_first_paint(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            running = threading.Event()
            release = threading.Event()

            def slow_preflight(loaded: Config) -> PreflightResult:
                running.set()
                release.wait(10)
                return PreflightResult(
                    tuple(loaded.projects), ((loaded.projects[0], ("docker is down",)),)
                )

            with (
                patch("flotte.app.load_config", return_value=config),
                patch("flotte.app.preflight_config", new=slow_preflight),
                patch.object(FlotteApp, "refresh_worktrees", new_callable=AsyncMock),
                patch("flotte.models.project.Project.start_polling"),
                patch(
                    "flotte.models.project.Project.shutdown", new_callable=AsyncMock
                ),
            ):
                app = FlotteApp()
                self.assertFalse(running.is_set())  # __init__ must not run it
                async with app.run_test(size=(100, 30)) as pilot:
                    await pilot.pause()
                    self.assertTrue(running.wait(5))

                    # The window is usable while preflight is still out
                    problems = app.query_one("#project-problems", Static)
                    self.assertTrue(app.query_one("#worktrees-box").display)
                    self.assertFalse(problems.display)
                    self.assertTrue(app.query_one("#btn-new-worktree", Button).display)

                    release.set()
                    for _ in range(100):
                        await pilot.pause()
                        if problems.display:
                            break
                        await asyncio.sleep(0.05)

                    self.assertEqual(problems.render().plain, "docker is down")
                    self.assertFalse(app.query_one("#worktrees-box").display)
                    self.assertFalse(app.query_one("#btn-new-worktree", Button).display)

        asyncio.run(exercise())

    async def _run_operation(self, app, pilot, operation, results):
        """Drive one compose operation with canned docker results."""
        calls: list[str] = []

        async def fake_command(name: str):
            calls.append(name)
            return results[name]

        wt = Worktree("feature", Path("/tmp/feature"))
        app.project.worktrees[wt.name] = wt
        app.selected_worktree = wt
        app.log_store = Mock()
        await pilot.pause()

        with (
            patch.object(
                DockerManager, "start", lambda self: fake_command("start")
            ),
            patch.object(DockerManager, "stop", lambda self: fake_command("stop")),
        ):
            app._run_compose_operation(operation)
            for _ in range(100):
                await pilot.pause()
                if not app._is_worktree_busy(wt.name):
                    break
                await asyncio.sleep(0.02)

        return wt, calls

    def test_restart_runs_stop_then_start_and_logs_once(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                app = FlotteApp()
                async with app.run_test() as pilot:
                    wt, calls = await self._run_operation(
                        app,
                        pilot,
                        RESTART_OPERATION,
                        {"stop": (0, "", ""), "start": (0, "", "")},
                    )

                    self.assertEqual(calls, ["stop", "start"])
                    self.assertFalse(app._is_worktree_busy(wt.name))
                    # Polling still has to confirm the worktree came up
                    self.assertEqual(wt.status, WorktreeStatus.STARTING)
                    app.log_store.record_elapsed.assert_called_once()
                    name, action, _, succeeded = (
                        app.log_store.record_elapsed.call_args.args
                    )
                    self.assertEqual((name, action, succeeded), (wt.name, "Restarted containers", True))

        asyncio.run(exercise())

    def test_a_failed_phase_stops_the_operation(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                app = FlotteApp()
                async with app.run_test(notifications=True) as pilot:
                    wt, calls = await self._run_operation(
                        app,
                        pilot,
                        RESTART_OPERATION,
                        {"stop": (1, "", "no such project"), "start": (0, "", "")},
                    )

                    self.assertEqual(calls, ["stop"])  # start never runs
                    self.assertFalse(app._is_worktree_busy(wt.name))
                    self.assertIsNone(wt.clear_operation())  # already cleared
                    self.assertEqual(
                        app.screen.query_one("HeaderNotification").render().plain,
                        "Failed to restart: no such project",
                    )
                    _, action, _, succeeded = (
                        app.log_store.record_elapsed.call_args.args
                    )
                    self.assertEqual((action, succeeded), ("Restarted containers", False))

        asyncio.run(exercise())

    def test_start_uses_one_phase_and_releases_the_lock(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                app = FlotteApp()
                async with app.run_test() as pilot:
                    wt, calls = await self._run_operation(
                        app, pilot, START_OPERATION, {"start": (0, "", "")}
                    )

                    self.assertEqual(calls, ["start"])
                    self.assertEqual(wt.status, WorktreeStatus.STARTING)
                    self.assertFalse(app._is_any_operation_running())
                    _, action, _, succeeded = (
                        app.log_store.record_elapsed.call_args.args
                    )
                    self.assertEqual((action, succeeded), ("Started containers", True))

        asyncio.run(exercise())

    def test_wrap_checkbox_rewraps_the_log_and_is_remembered(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with tempfile.TemporaryDirectory() as directory:
                with contextlib.ExitStack() as stack:
                    for patcher in self._patched_app(config):
                        stack.enter_context(patcher)
                    stack.enter_context(
                        patch("flotte.services.worktree_log.LOG_DIR", Path(directory))
                    )
                    app = FlotteApp()
                    async with app.run_test(size=(80, 30)) as pilot:
                        worktree = Worktree("feature", Path("/tmp/feature"))
                        app.selected_worktree = worktree
                        app.log_store.record(worktree.name, "x" * 300, 0.1, True)

                        app.action_show_logs()
                        await pilot.pause()
                        log = app.screen.query_one("#flotte-log", RichLog)
                        wrap_box = app.screen.query_one("#wrap-logs", Checkbox)

                        # The tabs keep the focus even though the box comes first
                        self.assertIsInstance(app.focused, Tabs)
                        self.assertFalse(wrap_box.value)
                        self.assertFalse(any(item.wrap for item in app.screen.query(RichLog)))
                        unwrapped = len(log.lines)

                        await pilot.click("#wrap-logs")
                        await pilot.pause()
                        await asyncio.sleep(0.2)

                        self.assertTrue(all(item.wrap for item in app.screen.query(RichLog)))
                        self.assertTrue(app.wrap_logs)
                        self._assert_checkbox_states_differ(wrap_box)

                        # Neither hover nor focus restyles the label
                        app.screen.query_one(Tabs).focus()
                        await pilot.pause()
                        resting = self._label_style(wrap_box)

                        await pilot.hover("#wrap-logs")
                        await pilot.pause()
                        self.assertEqual(self._label_style(wrap_box), resting)

                        wrap_box.focus()
                        await pilot.pause()
                        self.assertEqual(self._label_style(wrap_box), resting)
                        # The already-written line was re-rendered, not left alone
                        self.assertGreater(len(log.lines), unwrapped)

                        app.pop_screen()
                        await pilot.pause()
                        app.action_show_logs()
                        await pilot.pause()
                        self.assertTrue(app.screen.query_one("#wrap-logs", Checkbox).value)
                        self.assertTrue(app.screen.query_one("#flotte-log", RichLog).wrap)

        asyncio.run(exercise())

    def _assert_checkbox_states_differ(self, box: Checkbox) -> None:
        """The slot reports the state on its own, and the label never moves."""
        self.assertTrue(box.value)
        on_button = box.get_component_styles("toggle--button")
        on_slot = (on_button.color, on_button.background)
        on_label = self._label_style(box)
        # A filled slot when on: the mark contrasts with the slot behind it
        self.assertNotEqual(on_button.color, on_button.background)

        box.value = False
        off_button = box.get_component_styles("toggle--button")
        off_slot = (off_button.color, off_button.background)
        # An empty slot when off: the mark is hidden against the slot
        self.assertEqual(off_button.color, off_button.background)
        self.assertNotEqual(on_slot, off_slot)
        # Label colour means disabled elsewhere, so it is not a state channel
        self.assertEqual(self._label_style(box), on_label)
        box.value = True

    @staticmethod
    def _label_style(wrap_box: Checkbox) -> tuple:
        label = wrap_box.get_component_styles("toggle--label")
        return (label.color, label.background, label.text_style)

    def test_the_clone_checkbox_reads_the_same_way_as_the_wrap_one(self) -> None:
        async def exercise() -> None:
            config = self._single_project_config()
            with contextlib.ExitStack() as stack:
                for patcher in self._patched_app(config):
                    stack.enter_context(patcher)
                stack.enter_context(
                    patch.object(
                        CreateWorktreeScreen, "_load_branches", new_callable=AsyncMock
                    )
                )
                app = FlotteApp()
                async with app.run_test(size=(80, 30)) as pilot:
                    await pilot.pause()
                    app.action_new_worktree()
                    await pilot.pause()

                    clone_box = app.screen.query_one("#clone-data", Checkbox)
                    self.assertTrue(clone_box.value)
                    self._assert_checkbox_states_differ(clone_box)

                    # Neither focus nor hover restyles the label
                    app.screen.query_one("#branch-input").focus()
                    await pilot.pause()
                    resting = self._label_style(clone_box)

                    await pilot.hover("#clone-data")
                    await pilot.pause()
                    self.assertEqual(self._label_style(clone_box), resting)

                    clone_box.focus()
                    await pilot.pause()
                    self.assertEqual(self._label_style(clone_box), resting)

        asyncio.run(exercise())
