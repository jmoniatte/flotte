from functools import lru_cache

from rich.style import Style
from textual import events
from textual.widgets import DataTable
from textual.reactive import reactive
from rich.text import Text

from ..models import Worktree, Container, ContainerState
from ..theme import get_status_style


class ContainerTable(DataTable):
    """Table showing container status for selected worktree."""

    can_focus = False

    DEFAULT_CSS = """
    ContainerTable {
        height: auto;
        border: none;
        margin: 0;
    }
    """

    worktree: reactive[Worktree | None] = reactive(None, always_update=True)

    def on_mount(self) -> None:
        """Set up table columns and appearance."""
        self.cursor_foreground_priority = "renderable"
        self.cursor_type = "row"
        self.zebra_stripes = False

        # Define columns
        self.add_column("Service", key="service", width=15)
        self.add_column("Port", key="ports", width=10)
        self.add_column("State", key="state", width=12)
        self.add_column("Uptime", key="status", width=20)
        self.call_after_refresh(self._fit_columns)

    @lru_cache(maxsize=32)
    def _get_styles_to_render_cell(
        self,
        is_header_cell: bool,
        is_row_label_cell: bool,
        is_fixed_style_cell: bool,
        hover: bool,
        cursor: bool,
        show_cursor: bool,
        show_hover_cursor: bool,
        has_css_foreground_priority: bool,
        has_css_background_priority: bool,
    ) -> tuple[Style, Style]:
        """Let hover win over the passive cursor; mirrors Textual's 0.47 signature."""
        return super()._get_styles_to_render_cell(
            is_header_cell,
            is_row_label_cell,
            is_fixed_style_cell,
            hover,
            cursor and not hover,
            show_cursor,
            show_hover_cursor,
            has_css_foreground_priority,
            has_css_background_priority,
        )

    def on_resize(self, event: events.Resize) -> None:
        """Keep the compact service table stretched across its panel."""
        self._fit_columns()

    def _fit_columns(self) -> None:
        padding = self.cell_padding * 2 * len(self.columns)
        available = max(self.size.width - padding, 57)
        service = max(15, int(available * 0.40))
        ports = max(10, int(available * 0.15))
        state = max(12, int(available * 0.20))
        uptime = max(20, available - service - ports - state)

        self.columns["service"].width = service
        self.columns["ports"].width = ports
        self.columns["state"].width = state
        self.columns["status"].width = uptime

    def watch_worktree(self, worktree: Worktree | None) -> None:
        """React to worktree selection changes."""
        # Clear all existing rows
        self.clear()

        if worktree is None:
            return

        # Add rows for each container (container_list returns sorted list)
        for container in worktree.container_list:
            self._add_container_row(container)

        self.refresh()


    def _add_container_row(self, container: Container) -> None:
        """Add a row for a container."""
        self.add_row(
            container.service,
            ", ".join(container.ports) if container.ports else "-",
            self._format_state(container.state),
            container.status,
            key=container.service,
        )

    def _format_state(self, state: ContainerState) -> Text:
        """Format state with color coding."""
        _, color = get_status_style(state, self.app.theme_colors)
        return Text(state.value.title(), style=color)

    def update_container(self, container: Container) -> None:
        """
        Update a single container row by key.

        Use this for real-time updates during polling to avoid
        full table refresh.
        """
        try:
            # Get row index by key (service name)
            row_key = container.service

            # Update cells
            self.update_cell(row_key, "ports", ", ".join(container.ports) if container.ports else "-")
            self.update_cell(row_key, "state", self._format_state(container.state))
            self.update_cell(row_key, "status", container.status)
        except KeyError:
            # Container not in table, might need full refresh
            pass

    def sync_worktree(self, worktree: Worktree) -> None:
        """Synchronize displayed containers after a status poll."""
        displayed_services = {str(row_key.value) for row_key in self.rows}
        current_services = set(worktree.containers)
        if displayed_services != current_services:
            self.worktree = worktree
            return

        for container in worktree.container_list:
            self.update_container(container)

    def get_selected_container(self) -> Container | None:
        """Get the currently selected container, if any."""
        if self.cursor_row is None:
            return None

        try:
            row_key = self.get_row_at(self.cursor_row)
            # Find container by service name in current worktree
            if self.worktree:
                # containers is a dict keyed by service name
                return self.worktree.containers.get(row_key.value)
        except Exception:
            pass

        return None
