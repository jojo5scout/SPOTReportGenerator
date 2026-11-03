"""Diagnosis, help-source and treatment metrics (R15): cases, wiring, parity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd
import pytest
import yaml

from spot_report.features import compute_features, yes_no
from spot_report.ingest import read_responses
from spot_report.metrics import (
    Distribution,
    MetricSet,
    PatternCounts,
    Proportion,
    compute_metrics,
    default_registry,
    diagnoses,
    top_patterns,
)
from spot_report.metrics.diagnoses import (
    PATTERNS_ID,
    REPORTED_ID,
    USAGE_CATEGORIES,
    USAGE_ID,
    help_id,
    treatment_id,
    type_id,
)
from spot_report.questionnaire import load_spec, spec_from_mapping
from tests.parity import assert_parity, expected_datasets, load_expected

SPEC = load_spec("2026.1")
STRING = pd.StringDtype(na_value=pd.NA)
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures"
GROUPS = ("DIAGQ1", "DIAGQ2", "DIAGQ3")

Ticks = Mapping[str, Sequence[str]]


def frame(rows: Sequence[tuple[str | None, Ticks]]) -> pd.DataFrame:
    """Responses with the columns of DIAGQ0 to DIAGQ3 and the reader's dtypes.

    Every row is the answer to DIAGQ0 and the ticked options per group; an option
    that is not ticked is an empty cell. Optional option columns are present only if
    some row ticks them.
    """
    columns: dict[str, list[str | None]] = {
        "DIAGQ0": [answer for answer, _ in rows],
    }
    for group in GROUPS:
        ticked = {option for _, ticks in rows for option in ticks.get(group, ())}
        for option in SPEC.multi_select_options(group):
            name = option.code.removeprefix(f"{group}[").removesuffix("]")
            if option.required or name in ticked:
                columns[option.code] = [
                    option.selected if name in ticks.get(group, ()) else None
                    for _, ticks in rows
                ]
    return pd.DataFrame(
        {code: pd.Series(v, dtype=STRING) for code, v in columns.items()}
    )


def compute(responses: pd.DataFrame) -> MetricSet:
    features = pd.DataFrame({"diagnosis": yes_no(responses, SPEC, "DIAGQ0")})
    return diagnoses.compute(responses, features, SPEC)


def proportion(metrics: MetricSet, metric_id: str) -> Proportion:
    metric = metrics[metric_id]
    assert isinstance(metric, Proportion)
    return metric


# Ten respondents, by hand (rows 0-9). Diagnosed: 0, 1, 2, 3, 7, 8, 9 (7 people);
# not diagnosed: 4, 5; DIAGQ0 empty: 6. Rows 4 and 6 tick options although they are not
# part of the diagnosed group.
ROWS: list[tuple[str | None, Ticks]] = [
    (
        "Ja",
        {
            "DIAGQ1": ["DEPR", "ANGS"],
            "DIAGQ2": ["SCHU", "PSYO"],
            "DIAGQ3": ["MEDI", "THER"],
        },
    ),
    (
        "Ja",
        {"DIAGQ1": ["DEPR"], "DIAGQ2": ["PSYO", "PSYA", "SELB"], "DIAGQ3": ["THER"]},
    ),
    ("Ja", {"DIAGQ1": ["ESST"], "DIAGQ2": ["NIEM", "PSYA"], "DIAGQ3": ["NOT"]}),
    ("Ja", {}),
    ("Nein", {"DIAGQ1": ["DEPR"], "DIAGQ2": ["PSYO"], "DIAGQ3": ["MEDI"]}),
    ("Nein", {}),
    (None, {"DIAGQ1": ["DEPR"], "DIAGQ2": ["SCHU"], "DIAGQ3": ["THER"]}),
    (
        "Ja",
        {
            "DIAGQ1": ["PTBS"],
            "DIAGQ2": ["SCHU", "PSYO", "PSYA", "SELB", "BERA"],
            "DIAGQ3": [],
        },
    ),
    ("Ja", {"DIAGQ1": ["BIPO"], "DIAGQ2": ["KLIN", "NIEM"], "DIAGQ3": []}),
    (
        "Ja",
        {"DIAGQ1": ["PSYC"], "DIAGQ2": ["HAUS", "KIND", "SCHU"], "DIAGQ3": ["MEDI"]},
    ),
]


# --- hand-made cases ---------------------------------------------------------------


def test_diagnosis_share_leaves_out_empty_answers() -> None:
    reported = proportion(compute(frame(ROWS)), REPORTED_ID)
    # 9 of 10 answered DIAGQ0 (D12: the empty one is left out), 7 of them said yes.
    assert (reported.k, reported.n, reported.n_missing) == (7, 9, 1)


def test_types_are_counted_for_diagnosed_respondents_of_all_respondents() -> None:
    metrics = compute(frame(ROWS))
    expected = {
        "DEPR": 2,  # rows 0 and 1; rows 4 (not diagnosed) and 6 (empty) do not count
        "ANGS": 1,
        "ESST": 1,
        "ADHS": 0,
        "PTBS": 1,
        "BIPO": 1,
        "PSYC": 1,
        "BORD": 0,  # optional column absent: nobody selected it
        "OTHER": 0,
    }
    for option, count in expected.items():
        metric = proportion(metrics, type_id(option))
        assert (metric.k, metric.n, metric.n_missing) == (count, 10, 0), option


def test_help_sources_among_the_diagnosed() -> None:
    metrics = compute(frame(ROWS))
    expected = {
        "NIEM": 2,  # raw ticks, also where "nobody" overrides the others
        "HAUS": 1,
        "KIND": 1,
        "SCHU": 3,
        "PSYO": 3,  # rows 0, 1, 7; row 4 is not diagnosed
        "PSYA": 3,
        "SELB": 2,
        "BERA": 1,
        "KLIN": 1,
    }
    for option, count in expected.items():
        metric = proportion(metrics, help_id(option))
        # n is the 7 diagnosed; the respondent with an empty DIAGQ0 is n_missing.
        assert (metric.k, metric.n, metric.n_missing) == (count, 7, 1), option


def test_help_usage_counts_sources_and_nobody_overrides() -> None:
    usage = metrics_usage(compute(frame(ROWS)))
    assert usage.categories == USAGE_CATEGORIES == ("0", "1", "2", "3", "4plus")
    # Sources per diagnosed respondent: 2, 3, 0 (nobody overrides PSYA), 0 (nothing
    # ticked), 5 (4plus), 0 (nobody overrides the clinic), 3.
    assert usage.counts == (3, 0, 1, 2, 1)
    assert (usage.n, usage.n_missing) == (7, 1)


def metrics_usage(metrics: MetricSet) -> Distribution:
    metric = metrics[USAGE_ID]
    assert isinstance(metric, Distribution)
    return metric


def test_help_combinations_by_hand() -> None:
    metric = compute(frame(ROWS))[PATTERNS_ID]
    assert isinstance(metric, PatternCounts)
    assert metric.options == (
        "HAUS",
        "KIND",
        "SCHU",
        "PSYO",
        "PSYA",
        "SELB",
        "BERA",
        "KLIN",
    )
    assert metric.patterns == (
        (),
        ("SCHU", "PSYO"),
        ("HAUS", "KIND", "SCHU"),
        ("PSYO", "PSYA", "SELB"),
        ("SCHU", "PSYO", "PSYA", "SELB", "BERA"),
    )
    assert metric.counts == (3, 1, 1, 1, 1)
    assert (metric.n, metric.n_missing) == (7, 1)
    # The distribution and the combinations agree on the number of sources.
    assert metric.count_of(()) == metrics_usage(compute(frame(ROWS))).counts[0]


def test_chart_selection_from_the_combinations() -> None:
    metric = compute(frame(ROWS))[PATTERNS_ID]
    assert isinstance(metric, PatternCounts)
    assert top_patterns(metric, 1, 2) == ()
    assert top_patterns(metric, 2, 2) == ((("SCHU", "PSYO"), 1),)
    # Equal counts: ties are broken by the option codes as text.
    assert top_patterns(metric, 3, 2) == (
        (("HAUS", "KIND", "SCHU"), 1),
        (("PSYO", "PSYA", "SELB"), 1),
    )


def test_treatment_among_the_diagnosed() -> None:
    metrics = compute(frame(ROWS))
    expected = {"NOT": 1, "MEDI": 2, "THER": 2, "STAT": 0, "OTHER": 0}
    for option, count in expected.items():
        metric = proportion(metrics, treatment_id(option))
        assert (metric.k, metric.n, metric.n_missing) == (count, 7, 1), option


def test_nobody_option_comes_from_the_spec() -> None:
    """Without the spec's `none_option` mark NIEM is an ordinary help source."""
    raw = yaml.safe_load(
        (
            Path(__file__).parents[2]
            / "src/spot_report/questionnaire/specs/2026.1.yaml"
        ).read_text(encoding="utf-8")
    )
    del raw["multi_select"]["DIAGQ2"]["none_option"]
    plain = spec_from_mapping(raw)
    responses = frame([("Ja", {"DIAGQ2": ["NIEM", "PSYO"]})])
    features = pd.DataFrame({"diagnosis": yes_no(responses, plain, "DIAGQ0")})

    ordinary = diagnoses.compute(responses, features, plain)
    assert metrics_usage(ordinary).counts == (0, 0, 1, 0, 0)  # two sources
    assert compute(responses)[USAGE_ID] == Distribution(
        USAGE_CATEGORIES, (1, 0, 0, 0, 0), 0
    )  # with the mark: PSYO is cleared, so no source


