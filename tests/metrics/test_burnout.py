"""Burnout metrics (R20): hand-made cases, wiring and legacy parity."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spot_report.features import compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    MetricSet,
    Summary,
    burnout,
    compute_metrics,
    default_registry,
)
from spot_report.questionnaire import QuestionnaireSpec, load_spec, spec_from_mapping
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
SPEC_FILE = (
    Path(__file__).parents[2] / "src/spot_report/questionnaire/specs/2026.1.yaml"
)
SBI = SPEC.scale("SBI")
EXHAUSTION = SBI.subscale("EXHAUSTION").columns  # four items
CYNICISM = SBI.subscale("CYNICISM").columns  # five items

Items = list[list[int | None]]


def build(
    exhaustion: Items,
    cynicism: Items,
    spec: QuestionnaireSpec = SPEC,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Responses with the given item answers (one inner list per respondent).

    The rows are the first rows of a fixture; only the SBI columns are replaced.
    """
    base = read_responses(FIXTURE_DIR / "synthetic_300.xlsx", "xlsx", SPEC)
    responses = base.head(len(exhaustion)).reset_index(drop=True)
    sbi = spec.scale("SBI")
    for columns, rows in (
        (sbi.subscale(sbi.subscales[0].name).columns, exhaustion),
        (sbi.subscale(sbi.subscales[1].name).columns, cynicism),
    ):
        for position, code in enumerate(columns):
            column = [row[position] for row in rows]
            responses[code] = pd.Series(column, dtype=pd.Int64Dtype())
    return responses, compute_features(responses, spec)


def compute(
    exhaustion: Items, cynicism: Items, spec: QuestionnaireSpec = SPEC
) -> MetricSet:
    responses, features = build(exhaustion, cynicism, spec)
    return burnout.compute(responses, features, spec)


def summary(metrics: MetricSet, metric_id: str) -> Summary:
    metric = metrics[metric_id]
    assert isinstance(metric, Summary)
    return metric


# Four respondents.
#   exhaustion sums 10 0 20 9    cynicism sums 5 0 25 15    totals 15 0 45 24
EXHAUSTION_ROWS: Items = [[1, 2, 3, 4], [0, 0, 0, 0], [5, 5, 5, 5], [2, 2, 2, 3]]
CYNICISM_ROWS: Items = [
    [1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0],
    [5, 5, 5, 5, 5],
    [3, 3, 3, 3, 3],
]


# --- hand-made cases ---------------------------------------------------------------


def test_exhaustion_summary() -> None:
    metric = summary(compute(EXHAUSTION_ROWS, CYNICISM_ROWS), "burnout.sbi.exhaustion")
    assert (metric.n, metric.n_missing) == (4, 0)
    assert metric.mean == pytest.approx(9.75)
    assert metric.sd == pytest.approx(math.sqrt(200.75 / 3))  # ddof=1
    assert metric.median == 9.5
    assert (metric.q1, metric.q3) == (6.75, 12.5)  # linear interpolation
    assert (metric.min, metric.max) == (0.0, 20.0)


def test_cynicism_summary() -> None:
    metric = summary(compute(EXHAUSTION_ROWS, CYNICISM_ROWS), "burnout.sbi.cynicism")
    assert (metric.n, metric.n_missing) == (4, 0)
    assert metric.mean == pytest.approx(11.25)
    assert metric.sd == pytest.approx(math.sqrt(368.75 / 3))
    assert metric.median == 10.0
    assert (metric.min, metric.max) == (0.0, 25.0)


def test_total_sums_all_nine_items() -> None:
    metric = summary(compute(EXHAUSTION_ROWS, CYNICISM_ROWS), "burnout.sbi.total")
    assert (metric.n, metric.n_missing) == (4, 0)
    assert metric.mean == 21.0  # (15 + 0 + 45 + 24) / 4
    assert metric.sd == pytest.approx(math.sqrt(354))  # sum of squares 1062 / 3
    assert metric.median == 19.5
    assert (metric.min, metric.max) == (0.0, 45.0)


def test_each_subscale_is_read_from_its_own_items() -> None:
    # Only the exhaustion items change; the cynicism summary stays the same.
    other = [[5, 5, 5, 5]] * 4
    first = compute(EXHAUSTION_ROWS, CYNICISM_ROWS)
    second = compute(other, CYNICISM_ROWS)
    assert summary(second, "burnout.sbi.exhaustion").mean == 20.0
    assert summary(second, "burnout.sbi.cynicism") == summary(
        first, "burnout.sbi.cynicism"
    )
    assert summary(second, "burnout.sbi.total").mean == 20.0 + 11.25


