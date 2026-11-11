"""Association metrics (R18): hand-made cases, wiring and legacy parity."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spot_report.features import SYMPTOM_CATEGORIES, compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    Distribution,
    MetricSet,
    association,
    compute_metrics,
    default_registry,
)
from spot_report.metrics.association import (
    CATEGORY_ID,
    STATUS_CATEGORIES,
    category_id,
    level_id,
)
from spot_report.questionnaire import load_spec, spec_from_mapping
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
STRING = pd.StringDtype(na_value=pd.NA)
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
PHQ9_ITEMS = SPEC.scale("PHQ9").columns
GAD7_ITEMS = SPEC.scale("GAD7").columns
LEVELS = SPEC.question("DQSTUFE").codes
TREATMENT_OPTIONS = [q.code for q in SPEC.multi_select_options("DIAGQ3")]
NONE_OPTION = next(q.code for q in SPEC.multi_select_options("DIAGQ3") if q.none_option)
TREATMENT = next(
    q.code for q in SPEC.multi_select_options("DIAGQ3") if not q.none_option
)
OTHER_TREATMENT = SPEC.other_text("DIAGQ3")
assert OTHER_TREATMENT is not None
YES = SPEC.yes_code("DIAGQ0")
NO = next(c for c in SPEC.question("DIAGQ0").codes if c != YES)


@dataclass(frozen=True)
class Person:
    """One respondent; a score of ``None`` means one empty item of that scale."""

    phq9: int | None
    gad7: int | None
    diagnosis: str | None  # the DIAGQ0 code, or None for an empty answer
    treated: bool = False
    level: str | None = None
    #: A ticked "none" treatment option does not make a treatment.
    no_treatment_ticked: bool = False
    #: A filled "other" treatment text is a treatment (ADR 0004).
    other_treatment: bool = False


def spread(total: int, count: int) -> list[int | None]:
    """Item values 0-3 with the given sum, filled from the first item."""
    items: list[int | None] = []
    for _ in range(count):
        items.append(min(3, total))
        total -= items[-1] or 0
    assert total == 0
    return items


def _items(score: int | None, count: int) -> list[int | None]:
    return [None, *spread(0, count - 1)] if score is None else spread(score, count)


def responses_for(people: Sequence[Person]) -> pd.DataFrame:
    """Complete responses (first rows of a fixture) with the used columns replaced."""
    base = read_responses(FIXTURE_DIR / "synthetic_300.xlsx", "xlsx", SPEC)
    responses = base.head(len(people)).reset_index(drop=True)
    for items, getter in ((PHQ9_ITEMS, "phq9"), (GAD7_ITEMS, "gad7")):
        rows = [_items(getattr(p, getter), len(items)) for p in people]
        for position, code in enumerate(items):
            responses[code] = pd.Series(
                [row[position] for row in rows], dtype=pd.Int64Dtype()
            )
    responses["DIAGQ0"] = pd.Series([p.diagnosis for p in people], dtype=STRING)
    responses["DQSTUFE"] = pd.Series([p.level for p in people], dtype=STRING)
    for code in TREATMENT_OPTIONS:
        responses[code] = pd.Series(
            [
                "Y"
                if (code == TREATMENT and p.treated)
                or (code == NONE_OPTION and p.no_treatment_ticked)
                else None
                for p in people
            ],
            dtype=STRING,
        )
    responses[OTHER_TREATMENT.code] = pd.Series(
        ["x" if p.other_treatment else None for p in people], dtype=STRING
    )
    return responses


def compute(people: Sequence[Person]) -> MetricSet:
    responses = responses_for(people)
    return association.compute(responses, compute_features(responses, SPEC), SPEC)


def distribution(metrics: MetricSet, metric_id: str) -> Distribution:
    metric = metrics[metric_id]
    assert isinstance(metric, Distribution)
    return metric


G1, G2, G3, G4 = LEVELS

# Fourteen respondents, by hand. Category and status in the comment.
PEOPLE = [
    # severe: PHQ-9 or GAD-7 at or above 10
    Person(12, 2, YES, treated=True, level=G1),  # severe, diagnosed_treated
    Person(2, 10, YES, level=G1),  # severe, diagnosed_untreated
    Person(None, 15, YES, treated=True, level=G2),  # severe (PHQ-9 missing), treated
    Person(20, 20, NO, level=None),  # severe, not_diagnosed, no level
    Person(10, 0, NO, level=G4),  # severe at the cut-off, not_diagnosed
    # medium: both present, none at 10, one at 5-9
    Person(7, 1, NO, level=G1),  # medium, not_diagnosed
    Person(4, 5, YES, level=G3, no_treatment_ticked=True),  # medium, untreated
    Person(9, 9, YES, treated=True, level=G4),  # medium, diagnosed_treated
    Person(5, 0, NO, level=G1),  # medium at the lower bound, not_diagnosed
    # mildnone: both present and below 5
    Person(0, 4, NO, treated=True, level=G2),  # mildnone, not_diagnosed (treatment
    # does not matter without a diagnosis)
    Person(4, 4, None, level=G2),  # mildnone, DIAGQ0 empty
    # undetermined: a present score below 10 and a missing one, or both missing
    Person(3, None, NO, level=G2),
    Person(7, None, YES, treated=True, level=G3),
    Person(None, None, NO, level=G1),
]


def counts(metrics: MetricSet, metric_id: str) -> tuple[int, ...]:
    return distribution(metrics, metric_id).counts


# --- hand-made cases ---------------------------------------------------------------


def test_symptom_category_distribution_and_undetermined_respondents() -> None:
    metric = distribution(compute(PEOPLE), CATEGORY_ID)
    assert metric.categories == ("mildnone", "medium", "severe")
    assert metric.categories == SYMPTOM_CATEGORIES
    assert metric.counts == (2, 4, 5)
    # Three respondents cannot be assigned: a score below 10 and a missing score.
    assert (metric.n, metric.n_missing) == (11, 3)


def test_status_distributions_of_all_respondents() -> None:
    metrics = compute(PEOPLE)
    assert distribution(metrics, category_id("severe")).categories == STATUS_CATEGORIES
    assert counts(metrics, category_id("severe")) == (2, 1, 2)
    assert counts(metrics, category_id("medium")) == (1, 1, 2)
    # Mildnone: one not diagnosed; the respondent with an empty DIAGQ0 is n_missing.
    mildnone = distribution(metrics, category_id("mildnone"))
    assert (mildnone.counts, mildnone.n_missing) == ((0, 0, 1), 1)
    assert (mildnone.n, mildnone.n_missing) == (1, 1)


def test_status_distributions_by_level() -> None:
    metrics = compute(PEOPLE)
    by_level = {
        "severe": {G1: (1, 1, 0), G2: (1, 0, 0), G3: (0, 0, 0), G4: (0, 0, 1)},
        "medium": {G1: (0, 0, 2), G2: (0, 0, 0), G3: (0, 1, 0), G4: (1, 0, 0)},
        "mildnone": {G1: (0, 0, 0), G2: (0, 0, 1), G3: (0, 0, 0), G4: (0, 0, 0)},
    }
    for category, expected in by_level.items():
        for level, level_counts in expected.items():
            assert counts(metrics, level_id(category, level)) == level_counts
    # The respondent without a level is in the overall metric only.
    assert sum(counts(metrics, category_id("severe"))) == 5
    assert sum(sum(counts(metrics, level_id("severe", level))) for level in LEVELS) == 4


def test_respondent_with_empty_diagnosis_is_missing_in_the_level_metric() -> None:
    metric = distribution(compute(PEOPLE), level_id("mildnone", G2))
    assert (metric.counts, metric.n_missing) == ((0, 0, 1), 1)


def test_levels_add_up_to_the_overall_metric_when_every_level_is_known() -> None:
    people = [p for p in PEOPLE if p.level is not None]
    metrics = compute(people)
    for category in SYMPTOM_CATEGORIES:
        total = tuple(
            sum(column)
            for column in zip(
                *(counts(metrics, level_id(category, level)) for level in LEVELS),
                strict=True,
            )
        )
        assert total == counts(metrics, category_id(category))


@pytest.mark.parametrize(
    ("phq9", "gad7", "expected"),
    [
        (10, 0, "severe"),
        (9, 9, "medium"),
        (4, 4, "mildnone"),
        (5, 4, "medium"),
        (4, 5, "medium"),
        (12, None, "severe"),  # the present score decides
        (None, 10, "severe"),
        (9, None, None),  # the missing score could be 10 or more
        (None, 3, None),
        (None, None, None),
    ],
)
def test_category_rule_for_every_missing_value_case(
    phq9: int | None, gad7: int | None, expected: str | None
) -> None:
    metrics = compute([Person(phq9, gad7, NO)])
    overall = distribution(metrics, CATEGORY_ID)
    if expected is None:
        assert (overall.n, overall.n_missing) == (0, 1)
        assert all(
            sum(counts(metrics, category_id(c))) == 0 for c in overall.categories
        )
    else:
        assert (overall.n, overall.n_missing) == (1, 0)
        assert overall.counts[overall.categories.index(expected)] == 1
        assert counts(metrics, category_id(expected)) == (0, 0, 1)


def test_severe_is_the_burdened_feature() -> None:
    features = compute_features(responses_for(PEOPLE), SPEC)
    category, burdened = features["symptom_category"], features["burdened"]
    known = burdened.notna()
    assert (category[known].eq("severe") == burdened[known].astype(bool)).all()
    assert category[~known].isna().all()


def test_none_treatment_option_is_not_a_treatment() -> None:
    metrics = compute([Person(6, 0, YES, no_treatment_ticked=True)])
    assert counts(metrics, category_id("medium")) == (0, 1, 0)


def test_filled_other_treatment_is_a_treatment() -> None:
    metrics = compute([Person(6, 0, YES, other_treatment=True)])
    assert counts(metrics, category_id("medium")) == (1, 0, 0)


def test_treatment_without_diagnosis_does_not_count() -> None:
    metrics = compute([Person(6, 0, NO, treated=True)])
    assert counts(metrics, category_id("medium")) == (0, 0, 1)


def test_empty_diagnosis_is_left_out_of_the_status_partition() -> None:
    people = [Person(14, 0, None, treated=True), Person(14, 0, YES)]
    metric = distribution(compute(people), category_id("severe"))
    assert metric.counts == (0, 1, 0)
    assert (metric.n, metric.n_missing) == (1, 1)


def test_empty_level_is_in_no_level_subgroup() -> None:
    metrics = compute([Person(14, 0, YES, level=None)])
    assert counts(metrics, category_id("severe")) == (0, 1, 0)
    for level in LEVELS:
        metric = distribution(metrics, level_id("severe", level))
        assert (metric.n, metric.n_missing) == (0, 0)


def test_small_groups_are_not_suppressed() -> None:
    metrics = compute([Person(14, 0, YES, treated=True, level=G3)])
    assert counts(metrics, level_id("severe", G3)) == (1, 0, 0)


def test_no_respondents() -> None:
    metrics = compute([])
    assert distribution(metrics, CATEGORY_ID) == Distribution(
        SYMPTOM_CATEGORIES, (0, 0, 0), 0
    )
    assert distribution(metrics, level_id("severe", G1)).n == 0


def test_level_ids_come_from_the_spec() -> None:
    raw = yaml.safe_load(
        (
            Path(__file__).parents[2]
            / "src/spot_report/questionnaire/specs/2026.1.yaml"
        ).read_text(encoding="utf-8")
    )
    raw["single_choice"]["DQSTUFE"]["codes"] = ["Gym1", "Gym2", "Gym3", "Gym4", "Gym5"]
    other = spec_from_mapping(raw)
    ids = {d.id for d in association.definitions(other)}
    assert level_id("mildnone", "Gym5") in ids
    assert "association.mildnone.diagnosis_status.gym5" in ids
    assert len(ids) == len(association.definitions(SPEC)) + 3


# --- registry wiring -----------------------------------------------------------------


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute(PEOPLE)
    assert {d.id for d in association.definitions(SPEC)} == set(metrics)
    default_registry(SPEC).check(metrics)
    assert all(d.domain == "association" for d in association.definitions(SPEC))
    assert all(d.kind == "distribution" for d in association.definitions(SPEC))
    assert all(d.since == SPEC.version for d in association.definitions(SPEC))


def test_definition_items_are_spec_columns() -> None:
    for definition in association.definitions(SPEC):
        assert definition.items
        for item in definition.items:
            SPEC.question(item)


def test_expected_ids() -> None:
    expected = {"association.symptoms.category"}
    for category in ("mildnone", "medium", "severe"):
        expected.add(f"association.{category}.diagnosis_status")
        expected |= {
            f"association.{category}.diagnosis_status.gym{n}" for n in range(1, 5)
        }
    assert {d.id for d in association.definitions(SPEC)} == expected


def test_domain_is_part_of_compute_metrics() -> None:
    responses = responses_for(PEOPLE)
    metrics = compute_metrics(responses, compute_features(responses, SPEC), SPEC)
    assert CATEGORY_ID in metrics


# --- legacy parity ------------------------------------------------------------------

#: Legacy names of the symptom categories (ADR 0004 renamed ``moderate``).
LEGACY_CATEGORY = {"mildnone": "mildnone", "medium": "moderate", "severe": "severe"}

#: Legacy status columns as sums of the new status categories.
LEGACY_STATUS = {
    "known_diag": ("diagnosed_treated", "diagnosed_untreated"),
    "treated": ("diagnosed_treated",),
    "unknown_diag": ("not_diagnosed",),
}


def _legacy_count(metric: Distribution, status: str) -> int:
    return sum(
        count
        for name, count in zip(metric.categories, metric.counts, strict=True)
        if name in LEGACY_STATUS[status]
    )


@pytest.mark.parametrize("dataset", expected_datasets())
def test_legacy_parity(dataset: str) -> None:
    responses = read_responses(FIXTURE_DIR / f"{dataset}.xlsx", "xlsx", SPEC)
    metrics = compute_metrics(responses, compute_features(responses, SPEC), SPEC)
    expected = load_expected(dataset)
    checked: set[str] = set()

    def check(key: str, new: int) -> None:
        assert_parity(dataset, key, new)
        checked.add(key)

    def check_table(prefix: str, category: str, metric: Distribution) -> None:
        for status in LEGACY_STATUS:
            check(
                f"{prefix}.{LEGACY_CATEGORY[category]}.{status}",
                _legacy_count(metric, status),
            )

    for category in SYMPTOM_CATEGORIES:
        overall = distribution(metrics, category_id(category))
        check_table("assoc.table_all", category, overall)
        for level in LEVELS:
            check_table(
                f"assoc.by_level.{level}",
                category,
                distribution(metrics, level_id(category, level)),
            )

    severe = distribution(metrics, category_id("severe"))
    medium = distribution(metrics, category_id("medium"))
    check("assoc.overlap.symp_and_diag_n", _legacy_count(severe, "known_diag"))
    check("assoc.overlap.symp_diag_treated_n", _legacy_count(severe, "treated"))
    check("assoc.overlap.symp_no_diag_n", _legacy_count(severe, "unknown_diag"))
    check("assoc.overlap.moderate_no_diag_n", _legacy_count(medium, "unknown_diag"))

    assert checked == set(expected.under("assoc"))
