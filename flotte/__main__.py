import argparse
from collections.abc import Sequence

from . import __version__
from .app import FlotteApp


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage docker-compose projects across git worktrees.")
    parser.add_argument("--version", action="version", version=f"Flotte {__version__}")
    parser.parse_args(argv)

    app = FlotteApp()
    app.run()


if __name__ == "__main__":
    main()
