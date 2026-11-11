"""Command-line entry point `spot-report`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from spot_report import __version__, config
from spot_report.ingest import Finding, Severity, has_errors, validate_bundle
from spot_report.store import StoreError, WaveInfo, open_store

EXIT_OK = 0
EXIT_INVALID_INPUT = 3


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser.

    The subcommand `build` is added by a later roadmap task.
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
    _add_snapshot_commands(commands)
    return parser


def _add_snapshot_commands(commands: argparse._SubParsersAction) -> None:
    snapshot = commands.add_parser(
        "snapshot",
        help="inspect the snapshot store",
        description=(
            "Read-only commands on a snapshot store, given by --store or the "
            f"environment variable {config.STORE_VAR}. Exit code 3 if neither is "
            "given, the store cannot be read or the school or wave is not in it."
        ),
    )
    snapshot.set_defaults(snapshot_help=snapshot.print_help)
    actions = snapshot.add_subparsers(dest="snapshot_command", metavar="<action>")
    listing = actions.add_parser(
        "list",
        help="list the stored waves, ordered by fieldwork end",
        description=(
            "Print one line per stored wave: school, wave label, fieldwork "
            "dates, questionnaire version, metrics version and save time."
        ),
    )
    _add_store_option(listing)
    listing.add_argument("--school", metavar="ID", help="only the waves of this school")
    export = actions.add_parser(
        "export",
        help="write one snapshot as JSON to standard output",
        description=(
            "Write the metadata and the metrics of one snapshot as indented UTF-8 "
            "JSON to standard output (redirect it to save it)."
        ),
    )
    _add_store_option(export)
    export.add_argument("--school", metavar="ID", required=True, help="school id")
    export.add_argument("--wave", metavar="LABEL", required=True, help="wave label")


def _add_store_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        metavar="PATH",
        help=(
            f"snapshot store (SQLite file), overrides {config.STORE_VAR}; it is never "
            "created by this command"
        ),
    )


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> int:
    """Run the command line and return the process exit code.

    ``env`` is the environment for settings (default ``os.environ``).
    """
    env = os.environ if env is None else env
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.bundle)
    if args.command == "snapshot":
        if args.snapshot_command is None:
            args.snapshot_help()
            return EXIT_OK
        try:
            store = _store(args.store, env)
            if args.snapshot_command == "list":
                return _snapshot_list(store, args.school)
            return _snapshot_export(store, args.school, args.wave)
        except StoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_INVALID_INPUT
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


def _store(option: str | None, env: Mapping[str, str]) -> Path:
    """``--store`` if given, else ``SPOT_STORE``; no default location (ADR 0004)."""
    if option is not None:
        return Path(option)
    path = config.store_path(env)
    if path is None:
        raise StoreError(f"No snapshot store: pass --store or set {config.STORE_VAR}")
    return path


def _snapshot_list(store_path: Path, school: str | None) -> int:
    """One line per wave; messages carry ids and dates, never metric values."""
    with open_store(store_path, create=False) as store:
        schools = store.list_schools()
        if school is not None:
            if school not in {info.id for info in schools}:
                raise StoreError(f"No snapshots for school {school!r}")
            schools = tuple(info for info in schools if info.id == school)
        lines = [
            _format_wave(info.id, info.name, wave)
            for info in schools
            for wave in store.list_waves(info.id)
        ]
    print("\n".join(lines) if lines else "No snapshots")
    return EXIT_OK


def _format_wave(school_id: str, school_name: str, wave: WaveInfo) -> str:
    start = wave.fieldwork_start.isoformat() if wave.fieldwork_start else "?"
    return "  ".join(
        (
            f"school={school_id}",
            f"wave={wave.label}",
            f"fieldwork={start}..{wave.fieldwork_end.isoformat()}",
            f"questionnaire={wave.questionnaire_version}",
            f"metrics_version={wave.metrics_version}",
            f"saved={wave.created_at.isoformat()}",
            f"name={school_name}",
        )
    )


def _snapshot_export(store_path: Path, school: str, wave: str) -> int:
    """Write the snapshot as JSON; nothing else goes to standard output."""
    with open_store(store_path, create=False) as store:
        snapshot = store.load_snapshot(school, wave)
    text = json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False, allow_nan=False)
    _write_stdout_utf8(text + "\n")
    return EXIT_OK


def _write_stdout_utf8(text: str) -> None:
    """Write UTF-8 regardless of the locale of the terminal or pipe."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()
