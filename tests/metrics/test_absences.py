"""Absence metrics (R16): hand-made cases, wiring and legacy parity."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spot_report.features import compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    Distribution,
    MetricSet,
    Proportion,
    absences,
    compute_metrics,
    default_registry,
)
from spot_report.metrics.absences import DAYS_ID, REPORTED_ID
from spot_report.questionnaire import load_spec, spec_from_mapping
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
STRING = pd.StringDtype(na_value=pd.NA)
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
CATEGORIES = ("FE01", "FE05", "FE10", "FE20")


def frame(rows: Sequence[tuple[str | None, str | None]]) -> pd.DataFrame:
    """Responses with the columns FEHLTAGQ0 and FEHLTAGQ1 (reader dtypes)."""
    return pd.DataFrame(
        {
            "FEHLTAGQ0": pd.Series([q0 for q0, _ in rows], dtype=STRING),
            "FEHLTAGQ1": pd.Series([q1 for _, q1 in rows], dtype=STRING),
        }
    )


def compute(responses: pd.DataFrame) -> MetricSet:
    return absences.compute(responses, pd.DataFrame(index=responses.index), SPEC)


def reported(metrics: MetricSet) -> Proportion:
    metric = metrics[REPORTED_ID]
    assert isinstance(metric, Proportion)
    return metric


def days(metrics: MetricSet) -> Distribution:
    metric = metrics[DAYS_ID]
    assert isinstance(metric, Distribution)
    return metric


# Ten respondents, by hand: 6 FEJA, 3 FENE, 1 empty FEHLTAGQ0.
ROWS: list[tuple[str | None, str | None]] = [
    ("FEJA", "FE01"),
    ("FEJA", "FE01"),
    ("FEJA", "FE05"),
    ("FEJA", "FE10"),
    ("FEJA", "FE20"),
    ("FEJA", "FE20"),
    ("FENE", None),
    ("FENE", None),
    ("FENE", None),
    (None, None),
]


# --- hand-made cases ---------------------------------------------------------------


def test_any_absence_leaves_out_the_empty_answer() -> None:
    metric = reported(compute(frame(ROWS)))
    # 6 of the 9 who answered (D12); the empty answer is not counted as "no".
    assert (metric.k, metric.n, metric.n_missing) == (6, 9, 1)


def test_buckets_count_the_answers_in_spec_order() -> None:
    metric = days(compute(frame(ROWS)))
    assert metric.categories == CATEGORIES
    assert metric.counts == (2, 1, 1, 2)
    # 6 answered; the 4 respondents who were not shown the question are missing.
    assert (metric.n, metric.n_missing) == (6, 4)


def test_empty_follow_up_of_a_yes_answer_is_left_out_of_the_buckets() -> None:
    rows = [("FEJA", "FE01"), ("FEJA", None), ("FEJA", "FE05"), ("FENE", None)]
    metrics = compute(frame(rows))
    assert (reported(metrics).k, reported(metrics).n) == (3, 4)
    metric = days(metrics)
    # Legacy would divide by the 3 yes answers; D12 by the 2 answers to FEHLTAGQ1.
    assert metric.counts == (1, 1, 0, 0)
    assert (metric.n, metric.n_missing) == (2, 2)
    assert metric.shares == (0.5, 0.5, 0.0, 0.0)


def test_bucket_answer_without_a_yes_answer_is_counted() -> None:
    """The population is "answered FEHLTAGQ1" (D12), not "answered yes"."""
    rows = [("FEJA", "FE01"), ("FENE", "FE05"), (None, "FE05"), ("FEJA", "FE20")]
    metrics = compute(frame(rows))
    metric = days(metrics)
    assert metric.counts == (1, 2, 0, 1)
    assert (metric.n, metric.n_missing) == (4, 0)
    # Only the yes answers count as absence; the empty FEHLTAGQ0 is left out.
    assert (reported(metrics).k, reported(metrics).n) == (2, 3)
    assert reported(metrics).n_missing == 1


def test_yes_code_and_buckets_come_from_the_spec() -> None:
    raw = yaml.safe_load(
        (
            Path(__file__).parents[2]
            / "src/spot_report/questionnaire/specs/2026.1.yaml"
        ).read_text(encoding="utf-8")
    )
    raw["single_choice"]["FEHLTAGQ0"]["yes_code"] = "FENE"
    raw["single_choice"]["FEHLTAGQ1"]["codes"] = ["FE20", "FE10", "FE05", "FE01"]
    other = spec_from_mapping(raw)
    responses = frame(ROWS)
    metrics = absences.compute(responses, pd.DataFrame(index=responses.index), other)
    assert reported(metrics) == Proportion(3, 9, 1)
    assert days(metrics).categories == ("FE20", "FE10", "FE05", "FE01")
    assert days(metrics).counts == (2, 1, 1, 2)


def test_nobody_answered() -> None:
    metrics = compute(frame([(None, None)] * 3))
    assert reported(metrics) == Proportion(0, 0, 3)
    assert days(metrics) == Distribution(CATEGORIES, (0, 0, 0, 0), 3)


def test_no_respondents() -> None:
    metrics = compute(frame([]))
    assert reported(metrics) == Proportion(0, 0, 0)
    assert days(metrics).n == 0


def test_small_groups_are_not_suppressed() -> None:
    metrics = compute(frame([("FEJA", "FE20")]))
    assert reported(metrics) == Proportion(1, 1, 0)
    assert days(metrics).counts == (0, 0, 0, 1)


# --- registry wiring -----------------------------------------------------------------


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute(frame(ROWS))
    assert {d.id for d in absences.definitions(SPEC)} == set(metrics)
    default_registry(SPEC).check(metrics)
    assert all(d.domain == "absences" for d in absences.definitions(SPEC))
    assert all(d.since == SPEC.version for d in absences.definitions(SPEC))


def test_definition_items_are_spec_columns() -> None:
    for definition in absences.definitions(SPEC):
        for item in definition.items:
            SPEC.question(item)


def test_expected_ids() -> None:
    assert {(d.id, d.kind) for d in absences.definitions(SPEC)} == {
        ("absences.absence.reported", "proportion"),
        ("absences.days.distribution", "distribution"),
    }


# --- legacy parity ------------------------------------------------------------------


@pytest.mark.parametrize("dataset", expected_datasets())
def test_legacy_parity(dataset: str) -> None:
    responses = read_responses(FIXTURE_DIR / f"{dataset}.xlsx", "xlsx", SPEC)
    metrics = compute_metrics(responses, compute_features(responses, SPEC), SPEC)
    expected = load_expected(dataset)
    checked: set[str] = set()

    def check(key: str, new: float | None) -> None:
        assert_parity(dataset, key, new)
        checked.add(key)

    top = reported(metrics)
    check("absences.top.n", top.k)
    check("absences.top.pct", top.share)

    metric = days(metrics)
    assert metric.shares is not None
    for code, count, share in zip(
        metric.categories, metric.counts, metric.shares, strict=True
    ):
        check(f"absences.bucket.count.{code}", count)
        check(f"absences.bucket.pct.{code}", share)

    assert checked == set(expected.under("absences"))
