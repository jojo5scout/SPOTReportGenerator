"""Reject data files outside the directories reserved for synthetic data.

Used as a pre-commit hook: pre-commit passes the staged file paths as arguments.
Only file names are reported, never file contents.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

DATA_SUFFIXES = frozenset(
    {
        # spreadsheets and delimited text
        ".csv",
        ".tsv",
        ".xls",
        ".xlsx",
        ".xlsm",
        ".ods",
        # statistics packages and columnar formats
        ".sav",
        ".por",
        ".dta",
        ".rds",
        ".rdata",
        ".parquet",
        ".feather",
        # databases
        ".sqlite",
        ".sqlite3",
        ".db",
        # LimeSurvey survey structure, archive and response exports
        ".lss",
        ".lsa",
        ".lsr",
    }
)

ALLOWED_DIRS = (
    PurePosixPath("tests/fixtures"),
    PurePosixPath("examples/content-demo"),
)


def is_data_file(path: PurePosixPath) -> bool:
    return path.suffix.lower() in DATA_SUFFIXES


def is_allowed_location(path: PurePosixPath) -> bool:
    return any(path.is_relative_to(allowed) for allowed in ALLOWED_DIRS)


def find_violations(paths: Iterable[str]) -> list[str]:
    """Return the paths that are data files outside the allowed directories."""
    violations = []
    for raw in paths:
        path = PurePosixPath(raw.replace("\\", "/"))
        if is_data_file(path) and not is_allowed_location(path):
            violations.append(raw)
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    paths = sys.argv[1:] if argv is None else argv
    violations = find_violations(paths)
    for path in violations:
        print(f"{path}: data file outside tests/fixtures/ and examples/content-demo/")
    if violations:
        print(
            "Only synthetic datasets are allowed, and only in tests/fixtures/ "
            "or examples/content-demo/."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
