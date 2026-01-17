import webbrowser
from typing import Callable

from textual.containers import Vertical
from textual.widgets import DataTable
from textual.reactive import reactive
from textual.message import Message
from textual.events import Click
from rich.text import Text

from ..models import Worktree, WorktreeStatus


class WorktreeChanged(Message):
    """Posted when user selects a different worktree."""

    def __init__(self, worktree: Worktree) -> None:
        self.worktree = worktree
        super().__init__()


class WorktreeTable(DataTable):
    """DataTable for worktrees with status, name, URL, git status."""

    # Status icons and colors (OneDark theme - using hex to prevent cursor override)
    STATUS_ICONS = {
        WorktreeStatus.RUNNING: ("●", "#98c379"),      # Green filled
        WorktreeStatus.STARTING: ("◐", "#98c379"),     # Green half
        WorktreeStatus.STOPPING: ("◐", "#d19a66"),     # Orange half
        WorktreeStatus.STOPPED: ("○", "#e06c75"),      # Red outline
        WorktreeStatus.CREATING: ("◐", "#61afef"),     # Blue half
        WorktreeStatus.DELETING: ("◐", "#e06c75"),     # Red half
        WorktreeStatus.ERROR: ("✗", "#e06c75"),        # Red X
        WorktreeStatus.UNKNOWN: ("?", "#5c6370"),      # Dim
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._worktrees: list[Worktree] = []
        self._git_statuses: dict[str, dict] = {}
        self._status_fn: Callable[[str], WorktreeStatus] | None = None

    # Column positions (cumulative widths including borders)
    URL_COL_START = 3 + 20 + 2  # status + name + borders
    URL_COL_END = URL_COL_START + 25

    def on_mount(self) -> None:
        self.cursor_foreground_priority = "renderable"
        self.add_column("", key="status", width=3)
        self.add_column("Name", key="name", width=20)
        self.add_column("URL", key="url", width=25)
        self.add_column("Path", key="path", width=40)
        self.add_column("Git", key="git", width=20)
        self.cursor_type = "row"

    def on_click(self, event: Click) -> None:
        """Handle click - open URL if clicked on URL column."""
        # Check if click is in URL column range
        if not (self.URL_COL_START <= event.x < self.URL_COL_END):
            return

        # Get row from click position
        row_idx = event.y - 1  # Subtract 1 for header row
        if row_idx < 0 or row_idx >= len(self._worktrees):
            return

        wt = self._worktrees[row_idx]

        # Get effective status
        if self._status_fn is not None:
            status = self._status_fn(wt.name)
        else:
            status = wt.status

        # Only open if running
        if status == WorktreeStatus.RUNNING:
            url = f"http://localhost:{wt.port_config.nginx_port}"
            webbrowser.open(url)

    def _format_status(self, wt: Worktree) -> Text:
        """Format status icon for a worktree."""
        # Use status function if provided (consistent with StatusLine)
        # Otherwise fall back to wt.status for backwards compatibility
        if self._status_fn is not None:
            status = self._status_fn(wt.name)
        else:
            status = wt.status
        icon, color = self.STATUS_ICONS.get(
            status, self.STATUS_ICONS[WorktreeStatus.UNKNOWN]
        )
        return Text(icon, style=color)

    def _format_name(self, wt: Worktree) -> Text:
        return Text(wt.name, style="bold" if wt.is_main else "")

    def _format_url(self, wt: Worktree) -> Text:
        port = wt.port_config.nginx_port
        url = f"http://localhost:{port}"

        # Get effective status
        if self._status_fn is not None:
            status = self._status_fn(wt.name)
        else:
            status = wt.status

        # Cyan when running, greyed out otherwise
        if status == WorktreeStatus.RUNNING:
            return Text(url, style="cyan")
        else:
            return Text(url, style="dim")

    def _format_path(self, wt: Worktree) -> Text:
        from pathlib import Path
        home = str(Path.home())
        path_str = str(wt.path)
        if path_str.startswith(home):
            path_str = "~" + path_str[len(home):]
        return Text(path_str, style="dim")

    def _format_git(self, wt: Worktree) -> Text:
        git_status = self._git_statuses.get(wt.name)
        if not git_status:
            return Text("")

        text = Text()
        if git_status["staged"]:
            text.append(f"+{git_status['staged']} ", style="green")
        if git_status["modified"]:
            text.append(f"~{git_status['modified']} ", style="yellow")
        if git_status["untracked"]:
            text.append(f"?{git_status['untracked']} ", style="dim")
        if git_status["ahead"]:
            text.append(f"↑{git_status['ahead']} ", style="cyan")
        if git_status["behind"]:
            text.append(f"↓{git_status['behind']} ", style="red")

        if not text.plain:
            text = Text("clean", style="dim")

        return text

    def refresh_worktrees(
        self,
        worktrees: list[Worktree],
        status_fn: Callable[[str], WorktreeStatus] | None = None
    ) -> None:
        """Update table with worktrees.

        Args:
            worktrees: List of worktrees to display
            status_fn: Function to compute status for a worktree by name.
                       If None, falls back to wt.status (for backwards compatibility).
        """
        # Remember selection before updating list
        selected_name = None
        if self.cursor_row is not None and 0 <= self.cursor_row < len(self._worktrees):
            selected_name = self._worktrees[self.cursor_row].name

        self._worktrees = sorted(worktrees, key=lambda w: (not w.is_main, w.name))
        self._status_fn = status_fn
        self._rebuild_table(selected_name)

    def _rebuild_table(self, selected_name: str | None = None) -> None:
        """Rebuild the table rows."""
        self.clear()

        for wt in self._worktrees:
            self.add_row(
                self._format_status(wt),
                self._format_name(wt),
                self._format_url(wt),
                self._format_path(wt),
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
        # Remember selection before rebuilding
        selected_name = None
        if self.cursor_row is not None and 0 <= self.cursor_row < len(self._worktrees):
            selected_name = self._worktrees[self.cursor_row].name
        self._rebuild_table(selected_name)

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

    def refresh_worktrees(
        self,
        worktrees: list[Worktree],
        status_fn: Callable[[str], WorktreeStatus] | None = None
    ) -> None:
        """Update the table with worktrees.

        Args:
            worktrees: List of worktrees to display
            status_fn: Function to compute status for a worktree by name.
                       If None, falls back to wt.status (for backwards compatibility).
        """
        table = self.query_one("#worktree-table", WorktreeTable)
        table.refresh_worktrees(worktrees, status_fn)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (click/Enter)."""
        self._select_current_row()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle cursor movement (arrow keys)."""
        self._select_current_row()

    def _select_current_row(self) -> None:
        """Select the worktree at the current cursor position."""
        table = self.query_one("#worktree-table", WorktreeTable)
        wt = table.get_selected_worktree()
        if wt and wt != self.selected_worktree:
            self.selected_worktree = wt
            self.post_message(WorktreeChanged(wt))

    def select_worktree(self, worktree: Worktree) -> None:
        """Programmatically select a worktree."""
        self.selected_worktree = worktree
        table = self.query_one("#worktree-table", WorktreeTable)
        for i, wt in enumerate(table._worktrees):
            if wt.name == worktree.name:
                table.move_cursor(row=i)
                break

    def update_git_status(self, git_status: dict | None) -> None:
        """Update git status for selected worktree."""
        if self.selected_worktree and git_status:
            table = self.query_one("#worktree-table", WorktreeTable)
            table.update_git_status(self.selected_worktree.name, git_status)

    def clear(self) -> None:
        """Clear the display."""
        self.selected_worktree = None
