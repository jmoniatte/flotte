"""Controls and status for linked worktrees."""

from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static
from rich.style import Style
from rich.text import Text

from ..models import LinkedWorktree, Worktree


def available_actions(linked: LinkedWorktree, worktree: Worktree) -> frozenset[str]:
    """Return the lifecycle actions currently permitted for a linked repository."""
    actions: set[str] = set()
    can_manage = not worktree.is_main
    needs_link = linked.path is None or linked.state == "error"
    can_control = linked.path is not None and linked.can_start and linked.process_status != "external"

    if can_manage and needs_link:
        actions.add("link")
    if can_control and linked.process_status == "stopped":
        actions.add("start")
    if can_control and linked.process_status == "running":
        actions.update(("stop", "restart"))
    if can_manage and linked.path is not None:
        actions.add("unlink")
    return frozenset(actions)


class LinkedRepositoryAction(Message):
    """Request a lifecycle action for one linked repository."""

    def __init__(self, repository_name: str, action: str) -> None:
        self.repository_name = repository_name
        self.action = action
        super().__init__()


class LinkedRepositoryRow(Vertical):
    """Persistent controls and state for one linked repository."""

    def __init__(self, repository_name: str, index: int):
        super().__init__(classes="linked-repository-row")
        self.repository_name = repository_name
        self.index = index

    def compose(self):
        with Horizontal(classes="linked-repository-heading"):
            yield Static(self.repository_name, classes="linked-repository-title")
            yield Static("", classes="linked-repository-git-status")
        with Horizontal(classes="linked-repository-details"):
            with Horizontal(classes="linked-repository-lifecycle"):
                yield Button("Link", id=f"linked-link-{self.index}")
                yield Button("Start", id=f"linked-start-{self.index}", classes="linked-start-button")
                yield Button("Stop", id=f"linked-stop-{self.index}", classes="linked-stop-button", variant="error")
                yield Button("Restart", id=f"linked-restart-{self.index}", classes="linked-restart-button")
            yield Static("", classes="linked-repository-url")
            unlink_button = Button(
                "Unlink",
                id=f"linked-unlink-{self.index}",
                classes="linked-unlink-button",
                variant="error",
            )
            unlink_button.active_effect_duration = 0
            yield unlink_button

    def update_worktree(self, linked: LinkedWorktree, worktree: Worktree) -> None:
        link_button = self.query_one(f"#linked-link-{self.index}", Button)
        start_button = self.query_one(f"#linked-start-{self.index}", Button)
        stop_button = self.query_one(f"#linked-stop-{self.index}", Button)
        restart_button = self.query_one(f"#linked-restart-{self.index}", Button)
        unlink_button = self.query_one(f"#linked-unlink-{self.index}", Button)
        url_widget = self.query_one(".linked-repository-url", Static)
        git_widget = self.query_one(".linked-repository-git-status", Static)

        actions = available_actions(linked, worktree)
        link_button.display = "link" in actions
        link_button.label = "Retry Link" if linked.state == "error" else "Link"
        can_control = bool(actions & {"start", "stop", "restart"})
        start_button.display = can_control
        stop_button.display = can_control
        restart_button.display = can_control
        start_button.disabled = linked.process_status != "stopped"
        stop_button.disabled = linked.process_status != "running"
        restart_button.disabled = linked.process_status != "running"
        unlink_button.display = "unlink" in actions

        url = (
            self._open_url(worktree, linked.open_url_path)
            if linked.process_status == "running"
            else None
        )
        if url:
            url_text = Text(self._display_url(url), style=Style(color=self.app.theme_colors.blue, underline=True))
            url_text.stylize(Style(meta={"@click": f"app.open_url({url!r})"}))
            url_widget.update(url_text)
        else:
            url_widget.update("")
        git_widget.update(self._format_git_status(linked.git_status))

    @staticmethod
    def _open_url(worktree: Worktree, path: str) -> str | None:
        if not path or not worktree.web_url:
            return None
        return f"{worktree.web_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _display_url(url: str) -> str:
        return url.removeprefix("http://").removeprefix("https://")

    def _format_git_status(self, git_status: dict | None) -> Text:
        if git_status is None:
            return Text("")

        colors = self.app.theme_colors
        text = Text("· ", style=colors.dim)
        if git_status["staged"]:
            text.append(f"+{git_status['staged']} ", style=colors.green)
        if git_status["modified"]:
            text.append(f"~{git_status['modified']} ", style=colors.yellow)
        if git_status["untracked"]:
            text.append(f"?{git_status['untracked']} ", style=colors.dim)
        if git_status["ahead"]:
            text.append(f"↑{git_status['ahead']} ", style=colors.cyan)
        if git_status["behind"]:
            text.append(f"↓{git_status['behind']} ", style=colors.red)
        return text if text.plain != "· " else Text("· clean", style=colors.dim)


class LinkedRepositories(Vertical):
    """Linked-repository rows, rebuilt only if configured repositories change."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._repository_names: tuple[str, ...] = ()
        self._worktree: Worktree | None = None

    async def show_worktree(self, worktree: Worktree | None) -> None:
        linked_worktrees = worktree.linked_worktrees if worktree else []
        repository_names = tuple(linked.repository_name for linked in linked_worktrees)
        if repository_names != self._repository_names:
            await self.remove_children()
            self._repository_names = repository_names
            if repository_names:
                for index, repository_name in enumerate(repository_names):
                    await self.mount(LinkedRepositoryRow(repository_name, index))
        self.update_worktree(worktree)

    def update_worktree(self, worktree: Worktree | None) -> bool:
        linked_worktrees = worktree.linked_worktrees if worktree else []
        if tuple(linked.repository_name for linked in linked_worktrees) != self._repository_names:
            return False

        self._worktree = worktree
        self.display = bool(linked_worktrees)
        if worktree is None:
            return True

        rows = list(self.query(LinkedRepositoryRow))
        for index, linked in enumerate(linked_worktrees):
            rows[index].update_worktree(linked, worktree)
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        prefix, separator, index_value = button_id.rpartition("-")
        if not separator or not prefix.startswith("linked-"):
            return
        try:
            index = int(index_value)
        except ValueError:
            return
        action = prefix.removeprefix("linked-")
        worktree = self._worktree
        if worktree is None or index < 0 or index >= len(worktree.linked_worktrees):
            return
        linked = worktree.linked_worktrees[index]
        if action in available_actions(linked, worktree):
            self.post_message(LinkedRepositoryAction(linked.repository_name, action))
