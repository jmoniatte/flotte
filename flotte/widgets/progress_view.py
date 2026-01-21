from enum import Enum
from textual.widgets import Static
from textual.reactive import reactive

from ..theme import get_status_style, DEFAULT_COLORS


class StepStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    ERROR = "error"


class ProgressView(Static):
    """Shows operation progress with title and step checklist."""

    title: reactive[str] = reactive("")
    steps: reactive[tuple[tuple[str, StepStatus], ...]] = reactive(())

    def set_operation(self, title: str, step_names: list[str]) -> None:
        """Initialize operation with title and steps."""
        self.title = title
        self.steps = tuple((name, StepStatus.PENDING) for name in step_names)

    def start(self) -> None:
        """Mark first step as ACTIVE."""
        if self.steps:
            steps = list(self.steps)
            steps[0] = (steps[0][0], StepStatus.ACTIVE)
            self.steps = tuple(steps)

    def advance_step(self, index: int) -> None:
        """Mark step as DONE and next step (if any) as ACTIVE."""
        steps = list(self.steps)
        if index < len(steps):
            steps[index] = (steps[index][0], StepStatus.DONE)
        if index + 1 < len(steps):
            steps[index + 1] = (steps[index + 1][0], StepStatus.ACTIVE)
        self.steps = tuple(steps)

    def mark_error(self, index: int) -> None:
        """Mark current step as ERROR."""
        steps = list(self.steps)
        if index < len(steps):
            steps[index] = (steps[index][0], StepStatus.ERROR)
        self.steps = tuple(steps)

    def clear(self) -> None:
        """Clear the progress view."""
        self.title = ""
        self.steps = ()

    def render(self) -> str:
        # Guard: app may not be available during early renders
        if hasattr(self, 'app') and self.app:
            colors = self.app.theme_colors
        else:
            colors = DEFAULT_COLORS

        lines = []
        if self.title:
            lines.append(f"[bold]{self.title}[/bold]")
            lines.append("")
        for name, status in self.steps:
            icon, color = get_status_style(status.value, colors)
            lines.append(f"  [{color}]{icon}[/{color}] {name}")
        return "\n".join(lines) if lines else ""
