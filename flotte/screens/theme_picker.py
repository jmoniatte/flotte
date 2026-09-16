"""Theme picker: applies each theme as you move through the list."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from ..theme import list_themes, load_palette

# Order the swatch reads as a spectrum rather than in palette-variable order.
SWATCH_VARS = ("red", "orange", "yellow", "green", "cyan", "blue", "purple")


class ThemePicker(ModalScreen[str | None]):
    """Pick a base16 theme. Returns the chosen name, or None if cancelled."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
        ("up", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("pageup", "page_up", "Page up"),
        ("pagedown", "page_down", "Page down"),
    ]

    def __init__(self, current: str) -> None:
        super().__init__()
        self._current = current
        self._original = current
        self._names: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[bold]Theme[/bold]", id="dialog-title")
            yield Input(placeholder="Filter themes", id="theme-filter")
            yield DataTable(id="theme-table", cursor_type="row", show_header=False)
            yield Static(
                "Themes apply as you move. enter keeps one, esc restores "
                f"[bold]{self._original}[/bold].",
                id="theme-hint",
            )

    def on_mount(self) -> None:
        table = self.query_one("#theme-table", DataTable)
        table.add_column("name", key="name")
        table.add_column("swatch", key="swatch")
        self._populate("")
        self.query_one("#theme-filter", Input).focus()

    def _swatch(self, name: str) -> Text:
        palette = load_palette(name)
        swatch = Text()
        for var in SWATCH_VARS:
            swatch.append("█", style=palette[var])
        swatch.append(" ")
        swatch.append("Aa", style=f"{palette['fg']} on {palette['bg']}")
        return swatch

    def _populate(self, needle: str) -> None:
        """Rebuild the list, keeping the cursor on the active theme if shown."""
        table = self.query_one("#theme-table", DataTable)
        table.clear()
        self._names = [n for n in list_themes() if needle.lower() in n.lower()]
        for name in self._names:
            label = Text(name)
            if name == self._original:
                label = Text(f"{name} (current)")
            table.add_row(label, self._swatch(name), key=name)

        if not self._names:
            return
        target = self._current if self._current in self._names else self._names[0]
        table.move_cursor(row=self._names.index(target))

    def _apply(self, row: int) -> None:
        if not (0 <= row < len(self._names)):
            return
        self._current = self._names[row]
        self.app.apply_theme(self._current)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._populate(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Input claims enter before the screen binding sees it.
        event.stop()
        self.action_confirm()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self._apply(event.cursor_row)

    def _move(self, delta: int) -> None:
        table = self.query_one("#theme-table", DataTable)
        table.move_cursor(row=max(0, min(len(self._names) - 1, table.cursor_row + delta)))

    def action_cursor_up(self) -> None:
        self._move(-1)

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_page_up(self) -> None:
        self._move(-10)

    def action_page_down(self) -> None:
        self._move(10)

    def action_confirm(self) -> None:
        self.dismiss(self._current if self._names else None)

    def action_cancel(self) -> None:
        if self._current != self._original:
            self.app.apply_theme(self._original)
        self.dismiss(None)
