"""Manifest model: valid documents and every kind of invalid one.

Messages must name the field; none of them may contain a value from the document.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from spot_report.ingest import (
    ManifestError,
    ResponseCounts,
    ResponseFormat,
    load_manifest,
    parse_manifest,
)

VALID: dict[str, Any] = {
    "schema_version": 1,
    "school": {"id": "gym-example", "name": "Gymnasium Beispiel"},
    "wave": {
        "label": "2026",
        "fieldwork_start": "2026-04-20",
        "fieldwork_end": "2026-05-15",
    },
    "survey": {"limesurvey_id": 123456, "questionnaire_version": "2026.1"},
    "responses": {"file": "responses.csv", "format": "csv"},
}


def document(**changes: object) -> dict[str, Any]:
    """A copy of VALID with dotted paths replaced (``None`` value deletes the key)."""
    doc = copy.deepcopy(VALID)
    for dotted, value in changes.items():
        *parents, leaf = dotted.split("__")
        node = doc
        for parent in parents:
            node = node[parent]
        if value is None:
            node.pop(leaf, None)
        else:
            node[leaf] = value
    return doc


def test_valid_manifest_is_parsed() -> None:
    manifest = parse_manifest(VALID)
    assert manifest.schema_version == 1
    assert manifest.school.id == "gym-example"
    assert manifest.school.name == "Gymnasium Beispiel"
    assert manifest.wave.label == "2026"
    assert manifest.wave.fieldwork_start == date(2026, 4, 20)
    assert manifest.wave.fieldwork_end == date(2026, 5, 15)
    assert manifest.survey.limesurvey_id == 123456
    assert manifest.survey.questionnaire_version == "2026.1"
    assert manifest.responses.file == "responses.csv"
    assert manifest.responses.format is ResponseFormat.CSV
    assert manifest.responses.counts is None


def test_manifest_is_immutable() -> None:
    manifest = parse_manifest(VALID)
    with pytest.raises(AttributeError):
        manifest.school = manifest.school  # type: ignore[misc]


def test_optional_fields_may_be_absent_or_null() -> None:
    minimal = document(
        wave__fieldwork_start=None, survey__limesurvey_id=None, responses__format="xlsx"
    )
    manifest = parse_manifest(minimal)
    assert manifest.wave.fieldwork_start is None
    assert manifest.survey.limesurvey_id is None
    assert manifest.responses.format is ResponseFormat.XLSX
    nulls = document()
    nulls["wave"]["fieldwork_start"] = None
    nulls["survey"]["limesurvey_id"] = None
    nulls["responses"]["counts"] = None
    manifest = parse_manifest(nulls)
    assert manifest.wave.fieldwork_start is None
    assert manifest.survey.limesurvey_id is None
    assert manifest.responses.counts is None


def test_counts_present() -> None:
    doc = document(responses__counts={"completed": 287, "incomplete": 41})
    assert parse_manifest(doc).responses.counts == ResponseCounts(287, 41)


def test_counts_may_be_zero() -> None:
    doc = document(responses__counts={"completed": 0, "incomplete": 0})
    assert parse_manifest(doc).responses.counts == ResponseCounts(0, 0)


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"wave__fieldwork_end": None}, "wave.fieldwork_end"),
        ({"wave__label": None}, "wave.label"),
        ({"school__id": None}, "school.id"),
        ({"school__name": None}, "school.name"),
        ({"survey__questionnaire_version": None}, "survey.questionnaire_version"),
        ({"responses__file": None}, "responses.file"),
        ({"responses__format": None}, "responses.format"),
        ({"schema_version": None}, "schema_version"),
        ({"school": None}, "school"),
        ({"wave": None}, "wave"),
        ({"survey": None}, "survey"),
        ({"responses": None}, "responses"),
    ],
)
def test_missing_required_field(changes: dict[str, Any], field: str) -> None:
    with pytest.raises(ManifestError, match=field.replace(".", r"\.")):
        parse_manifest(document(**changes))


def test_fieldwork_end_null_is_rejected() -> None:
    doc = document()
    doc["wave"]["fieldwork_end"] = None
    with pytest.raises(ManifestError, match=r"wave\.fieldwork_end"):
        parse_manifest(doc)


@pytest.mark.parametrize("version", [0, 2, "1", 1.0, True, None])
def test_bad_schema_version(version: object) -> None:
    doc = document()
    doc["schema_version"] = version
    with pytest.raises(ManifestError, match="schema_version"):
        parse_manifest(doc)


@pytest.mark.parametrize(
    "value",
    ["15.05.2026", "2026-5-15", "20260515", "2026-W20-5", "2026-02-30", "", 20260515],
)
def test_bad_date(value: object) -> None:
    doc = document()
    doc["wave"]["fieldwork_end"] = value
    with pytest.raises(ManifestError, match=r"wave\.fieldwork_end"):
        parse_manifest(doc)


def test_bad_start_date() -> None:
    with pytest.raises(ManifestError, match=r"wave\.fieldwork_start"):
        parse_manifest(document(wave__fieldwork_start="April"))


def test_start_after_end() -> None:
    with pytest.raises(ManifestError, match=r"fieldwork_start is after"):
        parse_manifest(document(wave__fieldwork_start="2026-06-01"))


def test_start_equal_to_end_is_allowed() -> None:
    parse_manifest(document(wave__fieldwork_start="2026-05-15"))


@pytest.mark.parametrize(
    ("field", "counts"),
    [
        ("completed", {"completed": -1, "incomplete": 0}),
        ("incomplete", {"completed": 0, "incomplete": -3}),
        ("completed", {"completed": 1.5, "incomplete": 0}),
        ("incomplete", {"completed": 0, "incomplete": "4"}),
        ("completed", {"completed": True, "incomplete": 0}),
    ],
)
def test_bad_counts(field: str, counts: dict[str, Any]) -> None:
    with pytest.raises(ManifestError, match=rf"responses\.counts\.{field}"):
        parse_manifest(document(responses__counts=counts))


def test_counts_must_have_both_numbers() -> None:
    with pytest.raises(ManifestError, match=r"counts\.incomplete"):
        parse_manifest(document(responses__counts={"completed": 3}))


@pytest.mark.parametrize(
    ("changes", "where"),
    [
        ({"extra": 1}, "manifest"),
        ({"school__extra": 1}, "school"),
        ({"wave__extra": 1}, "wave"),
        ({"survey__extra": 1}, "survey"),
        ({"responses__extra": 1}, "responses"),
        (
            {"responses__counts": {"completed": 1, "incomplete": 1, "total": 2}},
            "responses.counts",
        ),
    ],
)
def test_unknown_keys(changes: dict[str, Any], where: str) -> None:
    with pytest.raises(
        ManifestError, match=rf"{where.replace('.', r'\.')} has unknown"
    ):
        parse_manifest(document(**changes))


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"school__id": 7}, "school.id"),
        ({"school__name": ""}, "school.name"),
        ({"school__name": "  "}, "school.name"),
        ({"wave__label": 2026}, "wave.label"),
        ({"survey__limesurvey_id": "123"}, "survey.limesurvey_id"),
        ({"survey__limesurvey_id": 1.5}, "survey.limesurvey_id"),
        ({"survey__limesurvey_id": True}, "survey.limesurvey_id"),
        ({"survey__questionnaire_version": 2026.1}, "survey.questionnaire_version"),
        ({"responses__format": "ods"}, "responses.format"),
        ({"responses__format": "CSV"}, "responses.format"),
        ({"responses__file": ["a.csv"]}, "responses.file"),
        ({"responses__file": "../responses.csv"}, "responses.file"),
        ({"responses__file": "sub/responses.csv"}, "responses.file"),
        ({"responses__file": "/etc/passwd"}, "responses.file"),
        ({"responses__counts": [1, 2]}, "responses.counts"),
    ],
)
def test_wrong_type_or_value_names_the_field(
    changes: dict[str, Any], field: str
) -> None:
    with pytest.raises(ManifestError, match=field.replace(".", r"\.")):
        parse_manifest(document(**changes))


@pytest.mark.parametrize("value", [[], "text", 3, None])
def test_top_level_must_be_an_object(value: object) -> None:
    with pytest.raises(ManifestError, match="manifest"):
        parse_manifest(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"wave__fieldwork_end": "MARKER-VALUE-123"},
        {"responses__format": "MARKER-VALUE-123"},
        {"survey__limesurvey_id": "MARKER-VALUE-123"},
        {"responses__counts": {"completed": "MARKER-VALUE-123", "incomplete": 0}},
    ],
)
def test_messages_do_not_echo_values(changes: dict[str, Any]) -> None:
    with pytest.raises(ManifestError) as info:
        parse_manifest(document(**changes))
    assert "MARKER-VALUE-123" not in str(info.value)


def test_load_manifest_from_file(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(VALID), encoding="utf-8")
    assert load_manifest(path) == parse_manifest(VALID)


def test_load_manifest_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match=r"manifest\.json"):
        load_manifest(tmp_path / "manifest.json")


def test_load_manifest_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid JSON"):
        load_manifest(path)


def test_load_manifest_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ManifestError, match="Cannot read"):
        load_manifest(path)
