"""Command-line entry point `spot-report`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from spot_report import __version__
from spot_report.ingest import Finding, Severity, has_errors, validate_bundle

EXIT_OK = 0
EXIT_INVALID_INPUT = 3


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser.

    Subcommands `build` and `snapshot` are added by later roadmap tasks.
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
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    validate = commands.add_parser(
        "validate",
        help="check an input bundle against the questionnaire spec",
        description=(
            "Structural checks of an input bundle (manifest and responses file). "
            "Prints one line per finding; exit code 3 if there are errors."
        ),
    )
    validate.add_argument("bundle", help="directory with manifest.json and responses")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.bundle)
    parser.print_help()
    return EXIT_OK


def _validate(bundle: str) -> int:
    findings = validate_bundle(bundle)
    for finding in findings:
        print(_format_finding(finding))
    errors = sum(f.severity is Severity.ERROR for f in findings)
    warnings = sum(f.severity is Severity.WARNING for f in findings)
    if findings:
        print(f"{errors} error(s), {warnings} warning(s) in {len(findings)} finding(s)")
    else:
        print("No findings")
    return EXIT_INVALID_INPUT if has_errors(findings) else EXIT_OK


def _format_finding(finding: Finding) -> str:
    """One line: severity, rule, column code and count; never cell values."""
    parts = [finding.severity.value, finding.rule.value]
    if finding.column is not None:
        parts.append(f"column={finding.column}")
    parts.append(f"count={finding.count}")
    line = "  ".join(parts)
    return f"{line}  {finding.message}" if finding.message else line