def test_nobody_cleared_from_every_other_option() -> None:
    responses = frame(
        [
            ("Ja", {"DIAGQ2": ["NIEM", "PSYO", "KLIN"]}),
            ("Ja", {"DIAGQ2": ["PSYO"]}),
        ]
    )
    metric = compute(responses)[PATTERNS_ID]
    assert isinstance(metric, PatternCounts)
    assert metric.patterns == ((), ("PSYO",))
    assert metric.counts == (1, 1)


def test_nobody_diagnosed_and_nobody_answered() -> None:
    for rows, (k, n, missing) in (
        ([("Nein", {"DIAGQ2": ["PSYO"]})] * 2, (0, 2, 0)),
        ([(None, {"DIAGQ2": ["PSYO"]})] * 2, (0, 0, 2)),
    ):
        metrics = compute(frame(rows))
        reported = proportion(metrics, REPORTED_ID)
        assert (reported.k, reported.n, reported.n_missing) == (k, n, missing)
        help_source = proportion(metrics, help_id("PSYO"))
        assert (help_source.k, help_source.n, help_source.n_missing) == (0, 0, missing)
        assert metrics_usage(metrics).counts == (0, 0, 0, 0, 0)
        patterns = metrics[PATTERNS_ID]
        assert isinstance(patterns, PatternCounts)
        assert (patterns.patterns, patterns.n, patterns.n_missing) == ((), 0, missing)
        # The type share still divides by everybody (kept legacy behaviour).
        assert proportion(metrics, type_id("DEPR")) == Proportion(0, 2, 0)


