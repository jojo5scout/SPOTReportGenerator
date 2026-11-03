"""The input bundle manifest (architecture section 3, schema version 1).

``manifest.json`` tells the program which school, wave and questionnaire version a
responses file belongs to. It is parsed into frozen dataclasses with explicit checks
(standard library only). Every problem raises :class:`ManifestError` whose message
names the offending field, for example ``wave.fieldwork_end``. Messages never contain
values from the manifest or from the responses file.

JSON ``null`` is accepted for optional fields and means "absent".
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSION = 1

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class ManifestError(ValueError):
    """The manifest is unreadable, malformed or violates the schema."""


class ResponseFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


@dataclass(frozen=True)
class School:
    id: str
    name: str


@dataclass(frozen=True)
class Wave:
    """``fieldwork_end`` orders the waves of a school (architecture section 7)."""

    label: str
    fieldwork_end: date
    fieldwork_start: date | None = None


@dataclass(frozen=True)
class Survey:
    questionnaire_version: str
    limesurvey_id: int | None = None


@dataclass(frozen=True)
class ResponseCounts:
    """Completed and incomplete responses as reported by LimeSurvey."""

    completed: int
    incomplete: int


@dataclass(frozen=True)
class ResponsesRef:
    """Name (inside the bundle) and format of the responses file."""

    file: str
    format: ResponseFormat
    counts: ResponseCounts | None = None


@dataclass(frozen=True)
class Manifest:
    school: School
    wave: Wave
    survey: Survey
    responses: ResponsesRef
    schema_version: int = SUPPORTED_SCHEMA_VERSION


# --- loading -----------------------------------------------------------------------


def load_manifest(path: str | Path) -> Manifest:
    """Read and validate a ``manifest.json``."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise ManifestError(f"Cannot read manifest {path.name}") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ManifestError(f"Manifest {path.name} is not valid JSON") from None
    return parse_manifest(data)


def parse_manifest(data: object) -> Manifest:
    """Validate a parsed manifest (a dict) and build the :class:`Manifest`."""
    top = _mapping(
        data,
        "manifest",
        required={"schema_version", "school", "wave", "survey", "responses"},
    )
    version = _int(top["schema_version"], "schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ManifestError(
            f"schema_version is not supported (supported: {SUPPORTED_SCHEMA_VERSION})"
        )
    return Manifest(
        schema_version=version,
        school=_school(top["school"]),
        wave=_wave(top["wave"]),
        survey=_survey(top["survey"]),
        responses=_responses(top["responses"]),
    )


def _school(raw: object) -> School:
    fields = _mapping(raw, "school", required={"id", "name"})
    return School(
        id=_str(fields["id"], "school.id"),
        name=_str(fields["name"], "school.name"),
    )


def _wave(raw: object) -> Wave:
    fields = _mapping(
        raw,
        "wave",
        required={"label", "fieldwork_end"},
        optional={"fieldwork_start"},
    )
    start = _optional(fields, "fieldwork_start", "wave", _iso_date)
    end = _iso_date(fields["fieldwork_end"], "wave.fieldwork_end")
    if start is not None and start > end:
        raise ManifestError("wave.fieldwork_start is after wave.fieldwork_end")
    return Wave(
        label=_str(fields["label"], "wave.label"),
        fieldwork_end=end,
        fieldwork_start=start,
    )


def _survey(raw: object) -> Survey:
    fields = _mapping(
        raw,
        "survey",
        required={"questionnaire_version"},
        optional={"limesurvey_id"},
    )
    return Survey(
        questionnaire_version=_str(
            fields["questionnaire_version"], "survey.questionnaire_version"
        ),
        limesurvey_id=_optional(fields, "limesurvey_id", "survey", _int),
    )


def _responses(raw: object) -> ResponsesRef:
    fields = _mapping(
        raw,
        "responses",
        required={"file", "format"},
        optional={"counts"},
    )
    return ResponsesRef(
        file=_file_name(fields["file"], "responses.file"),
        format=_format(fields["format"], "responses.format"),
        counts=_optional(fields, "counts", "responses", _counts),
    )


def _counts(raw: object, where: str) -> ResponseCounts:
    fields = _mapping(raw, where, required={"completed", "incomplete"})
    return ResponseCounts(
        completed=_non_negative_int(fields["completed"], f"{where}.completed"),
        incomplete=_non_negative_int(fields["incomplete"], f"{where}.incomplete"),
    )


# --- small validators --------------------------------------------------------------


def _mapping(
    value: object,
    where: str,
    required: set[str],
    optional: set[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{where} must be an object")
    allowed = required | (optional or set())
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise ManifestError(f"{where} has unknown keys: {unknown}")
    missing = sorted(key for key in required if key not in value)
    if missing:
        names = [key if where == "manifest" else f"{where}.{key}" for key in missing]
        raise ManifestError(f"{where} is missing required fields: {names}")
    return value


def _optional[T](
    fields: Mapping[str, Any],
    key: str,
    parent: str,
    check: Callable[[object, str], T],
) -> T | None:
    value = fields.get(key)
    return None if value is None else check(value, f"{parent}.{key}")


def _str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where} must be a non-empty string")
    return value


def _int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{where} must be an integer")
    return value


def _non_negative_int(value: object, where: str) -> int:
    number = _int(value, where)
    if number < 0:
        raise ManifestError(f"{where} must not be negative")
    return number


def _iso_date(value: object, where: str) -> date:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ManifestError(f"{where} must be a date in the form YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ManifestError(f"{where} is not a valid calendar date") from None


def _format(value: object, where: str) -> ResponseFormat:
    try:
        return ResponseFormat(value)
    except ValueError:
        allowed = [f.value for f in ResponseFormat]
        raise ManifestError(f"{where} must be one of {allowed}") from None


def _file_name(value: object, where: str) -> str:
    """A bare file name: the responses file always lies directly in the bundle."""
    name = _str(value, where)
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise ManifestError(f"{where} must be a plain file name without a directory")
    return name
