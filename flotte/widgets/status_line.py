from textual.containers import Horizontal
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Button, Static

from ..models.worktree import WorktreeStatus


class StatusLine(Horizontal):
    """Shows the Containers subtitle and worktree-level actions."""

    status: reactive[WorktreeStatus] = reactive(WorktreeStatus.UNKNOWN)
    git_status: reactive[dict | None] = reactive(None)

    def compose(self):
        yield Static("Containers", classes="containers-title")
        yield Static("", classes="containers-git-status")
        yield Static("", classes="spacer")
        delete_button = Button("Delete", id="btn-delete-worktree", variant="warning")
        delete_button.active_effect_duration = 0
        yield delete_button

    def watch_git_status(self, git_status: dict | None) -> None:
        self.query_one(".containers-git-status", Static).update(
            self._format_git_status(git_status)
        )

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
