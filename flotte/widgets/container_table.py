from textual.reactive import reactive
from rich.align import Align
from rich.text import Text

from ..models import Worktree, Container, ContainerState
from ..theme import get_status_style
from .table_rules import DashedHeaderDataTable


class ContainerTable(DashedHeaderDataTable):
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
        super().on_mount()
        self.cursor_type = "none"
        self.zebra_stripes = False

        # Define columns
        self.add_column("", key="indicator", width=3)
        self.add_column("Container", key="service", width=20)
        self.add_column("Port", key="ports", width=10)
        self.add_column("State", key="state", width=12)
        self.add_column("Uptime", key="status", width=20)

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
            self._format_indicator(container.state),
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

    def _format_indicator(self, state: ContainerState) -> Align:
        """Format the compact status light shown before each service."""
        icon, color = get_status_style(state, self.app.theme_colors)
        return Align.center(Text(icon or "?", style=color))

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
            self.update_cell(row_key, "indicator", self._format_indicator(container.state))
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
