"""Readers for the responses file of an input bundle (architecture sections 3 and 4).

Reading and type normalisation only: whether columns, codes and ranges are right is
decided later (validate, R09), and empty cells are never interpreted beyond ``NA``
(decision D12). Both formats go through the same normalisation, so the same dataset
as CSV and as XLSX yields identical DataFrames (values, dtypes, index, columns).

Normalisation
-------------
* Headings are the question codes, stripped. A column with an empty heading is dropped
  if all its cells are empty (stray spreadsheet columns), otherwise it is an error.
  Duplicate headings are an error.
* Cells are strings, stripped. An empty or whitespace-only cell becomes ``pd.NA``.
  Rows in which every cell is empty are dropped (blank lines, trailing spreadsheet
  rows). Strings such as ``NA`` or ``null`` are *not* treated as missing.
* Columns the spec knows as numeric (scale items, numeric questions) and the response
  id become ``Int64``. All other columns (metadata, single-choice codes, multi-select
  markers, free text, columns unknown to the spec) become ``string`` dtype. Metadata
  such as dates keeps its text form; see the format notes below.
* Values that are not integers are never turned into ``NA``. If at least one value of
  a numeric column cannot be converted, the whole column stays ``string`` with the raw
  (stripped) text. Validation (R09) finds such columns with
  :func:`unconverted_columns` and reports them by column code and count.
* Free-text columns are kept as strings and never interpreted or logged (D14).

CSV format (LimeSurvey ``export_responses``, headings ``code``, responses ``short``),
read off the CSV exports with dummy answers of the synthetic data:
UTF-8 without byte order mark, delimiter comma, line ending LF, no quoting for these
data (quotes are handled by the standard ``csv`` rules should a field need them), one
heading row of question codes followed by one row per response, every row with the
same number of fields, empty cells written as nothing between two commas, ``id`` as a
running number, ``submitdate`` as ``YYYY-MM-DD`` text, answers as numbers or short
codes. The reader also accepts a UTF-8 BOM and CRLF line endings.

XLSX: the first sheet, headings in row 1, same structure. Cell values are converted to
the text a CSV export would show: integers and integral floats without decimals,
date-times (which is how spreadsheet date cells arrive) as
``YYYY-MM-DD HH:MM:SS``. Metadata is never analysed, so the
exact form only has to be the same for the same cell.

Error messages contain the file name and a reason, never cell values.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

import openpyxl
import pandas as pd

from spot_report.ingest.manifest import Manifest, ResponseFormat, load_manifest
from spot_report.questionnaire import QuestionKind, QuestionnaireSpec, load_spec

MANIFEST_NAME = "manifest.json"

_STRING = pd.StringDtype(na_value=pd.NA)
_INTEGER = re.compile(r"[+-]?[0-9]+")
_Cells = list[str | None]


class ReadError(ValueError):
    """The responses file cannot be read or is not in the expected format."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"Cannot read {path.name}: {reason}")
        self.path = path
        self.reason = reason


@dataclass(frozen=True, eq=False)
class Dataset:
    """A bundle's manifest together with its normalised responses."""

    manifest: Manifest
    responses: pd.DataFrame


# --- public entry points -------------------------------------------------------------


def read_responses(
    path: str | Path, fmt: ResponseFormat | str, spec: QuestionnaireSpec
) -> pd.DataFrame:
    """Read a responses file in the given format into the normalised DataFrame."""
    path = Path(path)
    try:
        response_format = ResponseFormat(fmt)
    except ValueError:
        raise ReadError(path, "unsupported file format") from None
    if response_format is ResponseFormat.CSV:
        return read_csv_responses(path, spec)
    return read_xlsx_responses(path, spec)


