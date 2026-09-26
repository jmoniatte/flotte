"""The Rich colors flotte bakes into its tables, taken from tui_kit's palette, and the status styles.

Everything else about themes lives in tui-kit.
"""
from dataclasses import dataclass
from typing import Union

from .models import WorktreeStatus
from .models.container import ContainerState


@dataclass(frozen=True)
class ThemeColors:
    """Color palette used by Rich renderables, mirroring the TCSS variables."""
    bg_light: str
    green: str
    red: str
    yellow: str
    orange: str
    blue: str
    purple: str
    cyan: str
    dim: str  # mapped from $comment


# Default colors (OneDark) used as fallback when app not available.
# Hardcoded for simplicity - only used in edge cases (pre-mount renders).
DEFAULT_COLORS = ThemeColors(
    bg_light="#3e4451",
    green="#98c379",
    red="#e06c75",
    yellow="#e5c07b",
    orange="#d19a66",
    blue="#61afef",
    purple="#c678dd",
    cyan="#56b6c2",
    dim="#545862",
)


def theme_colors(palette: dict[str, str]) -> ThemeColors:
    """Project a palette onto the subset Rich renderables need."""
    return ThemeColors(
        bg_light=palette["bg-light"],
        green=palette["green"],
        red=palette["red"],
        yellow=palette["yellow"],
        orange=palette["orange"],
        blue=palette["blue"],
        purple=palette["purple"],
        cyan=palette["cyan"],
        dim=palette["comment"],
    )


# =============================================================================
# Status style mappings - SINGLE SOURCE OF TRUTH for icons and colors
# =============================================================================

# WorktreeStatus: (icon, color_attr)
_WORKTREE_STYLES: dict[WorktreeStatus, tuple[str, str]] = {
    WorktreeStatus.RUNNING: ("●", "green"),
    WorktreeStatus.STARTING: ("◐", "green"),
    WorktreeStatus.STOPPING: ("◐", "orange"),
    WorktreeStatus.STOPPED: ("○", "red"),
    WorktreeStatus.UNKNOWN: ("?", "dim"),
}

_CONTAINER_STYLES: dict[ContainerState, tuple[str, str]] = {
    ContainerState.RUNNING: ("●", "green"),
    ContainerState.EXITED: ("○", "red"),
    ContainerState.PAUSED: ("◐", "yellow"),
    ContainerState.RESTARTING: ("◐", "yellow"),
    ContainerState.DEAD: ("✗", "red"),
    ContainerState.CREATED: ("○", "dim"),
    ContainerState.UNKNOWN: ("?", "dim"),
}


def get_status_style(
    status: Union[WorktreeStatus, ContainerState, str],
    colors: ThemeColors,
) -> tuple[str | None, str]:
    """Return (icon, color_hex) for any status enum.

    Args:
        status: WorktreeStatus or ContainerState
        colors: ThemeColors instance with hex color values

    Returns:
        Tuple of (icon_string_or_None, hex_color_string)
    """
    if isinstance(status, WorktreeStatus):
        icon, color_attr = _WORKTREE_STYLES.get(
            status, _WORKTREE_STYLES[WorktreeStatus.UNKNOWN]
        )
    elif isinstance(status, ContainerState):
        icon, color_attr = _CONTAINER_STYLES.get(
            status, _CONTAINER_STYLES[ContainerState.UNKNOWN]
        )
    else:
        # Fallback for unknown status types
        return ("?", colors.dim)

    return (icon, getattr(colors, color_attr))
