from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.strip import Strip
from textual.widgets import DataTable, Static


class DashedHeaderDataTable(DataTable):
    """Data table with a dashed rule beneath its header."""

    def on_mount(self) -> None:
        self.header_height = 2

    def render_line(self, y: int) -> Strip:
        if self.show_header and y == self.header_height - 1:
            return Strip(
                [
                    Segment(
                        "-" * self.size.width,
                        Style(color=self.app.theme_colors.dim),
                    )
                ]
            )
        return super().render_line(y)


class DashedTableFooter(Static):
    """A dashed rule that tracks its table's rendered width."""

    def on_mount(self) -> None:
        self.call_after_refresh(self._update_rule)

    def on_resize(self, event: events.Resize) -> None:
        self._update_rule()

    def _update_rule(self) -> None:
        if self.size.width:
            self.update("-" * self.size.width)
