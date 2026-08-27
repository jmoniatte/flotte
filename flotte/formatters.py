from rich.text import Text

from .models import GitStatus
from .theme import ThemeColors


def display_web_url(url: str | None) -> str:
    """Return a URL without its scheme for compact display."""
    return url.removeprefix("http://").removeprefix("https://") if url else ""


def format_web_url(
    url: str | None,
    *,
    color: str = "blue",
    empty: str = "",
    hovered: bool = False,
) -> Text:
    """Format a URL for display without its scheme."""
    if not url:
        return Text(empty, style="dim" if empty else "")

    text = Text(
        display_web_url(url),
        style=f"{color} underline" if hovered else color,
    )
    return text


def format_git_status(
    git_status: GitStatus | None,
    colors: ThemeColors,
    *,
    prefix: str = "",
) -> Text:
    """Format git changes, or a clean marker when status is available."""
    if git_status is None:
        return Text("")

    text = Text(prefix, style=colors.dim)
    if git_status.staged:
        text.append(f"+{git_status.staged} ", style=colors.green)
    if git_status.unstaged:
        text.append(f"~{git_status.unstaged} ", style=colors.yellow)
    if git_status.untracked:
        text.append(f"?{git_status.untracked} ", style=colors.dim)
    if git_status.ahead:
        text.append(f"↑{git_status.ahead} ", style=colors.cyan)
    if git_status.behind:
        text.append(f"↓{git_status.behind} ", style=colors.red)
    return text if text.plain != prefix else Text(f"{prefix}clean", style=colors.dim)
