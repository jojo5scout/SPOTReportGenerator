"""Stigma metrics (R19): hand-made cases, wiring and legacy parity."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from spot_report.features import compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    MetricSet,
    Summary,
    compute_metrics,
    default_registry,
    stigma,
)
from spot_report.metrics.stats import box_whiskers
from spot_report.metrics.stigma import BURDENED_SUBGROUP, item_id
from spot_report.questionnaire import load_spec
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
ITEMS = SPEC.scale("STIG").columns
BOOLEAN = pd.BooleanDtype()


def build(
    columns: dict[str, list[int | None]], burdened: list[bool | None]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Responses with the given stigma items and a feature table with ``burdened``.

    Items not given are filled with 5. The rows are the first rows of a fixture; only
    the columns the domain reads are replaced.
    """
    base = read_responses(FIXTURE_DIR / "synthetic_300.xlsx", "xlsx", SPEC)
    responses = base.head(len(burdened)).reset_index(drop=True)
    for code in ITEMS:
        values = columns.get(code, [5] * len(burdened))
        responses[code] = pd.Series(values, dtype=pd.Int64Dtype())
    features = compute_features(responses, SPEC)
    features["burdened"] = pd.Series(burdened, dtype=BOOLEAN)
    return responses, features


def compute(
    columns: dict[str, list[int | None]], burdened: list[bool | None]
) -> MetricSet:
    responses, features = build(columns, burdened)
    return stigma.compute(responses, features, SPEC)


def summary(metrics: MetricSet, metric_id: str) -> Summary:
    metric = metrics[metric_id]
    assert isinstance(metric, Summary)
    return metric


# Eight respondents. Item 1 takes 1 2 3 4 5 6 7 9; the burdened ones are rows 0, 2, 4,
# 6 and 7 (answers 1 3 5 7 9), row 3 is undeterminable (NA), rows 1 and 5 are not
# burdened.
Q1 = [1, 2, 3, 4, 5, 6, 7, 9]
BURDENED = [True, False, True, None, True, False, True, True]


# --- hand-made cases ---------------------------------------------------------------


def test_summary_of_all_respondents() -> None:
    metric = summary(compute({ITEMS[0]: Q1}, BURDENED), item_id(1))
    assert (metric.n, metric.n_missing) == (8, 0)
    assert metric.mean == pytest.approx(4.625)  # 37 / 8
    assert metric.sd == pytest.approx(math.sqrt(7.125))  # ddof=1, sum of squares 49.875
    assert metric.median == 4.5
    assert (metric.q1, metric.q3) == (2.75, 6.25)  # linear interpolation
    assert (metric.min, metric.max) == (1.0, 9.0)


def test_summary_of_the_burdened_subgroup() -> None:
    metric = summary(compute({ITEMS[0]: Q1}, BURDENED), item_id(1, BURDENED_SUBGROUP))
    # Answers 1 3 5 7 9: undeterminable and unburdened respondents are not in the group.
    assert (metric.n, metric.n_missing) == (5, 0)
    assert metric.mean == 5.0
    assert metric.sd == pytest.approx(math.sqrt(10))  # (16 + 4 + 0 + 4 + 16) / 4
    assert (metric.q1, metric.median, metric.q3) == (3.0, 5.0, 7.0)


def test_each_item_is_read_from_its_own_column() -> None:
    columns = {code: [position] * 3 for position, code in enumerate(ITEMS, start=1)}
    metrics = compute(columns, [True, False, None])
    for position in range(1, len(ITEMS) + 1):
        assert summary(metrics, item_id(position)).mean == position
        assert summary(metrics, item_id(position, BURDENED_SUBGROUP)).n == 1


def test_empty_answers_are_missing_not_zero() -> None:
    # Row 1 (not burdened) and row 2 (burdened) left item 2 empty (D12).
    columns = {ITEMS[1]: [4, None, None, 6]}
    metrics = compute(columns, [True, False, True, True])
    everyone = summary(metrics, item_id(2))
    assert (everyone.n, everyone.n_missing, everyone.mean) == (2, 2, 5.0)
    burdened = summary(metrics, item_id(2, BURDENED_SUBGROUP))
    assert (burdened.n, burdened.n_missing, burdened.mean) == (2, 1, 5.0)


