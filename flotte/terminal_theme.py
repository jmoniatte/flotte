"""Read the terminal's own colours through xterm OSC queries.

OSC 10 and 11 report the default foreground and background and OSC 4 one
palette entry each. base16-shell writes the six slots ANSI has no place for
into entries 16-21, so those are read too and used when the terminal set them.
The query happens before Textual starts, since its driver then owns the tty.
"""

import os
import re
import select
import sys
import time
from dataclasses import dataclass

from .theme import MIN_TEXT_CONTRAST, Rgb, contrast_ratio, hex_color, luminance, shift

try:
    import termios
    import tty
except ImportError:  # not a POSIX tty; the caller falls back to a scheme file
    termios = None
    tty = None

QUERY_TIMEOUT = 0.25

_ANSI_SLOTS = {
    1: "base08",
    2: "base0B",
    3: "base0A",
    4: "base0D",
    5: "base0E",
    6: "base0C",
    8: "base03",
    15: "base07",
}
_EXTENDED_SLOTS = {
    16: "base09",
    17: "base0F",
    18: "base01",
    19: "base02",
    20: "base04",
    21: "base06",
}
# What entries 16-21 hold on a terminal nobody customised: the start of the
# 6x6x6 colour cube. Reporting those means the slots carry no scheme.
_CUBE_DEFAULTS = {
    16: (0, 0, 0),
    17: (0, 0, 95),
    18: (0, 0, 135),
    19: (0, 0, 175),
    20: (0, 0, 215),
    21: (0, 0, 255),
}
# Comment text has to sit between the background and the foreground; a bright
# black left at pure black on a dark background is on the wrong side.
_MIN_COMMENT_CONTRAST = 1.3
# How far the raised and selection surfaces stand off the background, as WCAG
# contrast. base16 authors land here in both light and dark schemes (onedark
# 1.24 and 1.43, one-light 1.09 and 1.21), whereas a fixed RGB step lands
# twice as far on a light ramp, where the greys are spread wider.
_RAISED_CONTRAST = 1.15
_SELECTION_CONTRAST = 1.35

# DA1 goes last: every terminal answers it, even one that ignores OSC, so its
# reply marks the end of whatever colour replies are coming.
_QUERY = (
    "\x1b]11;?\x07\x1b]10;?\x07"
    + "".join(f"\x1b]4;{index};?\x07" for index in range(22))
    + "\x1b[c"
)
_DA1_REPLY = re.compile(rb"\x1b\[\?[\d;]*c")
_COLOR_REPLY = re.compile(
    rb"\x1b\](1[01]|4;\d+);rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)"
)

TerminalColors = dict[str | int, Rgb]


@dataclass(frozen=True)
class TerminalReport:
    """What the terminal said: a usable scheme, and which way its background leans."""

    scheme: dict[str, Rgb] | None = None
    light_background: bool | None = None


def _channel(text: bytes) -> int:
    # xterm scales each channel to however many hex digits it prints (1 to 4).
    return round(int(text, 16) * 255 / (16 ** len(text) - 1))


def parse_replies(data: bytes) -> TerminalColors:
    """Extract 'fg', 'bg' and numbered palette entries from raw terminal replies."""
    colors: TerminalColors = {}
    for match in _COLOR_REPLY.finditer(data):
        code = match.group(1).decode()
        rgb = (_channel(match.group(2)), _channel(match.group(3)), _channel(match.group(4)))
        if code == "10":
            colors["fg"] = rgb
        elif code == "11":
            colors["bg"] = rgb
        else:
            colors[int(code[2:])] = rgb
    return colors


def scheme_from_terminal(colors: TerminalColors) -> dict[str, Rgb] | None:
    """Fill the 16 base16 slots, or None when the terminal reported too little."""
    if any(key not in colors for key in ("bg", "fg", 1, 2, 3, 4, 5, 6)):
        return None
    bg, fg = colors["bg"], colors["fg"]
    if contrast_ratio(hex_color(fg), hex_color(bg)) < MIN_TEXT_CONTRAST:
        return None

    scheme = {"base00": bg, "base05": fg}
    for index, slot in _ANSI_SLOTS.items():
        if index in colors:
            scheme[slot] = colors[index]
    for index, slot in _EXTENDED_SLOTS.items():
        if index in colors and colors[index] != _CUBE_DEFAULTS[index]:
            scheme[slot] = colors[index]

    if not _reads_as_comment(scheme.get("base03"), bg, fg):
        scheme["base03"] = shift(bg, fg, 0.4)
    scheme.setdefault("base07", fg)
    scheme.setdefault("base01", _toward_contrast(bg, fg, _RAISED_CONTRAST))
    scheme.setdefault("base02", _toward_contrast(bg, fg, _SELECTION_CONTRAST))
    scheme.setdefault("base04", shift(scheme["base03"], fg, 0.5))
    scheme.setdefault("base06", shift(fg, scheme["base07"], 0.5))
    scheme.setdefault("base09", shift(scheme["base08"], scheme["base0A"], 0.5))
    scheme.setdefault("base0F", shift(scheme["base08"], bg, 0.3))
    return scheme


def _toward_contrast(origin: Rgb, toward: Rgb, target: float) -> Rgb:
    """The point on the line from `origin` where contrast against it reaches `target`."""
    low, high = 0.0, 1.0
    for _ in range(16):
        middle = (low + high) / 2
        if contrast_ratio(hex_color(shift(origin, toward, middle)), hex_color(origin)) < target:
            low = middle
        else:
            high = middle
    return shift(origin, toward, high)


def light_background(colors: TerminalColors) -> bool | None:
    """Whether the background is the lighter end; None when the terminal did not say."""
    if "bg" not in colors:
        return None
    if "fg" in colors:
        return luminance(colors["bg"]) > luminance(colors["fg"])
    return luminance(colors["bg"]) > 0.5


def report_from_terminal(colors: TerminalColors) -> TerminalReport:
    return TerminalReport(scheme_from_terminal(colors), light_background(colors))


def _reads_as_comment(color: Rgb | None, bg: Rgb, fg: Rgb) -> bool:
    if color is None or contrast_ratio(hex_color(color), hex_color(bg)) < _MIN_COMMENT_CONTRAST:
        return False
    return (luminance(color) - luminance(bg)) * (luminance(fg) - luminance(bg)) > 0


def _read_until(fd: int, end: re.Pattern[bytes], timeout: float) -> bytes:
    data = b""
    deadline = time.monotonic() + timeout
    while not end.search(data):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            break
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        data += chunk
    return data


def query_terminal(timeout: float = QUERY_TIMEOUT, stdin=None, stdout=None) -> TerminalReport:
    """Ask the terminal for its colours; an empty report when it is not one or stays silent."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if termios is None:
        return TerminalReport()
    try:
        if not (stdin.isatty() and stdout.isatty()):
            return TerminalReport()
        fd = stdin.fileno()
        saved = termios.tcgetattr(fd)
    except (AttributeError, OSError, ValueError, termios.error):
        return TerminalReport()
    try:
        tty.setcbreak(fd)
        stdout.write(_QUERY)
        stdout.flush()
        data = _read_until(fd, _DA1_REPLY, timeout)
    except OSError:
        return TerminalReport()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return report_from_terminal(parse_replies(data))
