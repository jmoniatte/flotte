"""Centralized theme colors and status styling.

Single source of truth for:
- Theme color parsing from TCSS files
- Status icons and colors for WorktreeStatus and ContainerState
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
    bg_light: str
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
    bg_light="#3e4451",
    green="#98c379",
    red="#e06c75",
    yellow="#e5c07b",
    orange="#d19a66",
    blue="#61afef",
    purple="#c678dd",
    cyan="#56b6c2",
    dim="#5c6370",
)

REQUIRED_VARS = (
    "bg-light", "green", "red", "yellow", "orange", "blue", "purple", "cyan", "comment"
)


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
    for match in re.finditer(r'\$([\w-]+):\s*#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?', content):
        colors[match.group(1)] = f"#{match.group(2)}"

    # Validate required variables
    missing = [v for v in REQUIRED_VARS if v not in colors]
    if missing:
        raise ValueError(f"Theme '{theme_name}' missing required variables: {missing}")

    return ThemeColors(
        bg_light=colors["bg-light"],
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