def test_an_empty_item_makes_that_sum_missing_not_partial() -> None:
    # Respondent 3 left one exhaustion item empty (D12): no exhaustion sum and no
    # total, but the cynicism sum exists. The answered items are not summed alone.
    exhaustion: Items = [*EXHAUSTION_ROWS[:3], [2, None, 2, 3]]
    metrics = compute(exhaustion, CYNICISM_ROWS)
    exhaustion_summary = summary(metrics, "burnout.sbi.exhaustion")
    assert (exhaustion_summary.n, exhaustion_summary.n_missing) == (3, 1)
    assert exhaustion_summary.mean == 10.0  # (10 + 0 + 20) / 3
    cynicism_summary = summary(metrics, "burnout.sbi.cynicism")
    assert (cynicism_summary.n, cynicism_summary.n_missing) == (4, 0)
    assert cynicism_summary.mean == 11.25
    total = summary(metrics, "burnout.sbi.total")
    assert (total.n, total.n_missing) == (3, 1)
    assert total.mean == 20.0  # (15 + 0 + 45) / 3


def test_empty_answers_are_not_zero() -> None:
    cynicism: Items = [[None, 1, 1, 1, 1], *CYNICISM_ROWS[1:]]
    metrics = compute(EXHAUSTION_ROWS, cynicism)
    cynicism_summary = summary(metrics, "burnout.sbi.cynicism")
    assert (cynicism_summary.n, cynicism_summary.n_missing) == (3, 1)
    assert cynicism_summary.mean == 40 / 3  # not (4 + 0 + 25 + 15) / 4


def test_single_value_has_no_sd() -> None:
    """The previous program showed 0.00; here the SD is undefined (``None``)."""
    metrics = compute([[1, 2, 3, 4]], [[1, 1, 1, 1, 1]])
    for metric_id, mean in (
        ("burnout.sbi.exhaustion", 10.0),
        ("burnout.sbi.cynicism", 5.0),
        ("burnout.sbi.total", 15.0),
    ):
        metric = summary(metrics, metric_id)
        assert (metric.n, metric.mean, metric.sd) == (1, mean, None)
        assert metric.median == mean


def test_nobody_has_a_sum() -> None:
    metrics = compute([[None] * 4] * 2, [[None] * 5] * 2)
    assert set(metrics) == {d.id for d in burnout.definitions(SPEC)}
    for metric_id in metrics:
        assert summary(metrics, metric_id) == Summary(
            0, 2, None, None, None, None, None, None, None
        )


def test_no_respondents() -> None:
    metrics = compute([], [])
    assert all(summary(metrics, metric_id).n == 0 for metric_id in metrics)


def test_small_groups_are_not_suppressed() -> None:
    metrics = compute([[1, 1, 1, 1], [5, 5, 5, 5]], [[0] * 5, [5] * 5])
    assert summary(metrics, "burnout.sbi.total").n == 2


# --- ids come from the spec ----------------------------------------------------------


def test_subscale_ids_are_derived_from_the_spec() -> None:
    raw = yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))
    subscales = raw["scales"]["SBI"]["subscales"]
    subscales["BETA"] = subscales.pop("CYNICISM")
    other = spec_from_mapping(raw)
    assert [d.id for d in burnout.definitions(other)] == [
        "burnout.sbi.exhaustion",
        "burnout.sbi.beta",
        "burnout.sbi.total",
    ]
    metrics = compute(EXHAUSTION_ROWS, CYNICISM_ROWS, other)
    assert set(metrics) == {d.id for d in burnout.definitions(other)}
    assert summary(metrics, "burnout.sbi.beta").mean == 11.25


# --- registry wiring -----------------------------------------------------------------


def test_expected_ids() -> None:
    assert {d.id for d in burnout.definitions(SPEC)} == {
        "burnout.sbi.exhaustion",
        "burnout.sbi.cynicism",
        "burnout.sbi.total",
    }


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute(EXHAUSTION_ROWS, CYNICISM_ROWS)
    definitions = burnout.definitions(SPEC)
    assert {d.id for d in definitions} == set(metrics)
    default_registry(SPEC).check(metrics)
    assert all(d.domain == "burnout" for d in definitions)
    assert all(d.kind == "summary" for d in definitions)
    assert all(d.since == SPEC.version for d in definitions)


def test_definition_items_are_the_spec_columns() -> None:
    by_id = {d.id: d for d in burnout.definitions(SPEC)}
    assert by_id["burnout.sbi.exhaustion"].items == EXHAUSTION
    assert by_id["burnout.sbi.cynicism"].items == CYNICISM
    assert by_id["burnout.sbi.total"].items == SBI.columns
    for definition in by_id.values():
        for code in definition.items:
            SPEC.question(code)


# --- legacy parity ------------------------------------------------------------------


@pytest.mark.parametrize("dataset", expected_datasets())
def test_legacy_parity(dataset: str) -> None:
    responses = read_responses(FIXTURE_DIR / f"{dataset}.xlsx", "xlsx", SPEC)
    features = compute_features(responses, SPEC)
    metrics = compute_metrics(responses, features, SPEC)
    expected = load_expected(dataset)
    checked: set[str] = set()

    for segment in ("exhaustion", "cynicism", "total"):
        metric = summary(metrics, f"burnout.sbi.{segment}")
        assert metric.n_missing == 0  # the fixtures are complete
        for statistic, value in (("mean", metric.mean), ("sd", metric.sd)):
            key = f"burnout.sbi.{statistic}.{segment}"
            assert_parity(dataset, key, value)
            checked.add(key)

    assert checked == set(expected.under("burnout"))
