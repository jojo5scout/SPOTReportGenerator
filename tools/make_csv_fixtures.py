"""Generate the CSV fixtures from the XLSX fixtures in tests/fixtures/.

Each ``<name>.xlsx`` becomes ``<name>.csv`` in the LimeSurvey ``export_responses``
format (see the docstring of ``spot_report.ingest.readers``): UTF-8 without BOM,
comma delimiter, LF line endings, one heading row of question codes, empty cells
empty, no quoting unless a field needs it.

Usage::

    uv run python tools/make_csv_fixtures.py          # (re)write the CSV files
    uv run python tools/make_csv_fixtures.py --check  # fail if a CSV is out of date

The conversion reads the workbook cell by cell and is deliberately strict: it only
accepts text, integers and empty cells, which is all the synthetic data contain.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections.abc import Sequence
from pathlib import Path

import openpyxl

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise TypeError(f"unsupported cell type: {type(value).__name__}")
    return str(value)


def xlsx_to_csv_bytes(path: Path) -> bytes:
    """The LimeSurvey-style CSV for the first sheet of a workbook, as bytes."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(workbook.worksheets[0].iter_rows(values_only=True))
    finally:
        workbook.close()
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return buffer.getvalue().encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="do not write, fail if out of date"
    )
    args = parser.parse_args(argv)

    stale = []
    for xlsx in sorted(FIXTURE_DIR.glob("*.xlsx")):
        target = xlsx.with_suffix(".csv")
        content = xlsx_to_csv_bytes(xlsx)
        if args.check:
            if not target.is_file() or target.read_bytes() != content:
                stale.append(target.name)
        else:
            target.write_bytes(content)
            print(f"wrote {target.name}")
    if stale:
        print(f"out of date: {stale}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
