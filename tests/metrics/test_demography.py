"""Demography metrics (R14): hand-made cases, registry wiring and legacy parity."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spot_report.features import compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    Distribution,
    MetricError,
    MetricSet,
    compute_metrics,
    default_registry,
    demography,
)
from spot_report.metrics import compute as compute_module
from spot_report.metrics.demography import AGE_ID, GENDER_ID, LEVEL_ID
from spot_report.questionnaire import load_spec
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
STRING = pd.StringDtype(na_value=pd.NA)
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
AGES = tuple(str(age) for age in range(12, 21))


def frame(sex: list[object], level: list[object], age: list[object]) -> pd.DataFrame:
    """Demographic columns only, with the reader's dtypes."""
    return pd.DataFrame(
        {
            "DQSEX": pd.Series(sex, dtype=STRING),
            "DQSTUFE": pd.Series(level, dtype=STRING),
            "DQAGE": pd.Series(age, dtype=pd.Int64Dtype()),
        }
    )


def compute(responses: pd.DataFrame) -> MetricSet:
    return demography.compute(responses, pd.DataFrame(index=responses.index), SPEC)


def distribution(metrics: MetricSet, metric_id: str) -> Distribution:
    metric = metrics[metric_id]
    assert isinstance(metric, Distribution)
    return metric


# --- hand-made cases ---------------------------------------------------------------


def test_counts_in_spec_order_by_hand() -> None:
    responses = frame(
        sex=["W", "M", "W", "W", "D", "M"],
        level=["Gym1", "Gym4", "Gym1", "Gym2", "Gym2", "Gym2"],
        age=[12, 15, 15, 20, 15, 12],
    )
    metrics = compute(responses)

    gender = distribution(metrics, GENDER_ID)
    assert gender.categories == ("M", "W", "D")
    assert gender.counts == (2, 3, 1)
    assert (gender.n, gender.n_missing) == (6, 0)
    assert gender.shares == (2 / 6, 3 / 6, 1 / 6)

    level = distribution(metrics, LEVEL_ID)
    assert level.categories == ("Gym1", "Gym2", "Gym3", "Gym4")
    assert level.counts == (2, 3, 0, 1)

    age = distribution(metrics, AGE_ID)
    assert age.categories == AGES
    assert age.counts == (2, 0, 0, 3, 0, 0, 0, 0, 1)  # 12 twice, 15 three times, 20
    assert (age.n, age.n_missing) == (6, 0)


def test_empty_answers_are_left_out_of_the_denominator() -> None:
    """D12: an empty answer is not shown; the share is of the answered respondents."""
    responses = frame(
        sex=["M", None, "W", "W"],
        level=[None, None, "Gym3", "Gym3"],
        age=[None, 14, 14, None],
    )
    metrics = compute(responses)

    gender = distribution(metrics, GENDER_ID)
    assert gender.counts == (1, 2, 0)
    assert (gender.n, gender.n_missing) == (3, 1)
    # The legacy program would divide by 4 (all respondents); D12 divides by 3.
    assert gender.shares == (1 / 3, 2 / 3, 0.0)

    level = distribution(metrics, LEVEL_ID)
    assert level.counts == (0, 0, 2, 0)
    assert (level.n, level.n_missing) == (2, 2)

    age = distribution(metrics, AGE_ID)
    assert age.counts[AGES.index("14")] == 2
    assert (age.n, age.n_missing) == (2, 2)


def test_every_question_unanswered() -> None:
    metrics = compute(frame([None, None], [None, None], [None, None]))
    for metric_id in (GENDER_ID, LEVEL_ID, AGE_ID):
        metric = distribution(metrics, metric_id)
        assert (metric.n, metric.n_missing, metric.shares) == (0, 2, None)


def test_no_respondents() -> None:
    metrics = compute(frame([], [], []))
    assert distribution(metrics, GENDER_ID).counts == (0, 0, 0)
    assert distribution(metrics, GENDER_ID).n_missing == 0


def test_small_groups_are_not_suppressed() -> None:
    gender = distribution(compute(frame(["D"], ["Gym1"], [12])), GENDER_ID)
    assert gender.counts == (0, 0, 1)


def test_age_outside_the_spec_range_is_an_error_without_values() -> None:
    responses = frame(["M"], ["Gym1"], [47])
    with pytest.raises(ValueError, match="outside categories") as error:
        compute(responses)
    assert "47" not in str(error.value)


# --- registry wiring -----------------------------------------------------------------


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute(frame(["M"], ["Gym1"], [12]))
    assert {d.id for d in demography.definitions(SPEC)} == set(metrics)
    default_registry(SPEC).check(metrics)
    assert all(d.domain == "demography" for d in demography.definitions(SPEC))
    assert all(d.since == SPEC.version for d in demography.definitions(SPEC))


def test_definition_items_are_spec_columns() -> None:
    for definition in demography.definitions(SPEC):
        for item in definition.items:
            SPEC.question(item)


def test_compute_metrics_merges_the_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only this domain, so that the hand-made frame needs no other columns.
    monkeypatch.setattr(compute_module, "DOMAINS", (demography,))
    responses = frame(["M", "W"], ["Gym1", "Gym2"], [12, 13])
    assert compute_metrics(responses, pd.DataFrame(index=responses.index), SPEC) == (
        compute(responses)
    )


# --- legacy parity ------------------------------------------------------------------


def _read(dataset: str) -> pd.DataFrame:
    return read_responses(FIXTURE_DIR / f"{dataset}.xlsx", "xlsx", SPEC)


@pytest.mark.parametrize("dataset", expected_datasets())
def test_legacy_parity(dataset: str) -> None:
    responses = _read(dataset)
    features = compute_features(responses, SPEC)
    metrics = compute_metrics(responses, features, SPEC)
    expected = load_expected(dataset)
    checked = set()

    gender = distribution(metrics, GENDER_ID)
    # `demography.all` is the number of respondents: answered plus left out.
    assert_parity(dataset, "demography.all", gender.n + gender.n_missing)
    checked.add("demography.all")

    for prefix, metric_id in (("gender", GENDER_ID), ("level", LEVEL_ID)):
        metric = distribution(metrics, metric_id)
        assert metric.shares is not None
        for category, count, share in zip(
            metric.categories, metric.counts, metric.shares, strict=True
        ):
            for kind, new in (("count", count), ("pct", share)):
                key = f"demography.{prefix}.{kind}.{category}"
                assert_parity(dataset, key, new)
                checked.add(key)

    # The legacy age chart lists only ages that occur; the others have no key.
    age = distribution(metrics, AGE_ID)
    for category, count in zip(age.categories, age.counts, strict=True):
        key = f"demography.age_chart.count.{category}"
        if key in expected:
            assert_parity(dataset, key, count)
            checked.add(key)
        else:
            assert count == 0, key

    assert checked == set(expected.under("demography")) | {"demography.all"}


def test_duplicate_metric_ids_across_domains_are_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compute_module, "DOMAINS", (demography, demography))
    responses = frame(["M"], ["Gym1"], [12])
    with pytest.raises(MetricError, match="computed twice"):
        compute_metrics(responses, pd.DataFrame(index=responses.index), SPEC)