def test_no_respondents() -> None:
    metrics = compute(frame([]))
    assert proportion(metrics, REPORTED_ID) == Proportion(0, 0, 0)
    assert metrics_usage(metrics).n == 0


def test_small_groups_are_not_suppressed() -> None:
    metrics = compute(frame([("Ja", {"DIAGQ1": ["DEPR"], "DIAGQ3": ["THER"]})]))
    assert proportion(metrics, type_id("DEPR")) == Proportion(1, 1, 0)
    assert proportion(metrics, treatment_id("THER")) == Proportion(1, 1, 0)


# --- registry wiring -----------------------------------------------------------------


def test_definitions_match_computed_ids_and_kinds() -> None:
    metrics = compute(frame(ROWS))
    assert {d.id for d in diagnoses.DEFINITIONS} == set(metrics)
    default_registry().check(metrics)
    assert all(d.domain == "diagnoses" for d in diagnoses.DEFINITIONS)
    assert all(d.since == SPEC.version for d in diagnoses.DEFINITIONS)


def test_ids_are_the_same_whether_optional_columns_are_present() -> None:
    assert set(compute(frame([("Ja", {})]))) == set(compute(frame(ROWS)))


def test_definition_items_are_spec_columns() -> None:
    for definition in diagnoses.DEFINITIONS:
        assert definition.items[0] == "DIAGQ0"
        for item in definition.items:
            SPEC.question(item)


