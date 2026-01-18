from enum import Enum
from textual.widgets import Static
from textual.reactive import reactive


class StepStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    ERROR = "error"


STEP_ICONS = {
    StepStatus.PENDING: "󰄱",  # nf-md-checkbox_blank_outline
    StepStatus.ACTIVE: "󰄵",   # nf-md-checkbox_intermediate
    StepStatus.DONE: "󰄲",     # nf-md-checkbox_marked
    StepStatus.ERROR: "󰅖",    # nf-md-close_box
}

STEP_COLORS = {
    StepStatus.PENDING: "dim",
    StepStatus.ACTIVE: "cyan",
    StepStatus.DONE: "green",
    StepStatus.ERROR: "red",
}


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
        lines = []
        if self.title:
            lines.append(f"[bold]{self.title}[/bold]")
            lines.append("")
        for name, status in self.steps:
            icon = STEP_ICONS[status]
            color = STEP_COLORS[status]
            lines.append(f"  [{color}]{icon}[/{color}] {name}")
        return "\n".join(lines) if lines else ""
