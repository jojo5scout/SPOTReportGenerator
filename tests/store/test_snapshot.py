"""Snapshot metadata validation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime

import pytest

from spot_report.metrics import MetricSet, Proportion
from spot_report.store import Snapshot, SnapshotError


def make_snapshot(**overrides: object) -> Snapshot:
    fields: dict[str, object] = {
        "school_id": "demo",
        "school_name": "Demo School",
        "wave_label": "2026",
        "fieldwork_end": date(2026, 5, 15),
        "questionnaire_version": "2026.1",
        "program_version": "0.1.0",
        "metrics_version": 1,
        "metrics": MetricSet({"a.b.c": Proportion(1, 2, 0)}),
    }
    fields.update(overrides)
    return Snapshot(**fields)  # type: ignore[arg-type]


def test_optional_fields_default_to_none() -> None:
    snapshot = make_snapshot()
    assert snapshot.fieldwork_start is None
    assert snapshot.limesurvey_id is None
    assert snapshot.quality_rules_version is None
    assert snapshot.archive_path is None


def test_snapshot_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        make_snapshot().wave_label = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"school_id": ""},
        {"school_name": "  "},
        {"wave_label": ""},
        {"questionnaire_version": ""},
        {"program_version": ""},
        {"fieldwork_end": "2026-05-15"},
        {"fieldwork_end": datetime(2026, 5, 15, 12, 0)},
        {"fieldwork_start": date(2026, 5, 16)},
        {"fieldwork_start": "2026-04-01"},
        {"metrics_version": True},
        {"metrics_version": 1.0},
        {"limesurvey_id": "123"},
        {"archive_path": 3},
        {"quality_rules_version": 3},
        {"metrics": {"a.b.c": Proportion(1, 2, 0)}},
    ],
    ids=lambda overrides: next(iter(overrides)),
)
def test_invalid_metadata_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(SnapshotError):
        make_snapshot(**overrides)


def test_fieldwork_start_may_equal_end() -> None:
    snapshot = make_snapshot(fieldwork_start=date(2026, 5, 15))
    assert replace(snapshot, fieldwork_start=None).fieldwork_start is None


def test_to_dict_has_metadata_in_iso_text_and_the_metric_set_object() -> None:
    snapshot = Snapshot(
        school_id="demo",
        school_name="Demo",
        wave_label="2026",
        fieldwork_start=date(2026, 4, 20),
        fieldwork_end=date(2026, 5, 15),
        limesurvey_id=7,
        questionnaire_version="2026.1",
        program_version="0.1.0",
        metrics_version=2,
        quality_rules_version="q1",
        archive_path="demo/2026/001",
        metrics=MetricSet({"test.a.b": Proportion(1, 2, 0)}),
    )
    data = snapshot.to_dict()
    assert list(data) == [
        "school_id",
        "school_name",
        "wave_label",
        "fieldwork_start",
        "fieldwork_end",
        "limesurvey_id",
        "questionnaire_version",
        "program_version",
        "metrics_version",
        "quality_rules_version",
        "archive_path",
        "metrics",
    ]
    assert data["fieldwork_start"] == "2026-04-20"
    assert data["fieldwork_end"] == "2026-05-15"
    assert data["metrics"] == snapshot.metrics.to_dict()


def test_to_dict_keeps_missing_optional_fields_as_null() -> None:
    snapshot = Snapshot(
        school_id="demo",
        school_name="Demo",
        wave_label="2026",
        fieldwork_end=date(2026, 5, 15),
        questionnaire_version="2026.1",
        program_version="0.1.0",
        metrics_version=2,
        metrics=MetricSet(),
    )
    data = snapshot.to_dict()
    for name in (
        "fieldwork_start",
        "limesurvey_id",
        "quality_rules_version",
        "archive_path",
    ):
        assert data[name] is None
    assert data["metrics"] == {}
