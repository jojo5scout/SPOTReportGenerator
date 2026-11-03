"""Symptom metrics (R17): hand-made cases, wiring and legacy parity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spot_report.features import (
    GAD7_SEVERITY_CATEGORIES,
    PHQ9_SEVERITY_CATEGORIES,
    compute_features,
)
from spot_report.ingest import read_responses
from spot_report.metrics import (
    Distribution,
    MetricSet,
    Proportion,
    compute_metrics,
    default_registry,
    symptoms,
)
from spot_report.metrics.symptoms import (
    COMBINED_ID,
    GAD7_CUTOFF_ID,
    GAD7_SEVERITY_ANXIETY_ID,
    GAD7_SEVERITY_ID,
    IMPAIRMENT_DISTRIBUTION_ID,
    IMPAIRMENT_ELEVATED_ID,
    ITEM9_DISTRIBUTION_ID,
    ITEM9_ELEVATED_ID,
    PHQ9_CUTOFF_ID,
    PHQ9_SEVERITY_DEPRESSION_ID,
    PHQ9_SEVERITY_ID,
)
from spot_report.questionnaire import load_spec, spec_from_mapping
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
STRING = pd.StringDtype(na_value=pd.NA)
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
PHQ9_ITEMS = SPEC.scale("PHQ9").columns
GAD7_ITEMS = SPEC.scale("GAD7").columns
DEPRESSION = "DIAGQ1[DEPR]"
ANXIETY = "DIAGQ1[ANGS]"


@dataclass(frozen=True)
class Person:
    """One respondent; ``None`` means the score (or the answer) is missing."""

    phq9: int | None
    item9: int
    gad7: int | None
    impairment: int | None
    depression: bool = False
    anxiety: bool = False


def spread(total: int, count: int) -> list[int]:
    """Item values 0-3 with the given sum, filled from the first item."""
    items = []
    for _ in range(count):
        items.append(min(3, total))
        total -= items[-1]
    assert total == 0
    return items


def responses_for(people: Sequence[Person]) -> pd.DataFrame:
    """Complete responses (first rows of a fixture) with the symptom columns replaced.

    A missing PHQ-9 or GAD-7 score is one empty item (the item 9 answer stays).
    """
    base = read_responses(FIXTURE_DIR / "synthetic_300.xlsx", "xlsx", SPEC)
    responses = base.head(len(people)).reset_index(drop=True)
    columns: dict[str, list[object]] = {code: [] for code in PHQ9_ITEMS + GAD7_ITEMS}
    for person in people:
        phq9 = (
            [None, *spread(0, 7)]
            if person.phq9 is None
            else spread(person.phq9 - person.item9, 8)
        )
        gad7 = [None, *spread(0, 6)] if person.gad7 is None else spread(person.gad7, 7)
        for code, value in zip(PHQ9_ITEMS, [*phq9, person.item9], strict=True):
            columns[code].append(value)
        for code, value in zip(GAD7_ITEMS, gad7, strict=True):
            columns[code].append(value)
    for code, values in columns.items():
        responses[code] = pd.Series(values, dtype=pd.Int64Dtype())
    responses["SIPHQ"] = pd.Series(
        [p.impairment for p in people], dtype=pd.Int64Dtype()
    )
    responses[DEPRESSION] = pd.Series(
        ["Y" if p.depression else None for p in people], dtype=STRING
    )
    responses[ANXIETY] = pd.Series(
        ["Y" if p.anxiety else None for p in people], dtype=STRING
    )
    return responses


def compute(people: Sequence[Person]) -> MetricSet:
    responses = responses_for(people)
    return symptoms.compute(responses, compute_features(responses, SPEC), SPEC)


def distribution(metrics: MetricSet, metric_id: str) -> Distribution:
    metric = metrics[metric_id]
    assert isinstance(metric, Distribution)
    return metric


def proportion(metrics: MetricSet, metric_id: str) -> Proportion:
    metric = metrics[metric_id]
    assert isinstance(metric, Proportion)
    return metric


# Ten respondents, by hand. PHQ-9 sums 0 4 5 9 10 14 15 19 20 and one missing; GAD-7
# sums 0 4 9 10 5 14 15 16 and a missing one (row 8) and 3 (row 9).
PEOPLE = [
    Person(phq9=0, item9=0, gad7=0, impairment=0),
    Person(phq9=4, item9=0, gad7=4, impairment=1),
    Person(phq9=5, item9=1, gad7=9, impairment=2, depression=True),
    Person(phq9=9, item9=1, gad7=10, impairment=3, anxiety=True),
    Person(phq9=10, item9=2, gad7=5, impairment=2, depression=True, anxiety=True),
    Person(phq9=14, item9=2, gad7=14, impairment=1, depression=True),
    Person(phq9=15, item9=3, gad7=15, impairment=0),
    Person(phq9=19, item9=3, gad7=16, impairment=2),
    Person(phq9=20, item9=3, gad7=None, impairment=None, depression=True, anxiety=True),
    Person(phq9=None, item9=0, gad7=3, impairment=3, depression=True, anxiety=True),
]


# --- hand-made cases ---------------------------------------------------------------


def test_phq9_severity_counts_the_bands_in_order() -> None:
    metric = distribution(compute(PEOPLE), PHQ9_SEVERITY_ID)
    assert metric.categories == PHQ9_SEVERITY_CATEGORIES
    assert metric.counts == (2, 2, 2, 2, 1)
    # Row 9 has an empty item, so the score cannot be computed (D12).
    assert (metric.n, metric.n_missing) == (9, 1)


def test_gad7_severity_counts_the_bands_in_order() -> None:
    metric = distribution(compute(PEOPLE), GAD7_SEVERITY_ID)
    assert metric.categories == GAD7_SEVERITY_CATEGORIES
    assert metric.counts == (3, 2, 2, 2)
    assert (metric.n, metric.n_missing) == (9, 1)


def test_cutoffs_use_respondents_with_a_score() -> None:
    metrics = compute(PEOPLE)
    assert proportion(metrics, PHQ9_CUTOFF_ID) == Proportion(5, 9, 1)
    assert proportion(metrics, GAD7_CUTOFF_ID) == Proportion(4, 9, 1)


def test_severity_among_depression_diagnosis() -> None:
    metric = distribution(compute(PEOPLE), PHQ9_SEVERITY_DEPRESSION_ID)
    # Rows 2, 4, 5, 8 and 9 ticked the option; row 9 has no PHQ-9 score.
    assert metric.categories == PHQ9_SEVERITY_CATEGORIES
    assert metric.counts == (0, 1, 2, 0, 1)
    assert (metric.n, metric.n_missing) == (4, 1)


def test_severity_among_anxiety_diagnosis() -> None:
    metric = distribution(compute(PEOPLE), GAD7_SEVERITY_ANXIETY_ID)
    # Rows 3, 4, 8 and 9 ticked the option; row 8 has no GAD-7 score.
    assert metric.categories == GAD7_SEVERITY_CATEGORIES
    assert metric.counts == (1, 1, 1, 0)
    assert (metric.n, metric.n_missing) == (3, 1)


def test_combined_leaves_out_an_undeterminable_respondent() -> None:
    metric = proportion(compute(PEOPLE), COMBINED_ID)
    # Rows 3-8 are burdened; row 8 by PHQ-9 alone (GAD-7 missing). Row 9 has no
    # PHQ-9 score and GAD-7 below 10: undeterminable, left out.
    assert metric == Proportion(6, 9, 1)


def test_item9_and_impairment_distributions_and_cut() -> None:
    metrics = compute(PEOPLE)
    item9 = distribution(metrics, ITEM9_DISTRIBUTION_ID)
    assert item9.categories == ("0", "1", "2", "3")
    # Row 9 answered item 9 although its PHQ-9 score is missing.
    assert item9.counts == (3, 2, 2, 3)
    assert (item9.n, item9.n_missing) == (10, 0)
    assert proportion(metrics, ITEM9_ELEVATED_ID) == Proportion(5, 10, 0)
    impairment = distribution(metrics, IMPAIRMENT_DISTRIBUTION_ID)
    assert impairment.categories == ("0", "1", "2", "3")
    assert impairment.counts == (2, 2, 3, 2)
    assert (impairment.n, impairment.n_missing) == (9, 1)
    assert proportion(metrics, IMPAIRMENT_ELEVATED_ID) == Proportion(5, 9, 1)


def test_empty_item9_is_missing() -> None:
    responses = responses_for(PEOPLE[:3])
    features = compute_features(responses, SPEC)
    features.loc[1, "phq9_item9"] = pd.NA
    metrics = symptoms.compute(responses, features, SPEC)
    assert distribution(metrics, ITEM9_DISTRIBUTION_ID).counts == (1, 1, 0, 0)
    assert distribution(metrics, ITEM9_DISTRIBUTION_ID).n_missing == 1
    assert proportion(metrics, ITEM9_ELEVATED_ID) == Proportion(0, 2, 1)


def test_only_the_option_defines_the_subgroup() -> None:
    """DIAGQ0 is not consulted (kept from the previous report)."""
    responses = responses_for(PEOPLE[:3])
    no = next(c for c in SPEC.question("DIAGQ0").codes if c != SPEC.yes_code("DIAGQ0"))
    responses["DIAGQ0"] = pd.Series([None, no, no], dtype=STRING)
    metrics = symptoms.compute(responses, compute_features(responses, SPEC), SPEC)
    assert distribution(metrics, PHQ9_SEVERITY_DEPRESSION_ID).n == 1


def test_nobody_has_a_score() -> None:
    people = [Person(phq9=None, item9=0, gad7=None, impairment=None)] * 3
    metrics = compute(people)
    assert distribution(metrics, PHQ9_SEVERITY_ID) == Distribution(
        PHQ9_SEVERITY_CATEGORIES, (0,) * 5, 3
    )
    assert proportion(metrics, PHQ9_CUTOFF_ID) == Proportion(0, 0, 3)
    assert proportion(metrics, COMBINED_ID) == Proportion(0, 0, 3)
    assert distribution(metrics, IMPAIRMENT_DISTRIBUTION_ID).n_missing == 3
    assert proportion(metrics, IMPAIRMENT_ELEVATED_ID) == Proportion(0, 0, 3)


def test_no_respondents() -> None:
    metrics = compute([])
    assert distribution(metrics, GAD7_SEVERITY_ID).n == 0
    assert proportion(metrics, COMBINED_ID) == Proportion(0, 0, 0)


def test_small_groups_are_not_suppressed() -> None:
    metrics = compute([Person(phq9=12, item9=2, gad7=3, impairment=3, depression=True)])
    assert proportion(metrics, PHQ9_CUTOFF_ID) == Proportion(1, 1, 0)
    assert distribution(metrics, PHQ9_SEVERITY_DEPRESSION_ID).counts == (0, 0, 1, 0, 0)


def test_answer_categories_come_from_the_spec() -> None:
    raw = yaml.safe_load(
        (
            Path(__file__).parents[2]
            / "src/spot_report/questionnaire/specs/2026.1.yaml"
        ).read_text(encoding="utf-8")
    )
    raw["numeric"]["SIPHQ"]["max"] = 4
    other = spec_from_mapping(raw)
    responses = responses_for(PEOPLE[:2])
    metrics = symptoms.compute(responses, compute_features(responses, other), other)
    assert distribution(metrics, IMPAIRMENT_DISTRIBUTION_ID).categories == (
        "0",
        "1",
        "2",
        "3",
        "4",
    )


# --- registry wiring -----------------------------------------------------------------


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute(PEOPLE)
    assert {d.id for d in symptoms.definitions(SPEC)} == set(metrics)
    default_registry(SPEC).check(metrics)
    assert all(d.domain == "symptoms" for d in symptoms.definitions(SPEC))
    assert all(d.since == SPEC.version for d in symptoms.definitions(SPEC))


def test_definition_items_are_spec_columns() -> None:
    for definition in symptoms.definitions(SPEC):
        assert definition.items
        for item in definition.items:
            SPEC.question(item)


def test_expected_ids() -> None:
    assert {(d.id, d.kind) for d in symptoms.definitions(SPEC)} == {
        ("symptoms.phq9.severity", "distribution"),
        ("symptoms.phq9.severity.depression_diagnosis", "distribution"),
        ("symptoms.phq9.cutoff10", "proportion"),
        ("symptoms.gad7.severity", "distribution"),
        ("symptoms.gad7.severity.anxiety_diagnosis", "distribution"),
        ("symptoms.gad7.cutoff10", "proportion"),
        ("symptoms.combined.burdened", "proportion"),
        ("symptoms.phq9_item9.distribution", "distribution"),
        ("symptoms.phq9_item9.cutoff2", "proportion"),
        ("symptoms.impairment.distribution", "distribution"),
        ("symptoms.impairment.cutoff2", "proportion"),
    }


def test_item9_definition_depends_on_the_ninth_phq9_item() -> None:
    by_id = {d.id: d for d in symptoms.definitions(SPEC)}
    assert by_id[ITEM9_DISTRIBUTION_ID].items == (PHQ9_ITEMS[8],)


# --- legacy parity ------------------------------------------------------------------

#: Legacy band codes that differ from the feature categories.
LEGACY_BAND = {"mod_severe": "moderately_severe"}


def _read(dataset: str) -> pd.DataFrame:
    return read_responses(FIXTURE_DIR / f"{dataset}.xlsx", "xlsx", SPEC)


@pytest.mark.parametrize("dataset", expected_datasets())
def test_legacy_parity(dataset: str) -> None:
    responses = _read(dataset)
    metrics = compute_metrics(responses, compute_features(responses, SPEC), SPEC)
    expected = load_expected(dataset)
    checked: set[str] = set()

    def check(key: str, new: float | None) -> None:
        assert_parity(dataset, key, new)
        checked.add(key)

    def check_cut(prefix: str, metric: Proportion) -> None:
        check(f"{prefix}.n", metric.k)
        check(f"{prefix}.pct", metric.share)

    def check_distribution(
        prefix: str, metric: Distribution, names: dict[str, str] | None = None
    ) -> None:
        assert metric.shares is not None
        for category, count, share in zip(
            metric.categories, metric.counts, metric.shares, strict=True
        ):
            name = (names or {}).get(category, category)
            check(f"{prefix}.count.{name}", count)
            check(f"{prefix}.pct.{name}", share)

    for scale, subgroup_id, severity_id, cut_id in (
        ("phq9", PHQ9_SEVERITY_DEPRESSION_ID, PHQ9_SEVERITY_ID, PHQ9_CUTOFF_ID),
        ("gad7", GAD7_SEVERITY_ANXIETY_ID, GAD7_SEVERITY_ID, GAD7_CUTOFF_ID),
    ):
        legacy = {new: old for old, new in LEGACY_BAND.items()}
        severity = distribution(metrics, severity_id)
        check_cut(f"symptoms.{scale}.top", proportion(metrics, cut_id))
        check_distribution(f"symptoms.{scale}.sev", severity, legacy)
        subgroup = distribution(metrics, subgroup_id)
        for category, count in zip(subgroup.categories, subgroup.counts, strict=True):
            name = legacy.get(category, category)
            check(f"symptoms.{scale}.sev.diagcount.{name}", count)

    check_cut("symptoms.combined.top", proportion(metrics, COMBINED_ID))

    for name, distribution_id, elevated_id, letter in (
        ("suicidal", ITEM9_DISTRIBUTION_ID, ITEM9_ELEVATED_ID, "S"),
        ("impairment", IMPAIRMENT_DISTRIBUTION_ID, IMPAIRMENT_ELEVATED_ID, "I"),
    ):
        check_cut(f"symptoms.{name}.top", proportion(metrics, elevated_id))
        check_distribution(
            f"symptoms.{name}.dist",
            distribution(metrics, distribution_id),
            {str(v): f"{letter}{v}" for v in range(4)},
        )

    assert checked == set(expected.under("symptoms"))
