from textual.containers import Vertical
from textual import events, on
from textual.binding import Binding
from textual.widgets import DataTable
from textual.widgets._data_table import CellDoesNotExist
from textual.reactive import reactive
from textual.message import Message
from rich.align import Align
from rich.text import Text

from ..formatters import format_git_status, format_web_url
from ..models import Worktree, WorktreeStatus
from ..theme import get_status_style
from .table_rules import DashedHeaderDataTable, DashedTableFooter


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


class WorktreeTable(DashedHeaderDataTable):
    """DataTable for worktrees with status, name, URL, git status."""

    BINDINGS = DataTable.BINDINGS + [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._worktrees: list[Worktree] = []
        self._git_statuses: dict[str, dict] = {}
        self._hovered_url_worktree: str | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self.cursor_foreground_priority = "renderable"
        self.cursor_background_priority = "css"
        self.add_column("", key="status", width=3)
        self.add_column("Name", key="name", width=30)
        self.add_column("State", key="state", width=12)
        self.add_column("URL", key="url", width=50)
        self.add_column("Git", key="git", width=20)
        self.cursor_type = "row"
        self.call_after_refresh(self._fit_columns)

    @on(events.Leave)
    def on_pointer_left(self) -> None:
        """Restore the default URL styling after leaving the table."""
        self._set_hovered_url(None)

    @on(events.MouseMove)
    def on_pointer_moved(self, event: events.MouseMove) -> None:
        """Update only the URL text beneath the pointer."""
        row = event.style.meta.get("row")
        column = event.style.meta.get("column")
        url_column_index = self._url_column_index()
        is_data_row = isinstance(row, int) and 0 <= row < len(self._worktrees)
        if is_data_row and column != url_column_index:
            self.move_cursor(row=row)
        worktree_name = self._worktrees[row].name if is_data_row and column == url_column_index else None
        self._set_hovered_url(worktree_name)

    def _set_hovered_url(self, worktree_name: str | None) -> None:
        if worktree_name == self._hovered_url_worktree:
            return

        previous_name = self._hovered_url_worktree
        self._hovered_url_worktree = worktree_name
        for name in (previous_name, worktree_name):
            if name is None:
                continue
            worktree = next((item for item in self._worktrees if item.name == name), None)
            if worktree is not None:
                try:
                    self.update_cell(
                        name,
                        "url",
                        format_web_url(
                            worktree.web_url,
                            color=self.app.theme_colors.blue,
                            empty="-",
                            hovered=name == worktree_name,
                        ),
                    )
                except CellDoesNotExist:
                    pass

    def on_resize(self, event: events.Resize) -> None:
        """Keep the useful worktree columns balanced across the available width."""
        self._fit_columns()

    async def _on_click(self, event: events.Click) -> None:
        """Open a clicked data row independently of Textual's selection behavior."""
        await super()._on_click(event)

        row = event.style.meta.get("row")
        column = event.style.meta.get("column")
        if (
            isinstance(row, int)
            and 0 <= row < len(self._worktrees)
        ):
            worktree = self._worktrees[row]
            url_column_index = self._url_column_index()
            if column == url_column_index and worktree.web_url:
                self.app.open_url(worktree.web_url)
                return
            self.post_message(WorktreeOpened(worktree))

    def action_select_cursor(self) -> None:
        """Open the highlighted row when Enter is pressed."""
        worktree = self.get_selected_worktree()
        if worktree:
            self.post_message(WorktreeOpened(worktree))

    def _url_column_index(self) -> int:
        return next(
            index for index, key in enumerate(self.columns) if key.value == "url"
        )

    def _fit_columns(self) -> None:
        padding = self.cell_padding * 2 * len(self.columns)
        available = max(self.size.width - padding - 3, 81)
        name = max(28, int(available * 0.35))
        state = 12
        git = max(12, int(available * 0.15))
        url = max(25, available - name - state - git)

        self.columns["name"].width = name
        self.columns["state"].width = state
        self.columns["url"].width = url
        self.columns["git"].width = git

    @staticmethod
    def _display_status(wt: Worktree):
        return wt.status if wt.has_polled else WorktreeStatus.UNKNOWN

    def _format_status(self, wt: Worktree) -> Align:
        """Format status icon for a worktree."""
        icon, color = get_status_style(self._display_status(wt), self.app.theme_colors)
        return Align.center(Text(icon, style=color))

    def _format_state(self, wt: Worktree) -> Text:
        status = self._display_status(wt)
        _, color = get_status_style(status, self.app.theme_colors)
        return Text("Loading" if not wt.has_polled else status.value.title(), style=color)

    def _format_name(self, wt: Worktree) -> Text:
        return Text(wt.name, style="bold" if wt.is_main else "")

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
                self._format_state(wt),
                format_web_url(
                    wt.web_url,
                    color=self.app.theme_colors.blue,
                    empty="-",
                    hovered=wt.name == self._hovered_url_worktree,
                ),
                format_git_status(self._git_statuses.get(wt.name), self.app.theme_colors),
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
                self.update_cell(
                    worktree_name,
                    "git",
                    format_git_status(
                        self._git_statuses.get(worktree.name), self.app.theme_colors
                    ),
                )
            except CellDoesNotExist:
                pass

    def update_worktree_status(self, worktree: Worktree) -> None:
        """Update one status cell without rebuilding the worktree table."""
        try:
            self.update_cell(worktree.name, "status", self._format_status(worktree))
            self.update_cell(worktree.name, "state", self._format_state(worktree))
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

    def compose(self):
        yield WorktreeTable(id="worktree-table")
        yield DashedTableFooter(id="worktree-table-footer-rule")

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
                table.focus()
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
