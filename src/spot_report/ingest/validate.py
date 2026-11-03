"""Structural validation of a responses file (architecture sections 3 and 4).

The checks cover the shape of the data only: required columns are present, answer
codes and numeric values are inside the allowed sets and ranges, response ids are
unique and not empty, and the bundle (manifest, file) can be read. Whether individual
responses are plausible is a later stage (quality, R48-R50).

Rules
-----
``missing_column``     a required column of the spec is absent
``invalid_code``       single-choice cell not among the allowed codes
``invalid_marker``     multi-select option cell is not the ``selected`` code
``out_of_range``       numeric cell outside the inclusive range of the spec
``not_an_integer``     numeric cell that is not an integer (the reader left the
                       column as text, see ``unconverted_columns``)
``duplicate_id``       response id repeated (rows that repeat an earlier id)
``empty_id``           response without an id
``unreadable_file``    the responses file cannot be read (``ReadError``)
``invalid_manifest``   the manifest is unreadable or violates its schema
``unknown_version``    no spec for the questionnaire version of the manifest

All findings are errors. A finding holds a rule, a column code and a count of
offending cells (or rows), never a response value, a response id or row contents.
Empty cells (``NA``) are never counted by any rule, also not when a column is empty
for every respondent (decision D12). Free-text columns, metadata other than the
response id and columns unknown to the spec are not value-checked, and unknown
columns are not a finding.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pandas as pd

from spot_report.ingest.manifest import ManifestError, load_manifest
from spot_report.ingest.readers import (
    INTEGER_PATTERN,
    MANIFEST_NAME,
    ReadError,
    read_responses,
    unconverted_columns,
)
from spot_report.questionnaire import (
    QuestionKind,
    QuestionnaireSpec,
    UnknownVersionError,
    available_versions,
    load_spec,
)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Rule(StrEnum):
    MISSING_COLUMN = "missing_column"
    INVALID_CODE = "invalid_code"
    INVALID_MARKER = "invalid_marker"
    OUT_OF_RANGE = "out_of_range"
    NOT_AN_INTEGER = "not_an_integer"
    DUPLICATE_ID = "duplicate_id"
    EMPTY_ID = "empty_id"
    UNREADABLE_FILE = "unreadable_file"
    INVALID_MANIFEST = "invalid_manifest"
    UNKNOWN_VERSION = "unknown_version"


@dataclass(frozen=True)
class Finding:
    """One validation result.

    ``count`` is the number of offending cells (rows for the id rules, 1 for a
    missing column or a file-level problem). ``message`` is only set for file-level
    findings and holds the reason, which by construction contains no cell values.
    """

    severity: Severity
    rule: Rule
    column: str | None
    count: int
    message: str = ""


def has_errors(findings: tuple[Finding, ...]) -> bool:
    return any(f.severity is Severity.ERROR for f in findings)


# --- entry points --------------------------------------------------------------------


def validate(responses: pd.DataFrame, spec: QuestionnaireSpec) -> tuple[Finding, ...]:
    """Structural findings of a normalised responses DataFrame, sorted."""
    findings: list[Finding] = []
    present = set(responses.columns)

    for code in spec.required_columns:
        if code not in present:
            findings.append(_error(Rule.MISSING_COLUMN, code, 1))

    findings.extend(_id_findings(responses, spec))

    unconverted = set(unconverted_columns(responses, spec))
    for question in spec.questions:
        if question.code not in present:
            continue
        cells = responses[question.code].dropna()
        match question.kind:
            case QuestionKind.SINGLE_CHOICE:
                bad = ~cells.astype("string").isin(question.codes)
                findings.append(
                    _error(Rule.INVALID_CODE, question.code, int(bad.sum()))
                )
            case QuestionKind.MULTI_SELECT_OPTION:
                bad = cells.astype("string") != question.selected
                findings.append(
                    _error(Rule.INVALID_MARKER, question.code, int(bad.sum()))
                )
            case QuestionKind.NUMERIC:
                findings.extend(
                    _numeric_findings(
                        question.code,
                        cells,
                        question.min_value,
                        question.max_value,
                        as_text=question.code in unconverted,
                    )
                )
            case _:
                continue

    if spec.response_id in unconverted:
        findings.extend(
            _numeric_findings(
                spec.response_id,
                responses[spec.response_id].dropna(),
                None,
                None,
                as_text=True,
            )
        )

    return _sorted(f for f in findings if f.count > 0)


def validate_bundle(directory: str | Path) -> tuple[Finding, ...]:
    """Read a bundle and validate it; read problems become findings."""
    directory = Path(directory)
    try:
        manifest = load_manifest(directory / MANIFEST_NAME)
    except ManifestError as exc:
        return (_file_error(Rule.INVALID_MANIFEST, str(exc)),)
    version = manifest.survey.questionnaire_version
    try:
        spec = load_spec(version)
    except UnknownVersionError:
        reason = (
            "questionnaire version is not known "
            f"(available: {list(available_versions())})"
        )
        return (_file_error(Rule.UNKNOWN_VERSION, reason),)
    try:
        responses = read_responses(
            directory / manifest.responses.file, manifest.responses.format, spec
        )
    except ReadError as exc:
        return (_file_error(Rule.UNREADABLE_FILE, str(exc)),)
    return validate(responses, spec)


# --- rules ---------------------------------------------------------------------------


def _id_findings(responses: pd.DataFrame, spec: QuestionnaireSpec) -> list[Finding]:
    code = spec.response_id
    if code not in responses.columns:
        return []
    ids = responses[code]
    present = ids.dropna()
    return [
        _error(Rule.EMPTY_ID, code, int(ids.isna().sum())),
        _error(Rule.DUPLICATE_ID, code, int(present.duplicated().sum())),
    ]


def _numeric_findings(
    code: str,
    cells: pd.Series,
    low: int | None,
    high: int | None,
    *,
    as_text: bool,
) -> list[Finding]:
    """Range and integer checks on the non-empty cells of a numeric column.

    ``as_text`` marks a column the reader left as text because some value is not an
    integer: those cells are counted as ``not_an_integer``, and the cells that are
    integers are still range-checked.
    """
    findings: list[Finding] = []
    if as_text:
        text = cells.astype("string")
        is_integer = text.str.fullmatch(INTEGER_PATTERN).astype(bool)
        findings.append(_error(Rule.NOT_AN_INTEGER, code, int((~is_integer).sum())))
        values = text[is_integer].map(int)
    else:
        values = cells
    if low is not None and high is not None:
        outside = (values < low) | (values > high)
        findings.append(_error(Rule.OUT_OF_RANGE, code, int(outside.sum())))
    return findings


# --- helpers -------------------------------------------------------------------------


def _error(rule: Rule, column: str | None, count: int) -> Finding:
    return Finding(Severity.ERROR, rule, column, count)


def _file_error(rule: Rule, message: str) -> Finding:
    return Finding(Severity.ERROR, rule, None, 1, message)


def _sorted(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    order = list(Severity)
    return tuple(
        sorted(
            findings,
            key=lambda f: (order.index(f.severity), f.rule.value, f.column or ""),
        )
    )
