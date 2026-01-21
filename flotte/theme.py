"""Centralized theme colors and status styling.

Single source of truth for:
- Theme color parsing from TCSS files
- Status icons and colors for WorktreeStatus, ContainerState, StepStatus
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from .models import WorktreeStatus
from .models.container import ContainerState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThemeColors:
    """Color palette parsed from a TCSS theme file."""
    green: str
    red: str
    yellow: str
    orange: str
    blue: str
    purple: str  # future-proofing
    cyan: str
    dim: str  # mapped from $comment


# Default colors (OneDark) used as fallback when app not available.
# Hardcoded for simplicity - only used in edge cases (pre-mount renders).
DEFAULT_COLORS = ThemeColors(
    green="#98c379",
    red="#e06c75",
    yellow="#e5c07b",
    orange="#d19a66",
    blue="#61afef",
    purple="#c678dd",
    cyan="#56b6c2",
    dim="#5c6370",
)

REQUIRED_VARS = ("green", "red", "yellow", "orange", "blue", "purple", "cyan", "comment")


def load_theme_colors(theme_name: str) -> ThemeColors:
    """Parse TCSS file and extract color variables.

    Args:
        theme_name: Name of theme (matches filename without .tcss)

    Returns:
        ThemeColors with parsed hex values

    Raises:
        ValueError: If required variables are missing from theme file
    """
    styles_dir = Path(__file__).parent / "styles" / "themes"
    theme_path = styles_dir / f"{theme_name}.tcss"

    if not theme_path.exists():
        logger.warning(f"Theme '{theme_name}' not found, falling back to 'onedark'")
        theme_path = styles_dir / "onedark.tcss"

    content = theme_path.read_text(encoding="utf-8")

    # Parse $var: #hex; patterns (supports 6 or 8 digit hex, ignores alpha)
    colors = {}
    for match in re.finditer(r'\$(\w+):\s*#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?', content):
        colors[match.group(1)] = f"#{match.group(2)}"

    # Validate required variables
    missing = [v for v in REQUIRED_VARS if v not in colors]
    if missing:
        raise ValueError(f"Theme '{theme_name}' missing required variables: {missing}")

    return ThemeColors(
        green=colors["green"],
        red=colors["red"],
        yellow=colors["yellow"],
        orange=colors["orange"],
        blue=colors["blue"],
        purple=colors["purple"],
        cyan=colors["cyan"],
        dim=colors["comment"],
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
    WorktreeStatus.CREATING: ("◐", "blue"),
    WorktreeStatus.DELETING: ("◐", "red"),
    WorktreeStatus.ERROR: ("✗", "red"),
    WorktreeStatus.UNKNOWN: ("?", "dim"),
}

# ContainerState: (None, color_attr) - no icons, color only
_CONTAINER_STYLES: dict[ContainerState, tuple[None, str]] = {
    ContainerState.RUNNING: (None, "green"),
    ContainerState.EXITED: (None, "red"),
    ContainerState.PAUSED: (None, "yellow"),
    ContainerState.RESTARTING: (None, "yellow"),
    ContainerState.DEAD: (None, "red"),
    ContainerState.CREATED: (None, "dim"),
    ContainerState.UNKNOWN: (None, "dim"),
}

# StepStatus: (icon, color_attr) - uses string keys to avoid circular import
_STEP_STYLES: dict[str, tuple[str, str]] = {
    "pending": ("󰄱", "dim"),    # nf-md-checkbox_blank_outline
    "active": ("󰄵", "cyan"),    # nf-md-checkbox_intermediate
    "done": ("󰄲", "green"),     # nf-md-checkbox_marked
    "error": ("󰅖", "red"),      # nf-md-close_box
}

# Status text for status_line.py (text only, icons come from _WORKTREE_STYLES)
WORKTREE_STATUS_TEXT: dict[WorktreeStatus, str] = {
    WorktreeStatus.RUNNING: "Services running",
    WorktreeStatus.STARTING: "Services starting...",
    WorktreeStatus.STOPPING: "Services stopping...",
    WorktreeStatus.STOPPED: "Services stopped",
    WorktreeStatus.CREATING: "Services creating...",
    WorktreeStatus.DELETING: "Services deleting...",
    WorktreeStatus.ERROR: "Error",
    WorktreeStatus.UNKNOWN: "Unknown",
}


def get_status_style(
    status: Union[WorktreeStatus, ContainerState, str],
    colors: ThemeColors,
) -> tuple[str | None, str]:
    """Return (icon, color_hex) for any status enum.

    Args:
        status: WorktreeStatus, ContainerState, or StepStatus.value string
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
    elif isinstance(status, str) and status in _STEP_STYLES:
        # StepStatus passed as .value string
        icon, color_attr = _STEP_STYLES[status]
    else:
        # Fallback for unknown status types
        return ("?", colors.dim)

    return (icon, getattr(colors, color_attr))