def test_no_free_text_column_is_used() -> None:
    free_text = set(SPEC.free_text_columns)
    for definition in diagnoses.DEFINITIONS:
        assert not free_text & set(definition.items)


def test_expected_ids() -> None:
    types = ("depr", "angs", "esst", "adhs", "ptbs", "bipo", "psyc", "bord", "other")
    helps = ("niem", "haus", "kind", "schu", "psyo", "psya", "selb", "bera", "klin")
    treatments = ("not", "medi", "ther", "stat", "other")
    assert {d.id for d in diagnoses.DEFINITIONS} == {
        "diagnoses.diagnosis.reported",
        *(f"diagnoses.type.{o}" for o in types),
        *(f"diagnoses.help.{o}.diagnosed" for o in helps),
        "diagnoses.help_usage.sources.diagnosed",
        "diagnoses.help_patterns.combinations.diagnosed",
        *(f"diagnoses.treatment.{o}.diagnosed" for o in treatments),
    }


# --- legacy parity ------------------------------------------------------------------

#: Legacy key names of the diagnosis types and their option codes.
LEGACY_TYPES = {
    "Dep": "DEPR",
    "Angst": "ANGS",
    "Esss": "ESST",
    "ADHS": "ADHS",
    "PTBS": "PTBS",
    "BiPo": "BIPO",
    "Schizo": "PSYC",
    "Bord": "BORD",
}
#: Chart columns of the legacy help-source plot: (combination size, number of columns).
LEGACY_CHART = ((1, 2), (2, 2), (3, 2))


def _read(dataset: str) -> pd.DataFrame:
    return read_responses(FIXTURE_DIR / f"{dataset}.xlsx", "xlsx", SPEC)


def _share(metric: Proportion) -> float | None:
    return metric.share


@pytest.mark.parametrize("dataset", expected_datasets())
def test_legacy_parity(dataset: str) -> None:
    responses = _read(dataset)
    metrics = compute_metrics(responses, compute_features(responses, SPEC), SPEC)
    expected = load_expected(dataset)
    checked: set[str] = set()

    def check(key: str, new: float | None) -> None:
        assert_parity(dataset, key, new)
        checked.add(key)

    reported = proportion(metrics, REPORTED_ID)
    check("diagnoses.top.n", reported.k)
    check("diagnoses.top.pct", reported.share)

    for legacy, option in LEGACY_TYPES.items():
        metric = proportion(metrics, type_id(option))
        check(f"diagnoses.count.{legacy}", metric.k)
        check(f"diagnoses.pct.{legacy}", metric.share)

    for option in (
        "SCHU",
        "PSYO",
        "PSYA",
        "KIND",
        "HAUS",
        "SELB",
        "BERA",
        "KLIN",
        "NIEM",
    ):
        metric = proportion(metrics, help_id(option))
        check(f"diagnoses.help.count.{option}", metric.k)
        check(f"diagnoses.help.pct.{option}", metric.share)

    usage = metrics_usage(metrics)
    assert usage.shares is not None
    for category, count, share in zip(
        usage.categories, usage.counts, usage.shares, strict=True
    ):
        legacy = category.removesuffix("plus") + (
            "p" if category.endswith("plus") else ""
        )
        check(f"diagnoses.help_usage.n{legacy}", count)
        check(f"diagnoses.help_usage.p{legacy}", share)

    patterns = metrics[PATTERNS_ID]
    assert isinstance(patterns, PatternCounts)
    columns = [
        entry
        for size, columns_of_size in LEGACY_CHART
        for entry in top_patterns(patterns, size, columns_of_size)
    ]
    columns += [((), 0)] * (sum(n for _, n in LEGACY_CHART) - len(columns))
    for position, (pattern, count) in enumerate(columns, start=1):
        name = "+".join(pattern) or "empty"
        check(f"diagnoses.help_upset.K{position}.{name}", count)

    for option in ("THER", "MEDI", "STAT", "NOT"):
        metric = proportion(metrics, treatment_id(option))
        check(f"diagnoses.treatment.count.{option}", metric.k)
        check(f"diagnoses.treatment.pct.{option}", metric.share)

    assert checked == set(expected.under("diagnoses"))
