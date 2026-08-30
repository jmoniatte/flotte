"""Shortcut documentation built from the bindings the app actually declares."""

from collections.abc import Iterable
from dataclasses import dataclass

from textual.binding import Binding

# A binding is documented on the help screen by giving it one of these groups.
ACTIONS = "Actions"
GENERAL = "General"
SECTIONS = (ACTIONS, GENERAL)


@dataclass(frozen=True, slots=True)
class Shortcut:
    """One documented key and what it does."""

    key: str
    description: str


def for_section(section: str, *sources: Iterable[object]) -> tuple[Shortcut, ...]:
    """Collect the documented bindings of one section, in declaration order."""
    collected = []
    for source in sources:
        for binding in source:
            if not isinstance(binding, Binding) or binding.group != section:
                continue
            if not binding.description:
                continue
            collected.append(
                Shortcut(binding.key_display or binding.key, binding.description)
            )
    return tuple(collected)
