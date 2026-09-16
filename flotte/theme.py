"""Centralized theme colors and status styling.

Themes are base16 scheme files (github.com/tinted-theming/schemes) used
unmodified. base16 defines 16 slots; `base.tcss` needs 13 variables, 11 of
which map straight onto a slot. The remaining two -- a recessed surface and a
border colour -- are derived from the scheme's own greyscale ramp so that no
theme needs hand-picked values.

Single source of truth for:
- base16 scheme loading and the slot -> TCSS variable mapping
- Status icons and colors for WorktreeStatus and ContainerState
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Union

import yaml

from .models import WorktreeStatus
from .models.container import ContainerState

logger = logging.getLogger(__name__)

THEMES_DIR = Path(__file__).parent / "styles" / "themes"
DEFAULT_THEME = "onedark"
# Not a scheme file: the palette the terminal itself reports, when it does.
TERMINAL_THEME = "terminal"

BASE16_SLOTS = tuple(f"base{index:02X}" for index in range(16))

# base16 slots that map directly onto a TCSS variable. `bg-dark` and `gutter`
# have no slot and are derived; see _derive_bg_dark and _derive_gutter.
SLOT_VARS = {
    "base00": "bg",
    "base02": "bg-light",
    "base03": "comment",
    "base05": "fg",
    "base08": "red",
    "base09": "orange",
    "base0A": "yellow",
    "base0B": "green",
    "base0C": "cyan",
    "base0D": "blue",
    "base0E": "purple",
}

Rgb = tuple[int, int, int]

# Registered by __main__ once the terminal has answered; None until then.
_terminal_scheme: dict[str, Rgb] | None = None

# A derived surface this close to the background reads as no surface at all.
_MIN_SURFACE_DELTA = 3
# Fraction of a ramp step between base00 and base01; reproduces the hand-picked
# OneDark value (#21252b) to within two units per channel.
_BG_DARK_STEP = 0.5
# WCAG AA for body text. Schemes whose own $fg on $bg falls below this are not
# installed; see scripts/sync_themes.py.
MIN_TEXT_CONTRAST = 4.5


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


def _rgb(value: object) -> Rgb:
    """Parse a base16 hex value, with or without a leading '#'."""
    # An all-digit slot such as 001122 arrives from YAML as an int.
    text = str(value).strip().lstrip("#").zfill(6)
    if len(text) != 6:
        raise ValueError(f"Invalid base16 color: {value!r}")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def hex_color(rgb: Rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def luminance(rgb: Rgb) -> float:
    def channel(value: int) -> float:
        srgb = value / 255
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio between two hex colors, from 1.0 to 21.0."""
    lighter, darker = sorted((luminance(_rgb(first)), luminance(_rgb(second))))
    return (darker + 0.05) / (lighter + 0.05)


def shift(origin: Rgb, toward: Rgb, amount: float) -> Rgb:
    """Move `origin` along the line to `toward`; a negative amount overshoots back."""
    return tuple(
        max(0, min(255, round(o + (t - o) * amount))) for o, t in zip(origin, toward)
    )


def _derive_bg_dark(base00: Rgb, base01: Rgb) -> Rgb:
    """A surface recessed from the background.

    Whenever base01 is already the darker of the two -- every light scheme, and
    dark schemes that spend the slot on a recessed surface rather than a raised
    one -- it is the recessed surface the author chose, so use it. Otherwise
    base16 offers nothing below base00 and the step has to be extrapolated.
    """
    if luminance(base01) < luminance(base00):
        return base01

    shifted = shift(base00, base01, -_BG_DARK_STEP)
    if max(abs(a - b) for a, b in zip(shifted, base00)) < _MIN_SURFACE_DELTA:
        return base01  # base00 sits at the end of the ramp; nothing below it
    return shifted


def _derive_gutter(base02: Rgb, base03: Rgb) -> Rgb:
    """Borders and rules sit between the selection background and comments."""
    return shift(base02, base03, 0.5)


@lru_cache(maxsize=None)
def read_scheme(path: Path) -> dict[str, Rgb]:
    """Parse a base16 scheme file into its 16 slots.

    Accepts both the 0.11 spec (colors nested under `palette`) and the older
    flat layout.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    palette = data.get("palette", data)
    missing = [slot for slot in BASE16_SLOTS if slot not in palette]
    if missing:
        raise ValueError(f"Scheme '{path.name}' missing base16 slots: {missing}")
    return {slot: _rgb(palette[slot]) for slot in BASE16_SLOTS}


def register_terminal_scheme(scheme: dict[str, Rgb] | None) -> None:
    """Make the terminal's reported palette selectable, or drop it with None."""
    global _terminal_scheme
    _terminal_scheme = scheme


def is_known_theme(theme_name: str) -> bool:
    """Whether a config value names a theme at all, installed or not yet read."""
    return theme_name == TERMINAL_THEME or (THEMES_DIR / f"{theme_name}.yaml").exists()


def resolve_theme(theme_name: str) -> str | None:
    """Theme name usable right now, or None if not installed or not reported.

    Scheme names are the upstream base16 slugs verbatim, so for those this is
    just an existence check. The terminal theme exists only once the terminal
    has answered the colour query.
    """
    if theme_name == TERMINAL_THEME:
        return TERMINAL_THEME if _terminal_scheme else None
    return theme_name if (THEMES_DIR / f"{theme_name}.yaml").exists() else None


def effective_theme(theme_name: str) -> str:
    """The theme actually shown for a configured name, after any fallback."""
    return resolve_theme(theme_name) or DEFAULT_THEME


def load_palette(theme_name: str) -> dict[str, str]:
    """Return the TCSS variables for a theme, keyed without the leading '$'."""
    resolved = resolve_theme(theme_name)
    if resolved is None:
        # The terminal staying silent is expected; a missing scheme file is not.
        if theme_name != TERMINAL_THEME:
            logger.warning(
                f"Theme '{theme_name}' not found, falling back to '{DEFAULT_THEME}'"
            )
        resolved = DEFAULT_THEME

    if resolved == TERMINAL_THEME:
        scheme = _terminal_scheme
    else:
        scheme = read_scheme(THEMES_DIR / f"{resolved}.yaml")
    return palette_from_scheme(scheme)


def palette_from_scheme(scheme: dict[str, Rgb]) -> dict[str, str]:
    """Map 16 base16 slots onto the TCSS variables, deriving the two extras."""
    palette = {var: hex_color(scheme[slot]) for slot, var in SLOT_VARS.items()}
    palette["bg-dark"] = hex_color(_derive_bg_dark(scheme["base00"], scheme["base01"]))
    palette["gutter"] = hex_color(_derive_gutter(scheme["base02"], scheme["base03"]))
    return palette


def palette_to_tcss(palette: dict[str, str]) -> str:
    """Render a palette as the TCSS variable block `base.tcss` expects."""
    return "\n".join(f"${var}: {value};" for var, value in sorted(palette.items()))


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


def load_theme_colors(theme_name: str) -> ThemeColors:
    """Load a theme and return its Rich-side colors."""
    return theme_colors(load_palette(theme_name))


def list_themes() -> list[str]:
    """Names of every installed scheme file."""
    return sorted(path.stem for path in THEMES_DIR.glob("*.yaml"))


def selectable_themes() -> list[str]:
    """What the pickers offer: the terminal first, when it answered, then the files."""
    names = list_themes()
    return [TERMINAL_THEME, *names] if _terminal_scheme else names


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
