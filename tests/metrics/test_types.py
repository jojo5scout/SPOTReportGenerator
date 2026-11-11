"""Metric types: invariants, constructors, JSON round trip, ids and MetricSet."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
import pytest

from spot_report.metrics import (
    Count,
    Distribution,
    Metric,
    MetricError,
    MetricFormatError,
    MetricIdError,
    MetricSet,
    Proportion,
    Summary,
    metric_from_dict,
    metric_from_json,
    validate_metric_id,
)
from spot_report.metrics.types import METRIC_KINDS

EMPTY_SUMMARY = Summary(0, 3, None, None, None, None, None, None, None)
ONE_SUMMARY = Summary(1, 0, 2.5, None, 2.5, 2.5, 2.5, 2.5, 2.5)
PRECISE_SUMMARY = Summary(
    n=7,
    n_missing=2,
    mean=1 / 3,
    sd=math.sqrt(2) / 7,
    median=0.1 + 0.2,
    q1=1e-17,
    q3=123456789.12345678,
    min=-0.0,
    max=1e300,
)

EXAMPLES = [
    Proportion(3, 10, 1),
    Proportion(0, 0, 0),
    Proportion(5, 5, 2),
    Count(300),
    Count(0, 0),
    EMPTY_SUMMARY,
    ONE_SUMMARY,
    PRECISE_SUMMARY,
    Distribution(("a", "b", "c"), (1, 0, 4), 2),
    Distribution((), (), 5),
    Distribution(("ä", "x y"), (0, 0), 0),
]


def _id(metric: object) -> str:
    return f"{type(metric).__name__}-{metric!r}"[:60]


# ---------------------------------------------------------------- round trip


@pytest.mark.parametrize("metric", EXAMPLES, ids=_id)
def test_round_trip_dict_and_json(metric: Metric) -> None:
    data = metric.to_dict()
    assert data["kind"] == type(metric).kind
    assert metric_from_dict(data) == metric
    assert type(metric).from_dict(data) == metric
    text = metric.to_json()
    assert metric_from_json(text) == metric
    assert type(metric).from_json(text) == metric
    # The text itself is stable (re-serialising gives identical text).
    assert metric_from_json(text).to_json() == text


def test_count_rejects_negative_and_non_integer_values() -> None:
    for bad in (-1, 2.0, True, None):
        with pytest.raises(MetricError):
            Count(bad)  # type: ignore[arg-type]
    with pytest.raises(MetricFormatError):
        metric_from_dict({"kind": "count", "n": 3})  # n_missing is required


@pytest.mark.parametrize("metric", EXAMPLES, ids=_id)
def test_json_has_no_nan_and_is_strict(metric: Metric) -> None:
    text = metric.to_json()
    json.loads(text, parse_constant=lambda name: pytest.fail(f"non-finite {name}"))


def test_summary_floats_round_trip_exactly() -> None:
    rng = random.Random(1)
    for _ in range(200):
        values = sorted(rng.uniform(-1e6, 1e6) for _ in range(5))
        summary = Summary(
            5,
            0,
            mean=rng.random(),
            sd=rng.random(),
            median=values[2],
            q1=values[1],
            q3=values[3],
            min=values[0],
            max=values[4],
        )
        assert Summary.from_json(summary.to_json()) == summary


def test_none_is_written_as_null() -> None:
    assert '"sd":null' in ONE_SUMMARY.to_json()
    assert EMPTY_SUMMARY.to_dict()["mean"] is None


def test_kind_tags_match_store_column() -> None:
    assert set(METRIC_KINDS) == {
        "proportion",
        "count",
        "summary",
        "distribution",
        "pattern_counts",
    }
    assert Proportion(1, 2).to_dict() == {
        "kind": "proportion",
        "k": 1,
        "n": 2,
        "n_missing": 0,
    }


def test_integer_json_numbers_are_accepted_as_floats() -> None:
    data = ONE_SUMMARY.to_dict() | {"mean": 2, "median": 2, "q1": 2, "q3": 2}
    data["min"] = data["max"] = 2
    summary = Summary.from_dict(data)
    assert summary.mean == 2.0
    assert isinstance(summary.mean, float)


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        "{}",
        '{"kind": "nope"}',
        '{"kind": 3}',
        '{"kind": "proportion", "k": 1, "n": 2}',
        '{"kind": "proportion", "k": 1, "n": 2, "n_missing": 0, "extra": 1}',
        '{"kind": "proportion", "k": 3, "n": 2, "n_missing": 0}',
        '{"kind": "proportion", "k": "1", "n": 2, "n_missing": 0}',
        '{"kind": "distribution", "categories": "ab", "counts": [1], "n_missing": 0}',
        '{"kind": "distribution", "categories": ["a"], "counts": [1, 2],'
        ' "n_missing": 0}',
        '{"kind": "summary", "n": 0, "n_missing": 0, "mean": NaN, "sd": null,'
        ' "median": null, "q1": null, "q3": null, "min": null, "max": null}',
    ],
)
def test_malformed_payloads_raise_format_error(payload: str) -> None:
    with pytest.raises(MetricFormatError):
        metric_from_json(payload)


def test_from_json_checks_kind() -> None:
    with pytest.raises(MetricFormatError):
        Summary.from_json(Proportion(1, 2).to_json())


def test_format_errors_are_metric_errors_and_value_errors() -> None:
    assert issubclass(MetricFormatError, MetricError)
    assert issubclass(MetricIdError, MetricError)
    assert issubclass(MetricError, ValueError)


# --------------------------------------------------------------- invariants


@pytest.mark.parametrize(
    "build",
    [
        lambda: Proportion(-1, 2),
        lambda: Proportion(1, -2),
        lambda: Proportion(1, 2, -1),
        lambda: Proportion(3, 2),
        lambda: Proportion(True, 2),
        lambda: Proportion(1.0, 2),  # type: ignore[arg-type]
        lambda: Summary(-1, 0, None, None, None, None, None, None, None),
        lambda: Summary(0, -1, None, None, None, None, None, None, None),
        # n == 0 with a statistic
        lambda: Summary(0, 0, 1.0, None, None, None, None, None, None),
        # n >= 1 with a missing statistic
        lambda: Summary(2, 0, None, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        lambda: Summary(2, 0, 1.0, 1.0, 1.0, None, 1.0, 1.0, 1.0),
        # sd rules
        lambda: Summary(1, 0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        lambda: Summary(2, 0, 1.0, None, 1.0, 1.0, 1.0, 1.0, 1.0),
        lambda: Summary(2, 0, 1.0, -0.1, 1.0, 1.0, 1.0, 1.0, 1.0),
        # not finite / not a number
        lambda: Summary(2, 0, math.nan, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        lambda: Summary(2, 0, 1.0, math.inf, 1.0, 1.0, 1.0, 1.0, 1.0),
        lambda: Summary(2, 0, "1", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),  # type: ignore[arg-type]
        # order
        lambda: Summary(3, 0, 2.0, 1.0, 2.0, 3.0, 1.0, 1.0, 3.0),
        lambda: Summary(3, 0, 2.0, 1.0, 2.0, 1.0, 3.0, 3.0, 1.0),
        lambda: Distribution(("a", "b"), (1,), 0),
        lambda: Distribution(("a", "a"), (1, 2), 0),
        lambda: Distribution(("a",), (-1,), 0),
        lambda: Distribution(("a",), (1,), -1),
        lambda: Distribution(("a",), (1.5,), 0),  # type: ignore[arg-type]
        lambda: Distribution(["a"], (1,), 0),  # type: ignore[arg-type]
        lambda: Distribution(("a",), [1], 0),  # type: ignore[arg-type]
        lambda: Distribution((1,), (1,), 0),  # type: ignore[arg-type]
    ],
)
def test_invariant_violations_are_rejected(build: Callable[[], object]) -> None:
    with pytest.raises(MetricError):
        build()


def test_metrics_are_frozen() -> None:
    proportion = Proportion(1, 2)
    with pytest.raises(AttributeError):
        proportion.k = 2  # type: ignore[misc]


def test_summary_accepts_ints_and_stores_floats() -> None:
    summary = Summary(2, 0, 1, 1, 1, 1, 1, 1, 1)
    assert all(
        isinstance(getattr(summary, name), float)
        for name in ("mean", "sd", "median", "q1", "q3", "min", "max")
    )


# ------------------------------------------------------ derived properties


def test_proportion_share() -> None:
    assert Proportion(1, 4).share == 0.25
    assert Proportion(0, 0).share is None


def test_distribution_n_and_shares() -> None:
    dist = Distribution(("a", "b", "c"), (1, 0, 3), 7)
    assert dist.n == 4
    assert dist.shares == (0.25, 0.0, 0.75)
    empty = Distribution((), (), 0)
    assert empty.n == 0
    assert empty.shares is None
    assert Distribution(("a",), (0,), 0).shares is None


def test_derived_values_are_not_stored() -> None:
    assert "share" not in Proportion(1, 2).to_dict()
    data = Distribution(("a",), (1,), 0).to_dict()
    assert "n" not in data
    assert "shares" not in data


# ------------------------------------------------------------ constructors


def test_summary_from_values_hand_computed() -> None:
    summary = Summary.from_values(pd.Series([1, 2, 3, 4]), n_missing=2)
    assert summary.n == 4
    assert summary.n_missing == 2
    assert summary.mean == 2.5
    # sample SD: sqrt(((1.5^2 + 0.5^2) * 2) / 3) = sqrt(5/3)
    assert summary.sd == pytest.approx(math.sqrt(5 / 3), abs=1e-15)
    assert summary.median == 2.5
    # linear quantiles: position 0.25*3 = 0.75 -> 1.75, position 2.25 -> 3.25
    assert summary.q1 == 1.75
    assert summary.q3 == 3.25
    assert summary.min == 1.0
    assert summary.max == 4.0


def test_summary_from_values_matches_pandas_conventions() -> None:
    values = pd.Series([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5])
    summary = Summary.from_values(values)
    assert summary.sd == pytest.approx(values.std(ddof=1), rel=1e-12)
    assert summary.q1 == pytest.approx(values.quantile(0.25), rel=1e-12)
    assert summary.median == pytest.approx(values.median(), rel=1e-12)
    assert summary.q3 == pytest.approx(values.quantile(0.75), rel=1e-12)


def test_summary_from_values_n_equals_two() -> None:
    summary = Summary.from_values(pd.Series([2, 4]))
    assert summary.sd == pytest.approx(math.sqrt(2), abs=1e-15)
    assert summary.median == 3.0


def test_summary_from_values_single_value_has_no_sd() -> None:
    summary = Summary.from_values(pd.Series([7]))
    assert summary.n == 1
    assert summary.sd is None
    assert summary.mean == summary.median == summary.q1 == summary.q3 == 7.0
    assert summary.min == summary.max == 7.0


@pytest.mark.parametrize("dtype", ["int64", "Int64", "float64", "Float64"])
def test_summary_from_values_empty(dtype: str) -> None:
    summary = Summary.from_values(pd.Series([], dtype=dtype), n_missing=5)
    assert summary == Summary(0, 5, None, None, None, None, None, None, None)


def test_summary_from_values_returns_plain_floats() -> None:
    summary = Summary.from_values(pd.Series([1, 2, 3], dtype="Int64"))
    for name in ("mean", "sd", "median", "q1", "q3", "min", "max"):
        assert type(getattr(summary, name)) is float
    assert type(summary.n) is int
    assert Summary.from_json(summary.to_json()) == summary


def test_summary_from_values_never_violates_ordering() -> None:
    rng = np.random.default_rng(0)
    for size in (2, 3, 5, 17, 100):
        for _ in range(50):
            Summary.from_values(
                pd.Series(rng.normal(size=size) * 10.0 ** int(rng.integers(-5, 5)))
            )
    Summary.from_values(pd.Series([0.1] * 3))


def test_from_values_rejects_missing_values_without_leaking_them() -> None:
    with pytest.raises(ValueError, match="1 missing value") as excinfo:
        Summary.from_values(pd.Series([1, None, 3], dtype="Int64"))
    assert "3" not in str(excinfo.value)
    with pytest.raises(ValueError, match="missing"):
        Proportion.from_mask(pd.Series([True, None], dtype="boolean"))
    with pytest.raises(ValueError, match="missing"):
        Distribution.from_values(pd.Series(["a", None]), ["a"])


def test_summary_from_values_rejects_non_numeric_without_leaking() -> None:
    with pytest.raises(TypeError) as excinfo:
        Summary.from_values(pd.Series(["secret", "x"]))
    assert "secret" not in str(excinfo.value)
    with pytest.raises(TypeError):
        Summary.from_values(pd.Series([True, False]))
    with pytest.raises(TypeError):
        Summary.from_values([1, 2, 3])  # type: ignore[arg-type]


def test_proportion_from_mask() -> None:
    assert Proportion.from_mask(pd.Series([True, False, True, True]), 2) == Proportion(
        3, 4, 2
    )
    assert Proportion.from_mask(pd.Series([], dtype=bool)) == Proportion(0, 0, 0)
    assert Proportion.from_mask(
        pd.Series([True, False], dtype="boolean")
    ) == Proportion(1, 2, 0)
    with pytest.raises(TypeError):
        Proportion.from_mask(pd.Series([1, 0]))


def test_distribution_from_values() -> None:
    values = pd.Series([2, 0, 2, 3, 2], dtype="Int64")
    dist = Distribution.from_values(values, ["0", "1", "2", "3"], n_missing=1)
    assert dist.categories == ("0", "1", "2", "3")
    assert dist.counts == (1, 0, 3, 1)
    assert dist.n == 5
    assert dist.n_missing == 1
    assert all(type(count) is int for count in dist.counts)
    assert Distribution.from_json(dist.to_json()) == dist


def test_distribution_from_values_keeps_category_order_and_text() -> None:
    dist = Distribution.from_values(pd.Series(["b", "a", "b"]), ("b", "a", "z"))
    assert dist.categories == ("b", "a", "z")
    assert dist.counts == (2, 1, 0)


def test_distribution_from_values_empty() -> None:
    dist = Distribution.from_values(pd.Series([], dtype="Int64"), ["0", "1"], 3)
    assert dist == Distribution(("0", "1"), (0, 0), 3)


def test_distribution_from_values_rejects_unknown_values_without_leaking() -> None:
    with pytest.raises(ValueError, match="1 value") as excinfo:
        Distribution.from_values(pd.Series(["a", "secret"]), ["a"])
    assert "secret" not in str(excinfo.value)


# ---------------------------------------------------------------- metric ids


@pytest.mark.parametrize(
    "metric_id",
    [
        "symptoms.phq9.severity",
        "symptoms.combined.burdened",
        "resilience.res.total.burdened",
        "a.b.c",
        "a_1.b_2.c_3.d_4",
        "0.0.0",
    ],
)
def test_valid_ids(metric_id: str) -> None:
    assert validate_metric_id(metric_id) == metric_id


@pytest.mark.parametrize(
    "metric_id",
    [
        "",
        "a",
        "a.b",
        "a.b.c.d.e",
        "A.b.c",
        "a.B.c",
        "a.b.c.D",
        "a.b-c.d",
        "a.b.c-d",
        "a..c",
        "a.b..d",
        ".a.b.c",
        "a.b.c.",
        "a.b.c..",
        "a b.c.d",
        "a.b.c\n",
        "a.b.ä",
        "a.b.٣",
        "a/b/c",
    ],
)
def test_invalid_ids_are_rejected(metric_id: str) -> None:
    with pytest.raises(MetricIdError):
        validate_metric_id(metric_id)


def test_non_string_id_is_rejected() -> None:
    with pytest.raises(MetricIdError):
        validate_metric_id(None)  # type: ignore[arg-type]


# ----------------------------------------------------------------- MetricSet


def _set() -> MetricSet:
    return MetricSet(
        {
            "symptoms.phq9.severity": Distribution(("0", "1"), (3, 2), 1),
            "demography.sample.size": Proportion(5, 5, 0),
            "resilience.res.total": PRECISE_SUMMARY,
        }
    )


def test_metric_set_mapping_behaviour() -> None:
    metrics = _set()
    assert len(metrics) == 3
    assert metrics["demography.sample.size"] == Proportion(5, 5, 0)
    assert metrics.get("demography.sample.size") == Proportion(5, 5, 0)
    assert metrics.get("missing.id.here") is None
    assert "resilience.res.total" in metrics
    with pytest.raises(KeyError):
        metrics["missing.id.here"]
    assert list(metrics) == sorted(metrics)
    assert list(metrics) == [
        "demography.sample.size",
        "resilience.res.total",
        "symptoms.phq9.severity",
    ]
    assert len(MetricSet()) == 0


def test_metric_set_is_immutable_and_independent_of_input() -> None:
    source: dict[str, Any] = {"a.b.c": Proportion(1, 2)}
    metrics = MetricSet(source)
    source["a.b.d"] = Proportion(1, 1)
    assert list(metrics) == ["a.b.c"]
    with pytest.raises(TypeError):
        metrics["a.b.d"] = Proportion(1, 1)  # type: ignore[index]
    with pytest.raises(TypeError):
        del metrics["a.b.c"]  # type: ignore[attr-defined]


def test_metric_set_equality_ignores_insertion_order() -> None:
    a = MetricSet({"a.b.c": Proportion(1, 2), "a.b.d": Proportion(2, 2)})
    b = MetricSet({"a.b.d": Proportion(2, 2), "a.b.c": Proportion(1, 2)})
    assert a == b
    assert a != MetricSet({"a.b.c": Proportion(1, 2)})


def test_metric_set_validates_ids_and_values() -> None:
    with pytest.raises(MetricIdError):
        MetricSet({"Bad.id.here": Proportion(1, 2)})
    with pytest.raises(MetricIdError):
        MetricSet({"too.short": Proportion(1, 2)})
    with pytest.raises(MetricError):
        MetricSet({"a.b.c": 3})  # type: ignore[dict-item]


def test_metric_set_round_trip_and_stable_key_order() -> None:
    metrics = _set()
    text = metrics.to_json()
    assert MetricSet.from_json(text) == metrics
    assert MetricSet.from_dict(metrics.to_dict()) == metrics
    assert list(json.loads(text)) == sorted(metrics)
    shuffled = MetricSet(dict(reversed(list(metrics.items()))))
    assert shuffled.to_json() == text
    assert MetricSet.from_json(MetricSet().to_json()) == MetricSet()


def test_metric_set_from_json_rejects_bad_input() -> None:
    with pytest.raises(MetricFormatError):
        MetricSet.from_json("nope")
    with pytest.raises(MetricFormatError):
        MetricSet.from_json("[]")
    with pytest.raises(MetricIdError):
        MetricSet.from_json(
            '{"bad": {"kind": "proportion", "k": 1, "n": 1, "n_missing": 0}}'
        )
    with pytest.raises(MetricFormatError):
        MetricSet.from_json('{"a.b.c": {"kind": "other"}}')
