from textual.widgets import DataTable
from textual.reactive import reactive
from rich.text import Text

from ..models import Worktree, Container, ContainerState
from ..theme import get_status_style


class ContainerTable(DataTable):
    """Table showing container status for selected worktree."""

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
        self.cursor_type = "none"
        self.zebra_stripes = True

        # Define columns
        self.add_column("Service", key="service", width=15)
        self.add_column("Port", key="ports", width=10)
        self.add_column("State", key="state", width=12)
        self.add_column("Status", key="status", width=20)
        self.add_column("Container Name", key="name", width=50)

    def watch_worktree(self, worktree: Worktree | None) -> None:
        """React to worktree selection changes."""
        # Clear all existing rows
        self.clear()

        if worktree is None:
            return

        # Add rows for each container (container_list returns sorted list)
        for container in worktree.container_list:
            self._add_container_row(container)

        # Force refresh to ensure display updates
        self.refresh()

    def _add_container_row(self, container: Container) -> None:
        """Add a row for a container."""
        self.add_row(
            container.service,
            ", ".join(container.ports) if container.ports else "-",
            self._format_state(container.state),
            container.status,
            self._truncate(container.name, 50),
            key=container.service,
        )

    def _format_state(self, state: ContainerState) -> Text:
        """Format state with color coding."""
        _, color = get_status_style(state, self.app.theme_colors)
        return Text(state.value, style=color)

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

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
            self.update_cell(row_key, "state", self._format_state(container.state))
            self.update_cell(row_key, "status", container.status)
        except KeyError:
            # Container not in table, might need full refresh
            pass

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
