"""Metric registry: definitions, duplicates, lookups and checks of metric sets."""

from __future__ import annotations

from typing import Any

import pytest

from spot_report.metrics import (
    METRICS_VERSION,
    Distribution,
    MetricDefinition,
    MetricIdError,
    MetricRegistry,
    MetricSet,
    Proportion,
    RegistryError,
    Summary,
)


def _definition(**overrides: object) -> MetricDefinition:
    fields: dict[str, Any] = {
        "id": "symptoms.phq9.cutoff10",
        "kind": "proportion",
        "domain": "symptoms",
        "items": ("q1", "q2"),
        "since": "2026.1",
    }
    return MetricDefinition(**(fields | overrides))


def _registry() -> MetricRegistry:
    return MetricRegistry(
        [
            _definition(),
            _definition(id="symptoms.phq9.severity", kind="distribution"),
            _definition(id="resilience.res.total", kind="summary", domain="resilience"),
        ]
    )


def test_metrics_version_is_a_positive_int() -> None:
    assert isinstance(METRICS_VERSION, int)
    assert METRICS_VERSION >= 1


def test_lookup_and_iteration() -> None:
    registry = _registry()
    assert len(registry) == 3
    assert registry["symptoms.phq9.cutoff10"] == _definition()
    assert registry.get("nothing.here.at_all") is None
    assert "resilience.res.total" in registry
    assert list(registry) == sorted(registry)
    with pytest.raises(KeyError):
        registry["nothing.here.at_all"]


def test_empty_registry_is_valid() -> None:
    assert len(MetricRegistry([])) == 0


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(RegistryError, match="Duplicate"):
        MetricRegistry([_definition(), _definition(items=("q3",))])


@pytest.mark.parametrize(
    "bad", ["a.b", "a.b.c.d.e", "A.b.c", "a.b-c.d", "a..c", ".a.b.c"]
)
def test_definition_rejects_invalid_ids(bad: str) -> None:
    with pytest.raises(MetricIdError):
        _definition(id=bad, domain="a")


def test_domain_must_match_first_segment() -> None:
    with pytest.raises(RegistryError, match="domain"):
        _definition(domain="resilience")


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(RegistryError, match="kind"):
        _definition(kind="histogram")


@pytest.mark.parametrize(
    "overrides",
    [
        {"items": ["q1"]},
        {"items": (1,)},
        {"items": ("",)},
        {"since": ""},
        {"since": "20 26"},
        {"since": 2026},
    ],
)
def test_definition_rejects_bad_items_and_since(overrides: dict[str, Any]) -> None:
    with pytest.raises(RegistryError):
        _definition(**overrides)


def test_definition_without_items_is_allowed() -> None:
    assert _definition(items=()).items == ()


def test_check_accepts_matching_set() -> None:
    registry = _registry()
    registry.check(MetricSet())
    registry.check(
        MetricSet(
            {
                "symptoms.phq9.cutoff10": Proportion(1, 2),
                "symptoms.phq9.severity": Distribution(("0",), (1,)),
                "resilience.res.total": Summary(
                    0, 0, None, None, None, None, None, None, None
                ),
            }
        )
    )


def test_check_rejects_unknown_id() -> None:
    with pytest.raises(RegistryError, match="unregistered"):
        _registry().check(MetricSet({"symptoms.phq9.other": Proportion(1, 2)}))


def test_check_rejects_wrong_kind() -> None:
    with pytest.raises(RegistryError, match="kind"):
        _registry().check(
            MetricSet({"symptoms.phq9.cutoff10": Distribution(("0",), (1,))})
        )


def test_check_reports_all_problems() -> None:
    metrics = MetricSet(
        {
            "symptoms.phq9.cutoff10": Distribution(("0",), (1,)),
            "symptoms.phq9.other": Proportion(1, 2),
        }
    )
    with pytest.raises(RegistryError) as excinfo:
        _registry().check(metrics)
    message = str(excinfo.value)
    assert "symptoms.phq9.cutoff10" in message
    assert "symptoms.phq9.other" in message
