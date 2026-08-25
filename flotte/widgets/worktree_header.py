from textual.containers import Vertical
from textual import events
from textual.widgets import DataTable
from textual.widgets._data_table import CellDoesNotExist
from textual.reactive import reactive
from textual.message import Message
from rich.style import Style
from rich.text import Text

from ..models import Worktree
from ..theme import get_status_style


class WorktreeChanged(Message):
    """Posted when user selects a different worktree."""

    def __init__(self, worktree: Worktree) -> None:
        self.worktree = worktree
        super().__init__()


class WorktreeOpened(Message):
    """Posted when the user activates a worktree row."""

    def __init__(self, worktree: Worktree) -> None:
        self.worktree = worktree
        super().__init__()


class WorktreeTable(DataTable):
    """DataTable for worktrees with status, name, URL, git status."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._worktrees: list[Worktree] = []
        self._git_statuses: dict[str, dict] = {}

    def on_mount(self) -> None:
        self.cursor_foreground_priority = "renderable"
        self.add_column("", key="status", width=3)
        self.add_column("Name", key="name", width=30)
        self.add_column("URL", key="url", width=50)
        self.add_column("Git", key="git", width=20)
        self.cursor_type = "row"
        self.call_after_refresh(self._fit_columns)

    def on_resize(self, event: events.Resize) -> None:
        """Keep the useful worktree columns balanced across the available width."""
        self._fit_columns()

    async def _on_click(self, event: events.Click) -> None:
        """Open a clicked data row independently of Textual's selection behavior."""
        await super()._on_click(event)

        row = event.style.meta.get("row")
        if (
            isinstance(row, int)
            and 0 <= row < len(self._worktrees)
        ):
            self.post_message(WorktreeOpened(self._worktrees[row]))

    def action_select_cursor(self) -> None:
        """Open the highlighted row when Enter is pressed."""
        worktree = self.get_selected_worktree()
        if worktree:
            self.post_message(WorktreeOpened(worktree))

    def _fit_columns(self) -> None:
        padding = self.cell_padding * 2 * len(self.columns)
        available = max(self.size.width - padding - 3, 69)
        name = max(28, int(available * 0.40))
        git = max(12, int(available * 0.15))
        url = max(30, available - name - git)

        self.columns["name"].width = name
        self.columns["url"].width = url
        self.columns["git"].width = git

    def _format_status(self, wt: Worktree) -> Text:
        """Format status icon for a worktree."""
        icon, color = get_status_style(wt.status, self.app.theme_colors)
        return Text(icon, style=color)

    def _format_name(self, wt: Worktree) -> Text:
        return Text(wt.name, style="bold" if wt.is_main else "")

    def _format_url(self, wt: Worktree) -> Text:
        """Format URL for a worktree."""
        url = wt.web_url
        if url:
            text = Text(self._display_url(url), style="cyan underline")
            text.stylize(Style(meta={"@click": f"app.open_url({url!r})"}))
            return text
        return Text("-", style="dim")

    @staticmethod
    def _display_url(url: str) -> str:
        return url.removeprefix("http://").removeprefix("https://")

    def _format_git(self, wt: Worktree) -> Text:
        git_status = self._git_statuses.get(wt.name)
        if not git_status:
            return Text("")

        colors = self.app.theme_colors
        text = Text()
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

        if not text.plain:
            text = Text("clean", style=colors.dim)

        return text

    def refresh_worktrees(self, worktrees: list[Worktree]) -> None:
        """Update table with worktrees.

        Args:
            worktrees: List of worktrees to display
        """
        # Remember selection before updating list
        selected_name = None
        if self.cursor_row is not None and 0 <= self.cursor_row < len(self._worktrees):
            selected_name = self._worktrees[self.cursor_row].name

        self._worktrees = sorted(worktrees, key=lambda w: (not w.is_main, w.name))
        self._rebuild_table(selected_name)

    def _rebuild_table(self, selected_name: str | None = None) -> None:
        """Rebuild the table rows."""
        self.clear()

        for wt in self._worktrees:
            self.add_row(
                self._format_status(wt),
                self._format_name(wt),
                self._format_url(wt),
                self._format_git(wt),
                key=wt.name,
            )

        # Restore selection
        if selected_name:
            for i, wt in enumerate(self._worktrees):
                if wt.name == selected_name:
                    self.move_cursor(row=i)
                    break

    def update_git_status(self, worktree_name: str, git_status: dict) -> None:
        """Update git status for a worktree."""
        self._git_statuses[worktree_name] = git_status
        worktree = next((item for item in self._worktrees if item.name == worktree_name), None)
        if worktree is not None:
            try:
                self.update_cell(worktree_name, "git", self._format_git(worktree))
            except CellDoesNotExist:
                pass

    def update_worktree_status(self, worktree: Worktree) -> None:
        """Update one status cell without rebuilding the worktree table."""
        try:
            self.update_cell(worktree.name, "status", self._format_status(worktree))
        except CellDoesNotExist:
            pass

    def get_selected_worktree(self) -> Worktree | None:
        """Get currently selected worktree."""
        if self.cursor_row is not None and self.cursor_row < len(self._worktrees):
            return self._worktrees[self.cursor_row]
        return None


class WorktreeHeader(Vertical):
    """Header showing worktree table."""

    selected_worktree: reactive[Worktree | None] = reactive(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def compose(self):
        yield WorktreeTable(id="worktree-table")

    def refresh_worktrees(self, worktrees: list[Worktree]) -> None:
        """Update the table with worktrees.

        Args:
            worktrees: List of worktrees to display
        """
        table = self.query_one("#worktree-table", WorktreeTable)
        table.refresh_worktrees(worktrees)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle cursor movement (arrow keys)."""
        self._select_current_row()

    def _select_current_row(self, *, notify: bool = True) -> Worktree | None:
        """Select the worktree at the current cursor position."""
        table = self.query_one("#worktree-table", WorktreeTable)
        wt = table.get_selected_worktree()
        if wt:
            self.selected_worktree = wt
            if notify:
                self.post_message(WorktreeChanged(wt))
        return wt

    def select_worktree(self, worktree: Worktree) -> None:
        """Programmatically select a worktree."""
        self.selected_worktree = worktree
        table = self.query_one("#worktree-table", WorktreeTable)
        for i, wt in enumerate(table._worktrees):
            if wt.name == worktree.name:
                table.move_cursor(row=i)
                break

    def update_git_status(self, worktree_name: str, git_status: dict | None) -> None:
        """Update git status for one worktree."""
        if git_status:
            table = self.query_one("#worktree-table", WorktreeTable)
            table.update_git_status(worktree_name, git_status)

    def update_worktree_status(self, worktree: Worktree) -> None:
        self.query_one("#worktree-table", WorktreeTable).update_worktree_status(worktree)

    def clear(self) -> None:
        """Clear the display."""
        self.selected_worktree = None