def test_single_value_has_no_sd() -> None:
    """The previous program printed "nan"; here the SD is undefined (``None``)."""
    metrics = compute({ITEMS[0]: [3, 7]}, [True, False])
    burdened = summary(metrics, item_id(1, BURDENED_SUBGROUP))
    assert (burdened.n, burdened.mean, burdened.sd) == (1, 3.0, None)
    assert burdened.median == 3.0


def test_empty_subgroup_is_computed_with_n_zero() -> None:
    metrics = compute({}, [False, None, False])
    burdened = summary(metrics, item_id(3, BURDENED_SUBGROUP))
    assert burdened == Summary(0, 0, None, None, None, None, None, None, None)
    assert summary(metrics, item_id(3)).n == 3


def test_nobody_answered_an_item() -> None:
    metrics = compute({ITEMS[4]: [None, None]}, [True, True])
    assert summary(metrics, item_id(5)).n_missing == 2
    assert summary(metrics, item_id(5)).mean is None


def test_no_respondents() -> None:
    metrics = compute({}, [])
    assert summary(metrics, item_id(1)).n == 0
    assert summary(metrics, item_id(1, BURDENED_SUBGROUP)).n == 0


def test_small_groups_are_not_suppressed() -> None:
    metrics = compute({ITEMS[0]: [8]}, [True])
    assert summary(metrics, item_id(1, BURDENED_SUBGROUP)).mean == 8.0


# --- registry wiring -----------------------------------------------------------------


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute({}, [True, False])
    assert {d.id for d in stigma.definitions(SPEC)} == set(metrics)
    default_registry(SPEC).check(metrics)
    assert all(d.domain == "stigma" for d in stigma.definitions(SPEC))
    assert all(d.kind == "summary" for d in stigma.definitions(SPEC))
    assert all(d.since == SPEC.version for d in stigma.definitions(SPEC))


def test_expected_ids() -> None:
    expected = {f"stigma.stig.item{n}" for n in range(1, 6)}
    expected |= {f"{metric_id}.burdened" for metric_id in expected}
    assert {d.id for d in stigma.definitions(SPEC)} == expected


def test_definition_items_are_the_spec_columns_in_order() -> None:
    by_id = {d.id: d for d in stigma.definitions(SPEC)}
    for position, code in enumerate(ITEMS, start=1):
        assert by_id[item_id(position)].items == (code,)
        assert by_id[item_id(position, BURDENED_SUBGROUP)].items == (code,)
        SPEC.question(code)


# --- legacy parity ------------------------------------------------------------------


@pytest.mark.parametrize("dataset", expected_datasets())
def test_legacy_parity(dataset: str) -> None:
    responses = read_responses(FIXTURE_DIR / f"{dataset}.xlsx", "xlsx", SPEC)
    features = compute_features(responses, SPEC)
    metrics = compute_metrics(responses, features, SPEC)
    expected = load_expected(dataset)
    checked: set[str] = set()

    def check(key: str, new: float | None) -> None:
        assert_parity(dataset, key, new)
        checked.add(key)

    burdened = features["burdened"].fillna(False).astype(bool)
    for position, code in enumerate(ITEMS, start=1):
        legacy = f"Q{position}"
        everyone = summary(metrics, item_id(position))
        check(f"stigma.all.stats.mean.{legacy}", everyone.mean)
        check(f"stigma.all.stats.sd.{legacy}", everyone.sd)
        for group, metric, values in (
            ("all", everyone, responses[code]),
            (
                "burdened",
                summary(metrics, item_id(position, BURDENED_SUBGROUP)),
                responses[code][burdened],
            ),
        ):
            prefix = f"stigma.{group}.chart.box.{legacy}"
            check(f"{prefix}.n", metric.n)
            check(f"{prefix}.median", metric.median)
            check(f"{prefix}.q1", metric.q1)
            check(f"{prefix}.q3", metric.q3)
            # Whiskers are chart geometry: tested through the helper the chart uses.
            whislo, whishi = box_whiskers(values.dropna().to_numpy(dtype="float64"))
            check(f"{prefix}.whislo", whislo)
            check(f"{prefix}.whishi", whishi)

    assert checked == set(expected.under("stigma"))
