import argparse
from collections.abc import Sequence

from tui_kit.start import start

from . import __version__
from .app import FlotteApp


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage docker-compose projects across git worktrees.")
    parser.add_argument("--version", action="version", version=f"Flotte {__version__}")
    parser.parse_args(argv)
    start("flotte", FlotteApp)


if __name__ == "__main__":
    main()
