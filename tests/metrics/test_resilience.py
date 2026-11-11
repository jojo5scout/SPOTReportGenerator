"""Resilience metrics (R21): hand-made cases, wiring and legacy parity."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spot_report.features import compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    Distribution,
    MetricSet,
    Summary,
    compute_metrics,
    default_registry,
    resilience,
)
from spot_report.questionnaire import QuestionnaireSpec, load_spec, spec_from_mapping
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
SPEC_FILE = (
    Path(__file__).parents[2] / "src/spot_report/questionnaire/specs/2026.1.yaml"
)
RES = SPEC.scale("RES")
PHQ9 = SPEC.scale("PHQ9").columns
GAD7 = SPEC.scale("GAD7").columns

TOTAL = "resilience.res.total"
BURDENED = "resilience.res.total.burdened"
NONBURDENED = "resilience.res.total.nonburdened"
HISTOGRAM = "resilience.res.histogram"


def spread(total: int | None, columns: tuple[str, ...], top: int) -> list[int | None]:
    """Item answers (at most ``top`` each) that add up to ``total``; empty for None."""
    if total is None:
        return [None] * len(columns)
    answers = []
    for _ in columns:
        answers.append(min(top, total))
        total -= answers[-1]
    assert total == 0
    return answers


def build(
    res: list[int | None],
    phq9: list[int | None] | None = None,
    gad7: list[int | None] | None = None,
    spec: QuestionnaireSpec = SPEC,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Responses whose RES, PHQ-9 and GAD-7 sums are the given ones (one per person).

    The rows are the first rows of a fixture; only these items are replaced. A ``None``
    leaves all items of that scale empty. Symptom sums default to 0.
    """
    phq9 = phq9 if phq9 is not None else [0] * len(res)
    gad7 = gad7 if gad7 is not None else [0] * len(res)
    base = read_responses(FIXTURE_DIR / "synthetic_300.xlsx", "xlsx", SPEC)
    responses = base.head(len(res)).reset_index(drop=True)
    for sums, columns, top in (
        (res, spec.scale("RES").columns, 4),
        (phq9, PHQ9, 3),
        (gad7, GAD7, 3),
    ):
        rows = [spread(total, columns, top) for total in sums]
        for position, code in enumerate(columns):
            column = [row[position] for row in rows]
            responses[code] = pd.Series(column, dtype=pd.Int64Dtype())
    return responses, compute_features(responses, spec)


def compute(
    res: list[int | None],
    phq9: list[int | None] | None = None,
    gad7: list[int | None] | None = None,
    spec: QuestionnaireSpec = SPEC,
) -> MetricSet:
    responses, features = build(res, phq9, gad7, spec)
    return resilience.compute(responses, features, spec)


def summary(metrics: MetricSet, metric_id: str) -> Summary:
    metric = metrics[metric_id]
    assert isinstance(metric, Summary)
    return metric


def histogram(metrics: MetricSet) -> Distribution:
    metric = metrics[HISTOGRAM]
    assert isinstance(metric, Distribution)
    return metric


# Six respondents. Burdened (rows 0-2): PHQ-9 12, GAD-7 11, PHQ-9 10 (GAD-7 missing).
# Not burdened (row 3): both scores below 10. Undeterminable (rows 4-5): only GAD-7
# present and below 10 (row 4), neither score (row 5). RES sums 20 30 10 25 35 40.
RES_SUMS: list[int | None] = [20, 30, 10, 25, 35, 40]
PHQ_SUMS: list[int | None] = [12, 3, 10, 4, None, None]
GAD_SUMS: list[int | None] = [0, 11, None, 6, 2, None]


# --- hand-made cases ---------------------------------------------------------------


def test_total_summary() -> None:
    metric = summary(compute(RES_SUMS, PHQ_SUMS, GAD_SUMS), TOTAL)
    assert (metric.n, metric.n_missing) == (6, 0)
    assert metric.mean == 26.666666666666668  # 160 / 6
    assert metric.sd == pytest.approx(math.sqrt(583.3333333333334 / 5))  # ddof=1
    assert metric.median == 27.5
    assert (metric.q1, metric.q3) == (21.25, 33.75)  # linear interpolation
    assert (metric.min, metric.max) == (10.0, 40.0)


def test_burdened_is_any_cutoff_even_with_a_missing_score() -> None:
    metric = summary(compute(RES_SUMS, PHQ_SUMS, GAD_SUMS), BURDENED)
    assert (metric.n, metric.n_missing) == (3, 0)
    assert metric.mean == 20.0  # rows 0, 1, 2: 20, 30, 10
    assert metric.sd == 10.0


def test_nonburdened_needs_both_scores_below_the_cutoffs() -> None:
    # Row 3: both scores below the cut-offs. Row 4: only GAD-7 present and below its
    # cut-off; the missing PHQ-9 could be 10 or more, so the row is in no group (the
    # previous program counted it as non-burdened, ADR 0004). Row 5 has no score.
    metrics = compute(RES_SUMS, PHQ_SUMS, GAD_SUMS)
    metric = summary(metrics, NONBURDENED)
    assert (metric.n, metric.n_missing) == (1, 0)
    assert (metric.mean, metric.sd) == (25.0, None)


def test_groups_do_not_overlap_and_leave_out_respondents_without_scores() -> None:
    metrics = compute(RES_SUMS, PHQ_SUMS, GAD_SUMS)
    assert (
        summary(metrics, BURDENED).n + summary(metrics, NONBURDENED).n
        == summary(metrics, TOTAL).n - 2
    )


def test_a_cutoff_exactly_at_ten_is_burdened() -> None:
    metrics = compute([5, 6], [10, 9], [0, 9])
    assert summary(metrics, BURDENED).mean == 5.0
    assert summary(metrics, NONBURDENED).mean == 6.0


