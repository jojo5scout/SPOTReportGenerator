"""PatternCounts: invariants, construction from selections, JSON and top_patterns."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from spot_report.metrics import (
    MetricFormatError,
    MetricSet,
    PatternCounts,
    metric_from_dict,
    metric_from_json,
    top_patterns,
)
from spot_report.metrics.types import METRIC_KINDS, METRIC_TYPES

OPTIONS = ("A", "B", "C")
EXAMPLE = PatternCounts(
    OPTIONS, ((), ("A",), ("C",), ("A", "B"), ("A", "B", "C")), (4, 3, 1, 2, 1), 5
)


def selections(rows: list[tuple[bool, bool, bool]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(OPTIONS), dtype=bool)


# --- round trip --------------------------------------------------------------------


@pytest.mark.parametrize(
    "metric",
    [EXAMPLE, PatternCounts((), (), (), 2), PatternCounts(OPTIONS, ((),), (7,), 0)],
)
def test_round_trip_dict_and_json(metric: PatternCounts) -> None:
    assert metric_from_dict(metric.to_dict()) == metric
    assert PatternCounts.from_dict(metric.to_dict()) == metric
    text = metric.to_json()
    assert metric_from_json(text) == metric
    assert PatternCounts.from_json(text) == metric
    assert metric_from_json(text).to_json() == text
    json.loads(text, parse_constant=lambda name: pytest.fail(f"non-finite {name}"))


def test_json_layout() -> None:
    metric = PatternCounts(("A", "B"), ((), ("B",), ("A", "B")), (2, 1, 3), 1)
    assert metric.to_dict() == {
        "kind": "pattern_counts",
        "options": ["A", "B"],
        "patterns": [[], ["B"], ["A", "B"]],
        "counts": [2, 1, 3],
        "n_missing": 1,
    }
    assert metric.to_json() == (
        '{"kind":"pattern_counts","options":["A","B"],'
        '"patterns":[[],["B"],["A","B"]],"counts":[2,1,3],"n_missing":1}'
    )


def test_registered_as_a_kind() -> None:
    assert PatternCounts in METRIC_TYPES
    assert METRIC_KINDS["pattern_counts"] is PatternCounts


def test_in_a_metric_set() -> None:
    metrics = MetricSet({"diagnoses.help_patterns.combinations": EXAMPLE})
    assert MetricSet.from_json(metrics.to_json()) == metrics


GOOD: dict[str, Any] = {
    "kind": "pattern_counts",
    "options": ["A", "B"],
    "patterns": [["A"]],
    "counts": [1],
    "n_missing": 0,
}


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "distribution"},
        {"options": "AB"},
        {"patterns": ["A"]},
        {"patterns": "A"},
        {"counts": 1},
        {"counts": [1.5]},
        {"counts": [True]},
        {"n_missing": -1},
        {"n_missing": None},
        {"options": ["A", 2]},
        {"patterns": [["Z"]], "counts": [1]},
        {"patterns": [["A"], ["A"]], "counts": [1, 1]},
    ],
)
def test_malformed_payloads_raise_format_error(change: dict[str, Any]) -> None:
    with pytest.raises(MetricFormatError):
        metric_from_dict(GOOD | change)


@pytest.mark.parametrize("missing", ["options", "patterns", "counts", "n_missing"])
def test_missing_and_extra_keys(missing: str) -> None:
    payload = {k: v for k, v in GOOD.items() if k != missing}
    with pytest.raises(MetricFormatError):
        metric_from_dict(payload)
    with pytest.raises(MetricFormatError):
        metric_from_dict(GOOD | {"extra": 1})
    metric_from_dict(GOOD)


# --- invariants --------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: PatternCounts(("A", "A"), (), (), 0),  # duplicate options
        lambda: PatternCounts(("",), (), (), 0),
        lambda: PatternCounts(OPTIONS, (("Z",),), (1,), 0),  # unknown option
        lambda: PatternCounts(OPTIONS, (("A", "A"),), (1,), 0),  # option twice
        lambda: PatternCounts(OPTIONS, (("B", "A"),), (1,), 0),  # not in option order
        lambda: PatternCounts(OPTIONS, (("A",), ("A",)), (1, 2), 0),  # twice
        lambda: PatternCounts(
            OPTIONS, (("A", "B"), ("A",)), (1, 1), 0
        ),  # not canonical
        lambda: PatternCounts(OPTIONS, (("B",), ("A",)), (1, 1), 0),  # not canonical
        lambda: PatternCounts(OPTIONS, (("A",),), (1, 2), 0),  # length mismatch
        lambda: PatternCounts(OPTIONS, (("A",),), (0,), 0),  # only observed patterns
        lambda: PatternCounts(OPTIONS, (("A",),), (-1,), 0),
        lambda: PatternCounts(OPTIONS, (("A",),), (1,), -1),
        lambda: PatternCounts(OPTIONS, [("A",)], (1,), 0),  # type: ignore[arg-type]
        lambda: PatternCounts(list(OPTIONS), (), (), 0),  # type: ignore[arg-type]
    ],
)
def test_invariant_violations_are_rejected(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - MetricError is a ValueError
        build()


def test_metrics_are_frozen() -> None:
    with pytest.raises(AttributeError):
        EXAMPLE.n_missing = 1  # type: ignore[misc]


# --- derived values ----------------------------------------------------------------


def test_n_count_of_and_option_counts() -> None:
    assert EXAMPLE.n == 11  # 4 + 3 + 1 + 2 + 1, the empty combination included
    assert EXAMPLE.count_of(()) == 4
    assert EXAMPLE.count_of(["A", "B"]) == 2
    assert EXAMPLE.count_of(("B",)) == 0  # not observed
    # Respondents per option: A in A, AB, ABC; B in AB, ABC; C in C, ABC.
    assert EXAMPLE.option_counts == (3 + 2 + 1, 2 + 1, 1 + 1)
    assert PatternCounts((), (), (), 3).n == 0
    assert PatternCounts((), (), (), 3).option_counts == ()


def test_derived_values_are_not_stored() -> None:
    assert set(EXAMPLE.to_dict()) == {
        "kind",
        "options",
        "patterns",
        "counts",
        "n_missing",
    }


# --- from_selections ---------------------------------------------------------------


def test_from_selections_by_hand() -> None:
    table = selections(
        [
            (True, False, False),
            (False, False, False),
            (True, True, False),
            (True, False, False),
            (False, False, True),
            (True, True, False),
            (False, False, False),
            (True, True, True),
        ]
    )
    metric = PatternCounts.from_selections(table, n_missing=2)
    assert metric.options == OPTIONS
    assert metric.patterns == ((), ("A",), ("C",), ("A", "B"), ("A", "B", "C"))
    assert metric.counts == (2, 2, 1, 2, 1)
    assert (metric.n, metric.n_missing) == (8, 2)


def test_from_selections_accepts_nullable_booleans_and_keeps_column_order() -> None:
    table = pd.DataFrame(
        {"Z": [True, False], "M": [True, True]}, dtype=pd.BooleanDtype()
    )
    metric = PatternCounts.from_selections(table)
    assert metric.options == ("Z", "M")
    assert metric.patterns == (("M",), ("Z", "M"))
    assert metric.counts == (1, 1)


def test_from_selections_without_respondents_or_options() -> None:
    assert PatternCounts.from_selections(selections([])) == PatternCounts(
        OPTIONS, (), (), 0
    )
    no_options = PatternCounts.from_selections(pd.DataFrame(index=range(3)))
    assert (no_options.options, no_options.patterns, no_options.counts) == (
        (),
        ((),),
        (3,),
    )


def test_from_selections_rejects_bad_input_without_leaking() -> None:
    with pytest.raises(TypeError):
        PatternCounts.from_selections(pd.Series([True]))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="boolean"):
        PatternCounts.from_selections(pd.DataFrame({"A": ["x", "y"]}))
    with pytest.raises(ValueError, match="missing"):
        PatternCounts.from_selections(
            pd.DataFrame({"A": [True, pd.NA]}, dtype=pd.BooleanDtype())
        )


# --- top_patterns ------------------------------------------------------------------


def test_top_patterns_orders_by_count_then_codes() -> None:
    metric = PatternCounts(
        ("S", "P", "Q"),
        (("S",), ("P",), ("Q",), ("S", "P"), ("S", "Q"), ("P", "Q")),
        (5, 9, 9, 2, 2, 2),
    )
    # Highest count first; the tie between P and Q is broken by the code as text.
    assert top_patterns(metric, 1, 2) == ((("P",), 9), (("Q",), 9))
    assert top_patterns(metric, 1, 3) == ((("P",), 9), (("Q",), 9), (("S",), 5))
    # All pairs tie: compared code by code, as text.
    assert top_patterns(metric, 2, 2) == ((("P", "Q"), 2), (("S", "P"), 2))
    # Fewer combinations than k, none of that size, k = 0.
    assert top_patterns(metric, 2, 10) == (
        (("P", "Q"), 2),
        (("S", "P"), 2),
        (("S", "Q"), 2),
    )
    assert top_patterns(metric, 3, 2) == ()
    assert top_patterns(metric, 1, 0) == ()


def test_top_patterns_of_the_empty_combination() -> None:
    assert top_patterns(EXAMPLE, 0, 1) == (((), 4),)


def test_top_patterns_rejects_negative_arguments() -> None:
    with pytest.raises(ValueError, match="negative"):
        top_patterns(EXAMPLE, -1, 1)
    with pytest.raises(ValueError, match="negative"):
        top_patterns(EXAMPLE, 1, -1)
