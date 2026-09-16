import argparse
from collections.abc import Sequence

from . import __version__
from .app import FlotteApp
from .terminal_theme import query_terminal_scheme
from .theme import register_terminal_scheme


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage docker-compose projects across git worktrees.")
    parser.add_argument("--version", action="version", version=f"Flotte {__version__}")
    parser.parse_args(argv)

    # Must run before Textual takes the tty; a silent terminal just yields None.
    register_terminal_scheme(query_terminal_scheme())
    app = FlotteApp()
    app.run()


if __name__ == "__main__":
    main()