def test_an_empty_item_makes_the_sum_missing_not_partial() -> None:
    # Respondent 1 left one RES item empty (D12): no sum, counted as missing in every
    # group they belong to. The answered items are not summed alone.
    responses, features = build([20, 30, 10, 25], [12, 12, 0, 0], [0] * 4)
    responses.loc[1, RES.columns[3]] = pd.NA
    features = compute_features(responses, SPEC)
    metrics = resilience.compute(responses, features, SPEC)
    total = summary(metrics, TOTAL)
    assert (total.n, total.n_missing) == (3, 1)
    assert total.mean == 55 / 3  # not (20 + 30 + 10 + 25) / 4
    burdened = summary(metrics, BURDENED)
    assert (burdened.n, burdened.n_missing, burdened.mean) == (1, 1, 20.0)
    nonburdened = summary(metrics, NONBURDENED)
    assert (nonburdened.n, nonburdened.n_missing, nonburdened.mean) == (2, 0, 17.5)
    assert histogram(metrics).n_missing == 1


def test_single_value_has_no_sd() -> None:
    """The previous program showed 0.00; here the SD is undefined (``None``)."""
    metrics = compute([22], [11], [0])
    metric = summary(metrics, BURDENED)
    assert (metric.n, metric.mean, metric.sd, metric.median) == (1, 22.0, None, 22.0)


def test_empty_group_has_no_statistics() -> None:
    metrics = compute([22, 18], [0, 0], [0, 0])
    assert summary(metrics, BURDENED) == Summary(
        0, 0, None, None, None, None, None, None, None
    )


def test_nobody_has_a_sum() -> None:
    metrics = compute([None, None], [12, 0], [0, 0])
    assert set(metrics) == {d.id for d in resilience.definitions(SPEC)}
    assert summary(metrics, TOTAL) == Summary(
        0, 2, None, None, None, None, None, None, None
    )
    assert summary(metrics, BURDENED).n_missing == 1
    assert histogram(metrics).n == 0


def test_no_respondents() -> None:
    metrics = compute([])
    assert all(summary(metrics, i).n == 0 for i in (TOTAL, BURDENED, NONBURDENED))
    assert histogram(metrics).n == 0
    assert histogram(metrics).n_missing == 0


def test_small_groups_are_not_suppressed() -> None:
    metrics = compute([10, 20], [12, 0], [0, 0])
    assert summary(metrics, BURDENED).n == 1
    assert summary(metrics, NONBURDENED).n == 1


# --- histogram ----------------------------------------------------------------------


def test_histogram_counts_every_score_from_zero_to_forty() -> None:
    metric = histogram(compute([0, 0, 7, 40, 7, 7]))
    assert metric.categories == tuple(str(score) for score in range(41))
    assert metric.counts[0] == 2
    assert metric.counts[7] == 3
    assert metric.counts[40] == 1
    assert (metric.n, metric.n_missing) == (6, 0)
    assert sum(metric.counts) == 6


def test_histogram_leaves_out_missing_sums() -> None:
    metric = histogram(compute([12, None, 12, 13]))
    assert (metric.n, metric.n_missing) == (3, 1)
    assert (metric.counts[12], metric.counts[13]) == (2, 1)


# --- ids come from the spec ----------------------------------------------------------


def test_histogram_range_follows_the_spec() -> None:
    raw = yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))
    raw["scales"]["RES"]["range"] = [0, 3]
    other = spec_from_mapping(raw)
    assert resilience.score_categories(other) == tuple(str(i) for i in range(31))
    assert histogram(compute([0, 29, 30], spec=other)).counts[-2:] == (1, 1)


# --- registry wiring -----------------------------------------------------------------


def test_expected_ids() -> None:
    assert {d.id for d in resilience.definitions(SPEC)} == {
        "resilience.res.total",
        "resilience.res.total.burdened",
        "resilience.res.total.nonburdened",
        "resilience.res.histogram",
    }


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute(RES_SUMS, PHQ_SUMS, GAD_SUMS)
    definitions = resilience.definitions(SPEC)
    assert {d.id for d in definitions} == set(metrics)
    default_registry(SPEC).check(metrics)
    assert all(d.domain == "resilience" for d in definitions)
    assert all(d.since == SPEC.version for d in definitions)
    kinds = {d.id: d.kind for d in definitions}
    assert kinds[HISTOGRAM] == "distribution"
    assert {kinds[i] for i in (TOTAL, BURDENED, NONBURDENED)} == {"summary"}


def test_definition_items_are_the_spec_columns() -> None:
    for definition in resilience.definitions(SPEC):
        assert definition.items == RES.columns
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

    for group, metric_id in (
        ("all", TOTAL),
        ("burdened", BURDENED),
        ("nonburdened", NONBURDENED),
    ):
        metric = summary(metrics, metric_id)
        assert metric.n_missing == 0  # the fixtures are complete
        for key, value in (
            (f"resilience.res.{group}.n", metric.n),
            (f"resilience.res.{group}.mean", metric.mean),
            (f"resilience.res.{group}.sd", metric.sd),
        ):
            assert_parity(dataset, key, value)
            checked.add(key)

    distribution = histogram(metrics)
    assert distribution.n_missing == 0
    assert_parity(dataset, "resilience.res.hist.n", distribution.n)
    checked.add("resilience.res.hist.n")
    for score, count in zip(distribution.categories, distribution.counts, strict=True):
        key = f"resilience.res.hist.count.{score}"
        assert_parity(dataset, key, count)
        checked.add(key)

    assert checked == set(expected.under("resilience"))