def read_csv_responses(path: str | Path, spec: QuestionnaireSpec) -> pd.DataFrame:
    """Read a LimeSurvey CSV export (UTF-8, comma separated, heading row)."""
    path = Path(path)
    _require_file(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = [row for row in csv.reader(handle, strict=True) if row]
    except UnicodeDecodeError:
        raise ReadError(path, "file is not valid UTF-8 text") from None
    except csv.Error:
        raise ReadError(path, "file is not well-formed CSV") from None
    except OSError:
        raise ReadError(path, "file cannot be opened") from None
    if not rows:
        raise ReadError(path, "file has no heading row")

    headings, body = rows[0], rows[1:]
    if len(headings) == 1 and any(sep in headings[0] for sep in (";", "\t")):
        raise ReadError(path, "delimiter is not a comma")
    for number, row in enumerate(body, start=2):
        if len(row) != len(headings):
            raise ReadError(
                path,
                f"line {number} has {len(row)} fields, expected {len(headings)}",
            )
    return _normalise(path, headings, body, spec)


def read_xlsx_responses(path: str | Path, spec: QuestionnaireSpec) -> pd.DataFrame:
    """Read the first sheet of an XLSX export (headings in row 1)."""
    path = Path(path)
    _require_file(path)
    # Any parser failure becomes a ReadError; only the exception type is reported.
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ReadError(
            path, f"not a readable XLSX workbook ({type(exc).__name__})"
        ) from None
    try:
        sheets = workbook.worksheets
        raw = (
            [list(row) for row in sheets[0].iter_rows(values_only=True)]
            if sheets
            else []
        )
    except Exception as exc:
        raise ReadError(path, f"sheet cannot be read ({type(exc).__name__})") from None
    finally:
        workbook.close()
    if not raw:
        raise ReadError(path, "workbook has no sheet or the sheet is empty")

    width = max(len(row) for row in raw)
    cells = [[_cell_text(value) for value in row] for row in raw]
    padded = [row + [None] * (width - len(row)) for row in cells]
    return _normalise(path, [h or "" for h in padded[0]], padded[1:], spec)


def unconverted_columns(
    responses: pd.DataFrame, spec: QuestionnaireSpec
) -> tuple[str, ...]:
    """Columns that should be integers but still hold text.

    These are the numeric columns of the spec (and the response id) in which at least
    one value was not an integer. Reading leaves such a column as raw ``string`` so
    nothing is lost; validation reports it by code and count of offending cells.
    """
    return tuple(
        code
        for code in _integer_columns(spec)
        if code in responses.columns and responses[code].dtype != pd.Int64Dtype()
    )


def load_bundle(directory: str | Path) -> Dataset:
    """Load ``manifest.json`` and the responses file of an input bundle."""
    directory = Path(directory)
    manifest = load_manifest(directory / MANIFEST_NAME)
    spec = load_spec(manifest.survey.questionnaire_version)
    responses = read_responses(
        directory / manifest.responses.file, manifest.responses.format, spec
    )
    return Dataset(manifest=manifest, responses=responses)


# --- normalisation, shared by both formats -------------------------------------------


def _normalise(
    path: Path,
    headings: Sequence[str | None],
    body: Sequence[Sequence[str | None]],
    spec: QuestionnaireSpec,
) -> pd.DataFrame:
    codes = [(h or "").strip() for h in headings]
    rows = [[_clean(cell) for cell in row] for row in body]
    rows = [row for row in rows if any(cell is not None for cell in row)]

    keep: list[int] = []
    for index, code in enumerate(codes):
        if code:
            keep.append(index)
        elif any(row[index] is not None for row in rows):
            raise ReadError(path, f"column {index + 1} has cells but no heading")
    kept_codes = [codes[index] for index in keep]
    if len(set(kept_codes)) != len(kept_codes):
        seen: set[str] = set()
        positions = [
            index + 1
            for index in keep
            if codes[index] in seen or seen.add(codes[index])
        ]
        raise ReadError(path, f"duplicate headings in columns {positions}")

    integer_columns = set(_integer_columns(spec))
    data = {
        code: _series([row[index] for row in rows], as_integer=code in integer_columns)
        for code, index in zip(kept_codes, keep, strict=True)
    }
    return pd.DataFrame(data, index=pd.RangeIndex(len(rows)), columns=kept_codes)


def _clean(cell: str | None) -> str | None:
    if cell is None:
        return None
    text = cell.strip()
    return text or None


def _series(values: _Cells, *, as_integer: bool) -> pd.Series:
    text = pd.Series(values, dtype=_STRING)
    if not as_integer:
        return text
    present = text.dropna()
    if not present.str.fullmatch(_INTEGER).all():
        return text
    try:
        return text.astype(pd.Int64Dtype())
    except (OverflowError, ValueError, TypeError):
        return text


def _integer_columns(spec: QuestionnaireSpec) -> tuple[str, ...]:
    numeric = tuple(q.code for q in spec.questions if q.kind is QuestionKind.NUMERIC)
    return (spec.response_id, *numeric)


def _cell_text(value: object) -> str | None:
    """The text a CSV export would show for a spreadsheet cell."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value)


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise ReadError(path, "file not found")
