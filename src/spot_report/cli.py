"""Command-line entry point `spot-report`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from spot_report import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser.

    Subcommands (`build`, `validate`, `snapshot`) are added by later roadmap tasks.
    """
    parser = argparse.ArgumentParser(
        prog="spot-report",
        description=(
            "Turn the survey responses of one school and one survey wave "
            "into a PDF report."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
