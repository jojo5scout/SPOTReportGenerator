"""Derived per-person features (R12) on hand-made responses and on every fixture.

Hand-made responses use the reader's dtypes (``Int64`` for numeric columns,
``string`` with ``pd.NA`` for codes); one test checks that the reader itself gives the
same features for the same rows.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from spot_report.features import (
    BOOLEAN_FEATURES,
    CATEGORY_FEATURES,
    GAD7_SEVERITY_CATEGORIES,
    PHQ9_SEVERITY_CATEGORIES,
    SYMPTOM_CATEGORIES,
    FeatureInputError,
    compute_features,
    feature_columns,
    integer_features,
    option_selected,
)
from spot_report.ingest import read_csv_responses, read_responses
from spot_report.metrics.types import Proportion
from spot_report.questionnaire import QuestionKind, load_spec, spec_from_mapping

SPEC = load_spec("2026.1")
STRING = pd.StringDtype(na_value=pd.NA)
FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURES = sorted(
    p for p in FIXTURE_DIR.iterdir() if p.suffix.lower() in {".csv", ".xlsx"}
)

PHQ9 = SPEC.scale("PHQ9").columns
GAD7 = SPEC.scale("GAD7").columns
RES = SPEC.scale("RES").columns
SBI = SPEC.scale("SBI")
EXHAUSTION = SBI.subscale("EXHAUSTION").columns
CYNICISM = SBI.subscale("CYNICISM").columns

Row = dict[str, Any]


# --- building responses with the reader's dtypes --------------------------------------


def _is_integer(code: str) -> bool:
    return code == SPEC.response_id or SPEC.question(code).kind is QuestionKind.NUMERIC


def base_row() -> Row:
    """A complete response: every required column, all scale items 0, no diagnosis."""
    row: Row = dict.fromkeys(SPEC.required_columns)
    for scale in SPEC.scales:
        row.update(dict.fromkeys(scale.columns, 0))
    row.update(
        DQSEX="W",
        DQSTUFE="Gym2",
        DQAGE=15,
        SIPHQ=0,
        DIAGQ0="Nein",
        FEHLTAGQ0="FENE",
    )
    return row


def spread(columns: Sequence[str], total: int, item_max: int) -> Row:
    """Item values that add up to ``total``, filling items up to ``item_max``."""
    values: Row = {}
    rest = total
    for code in columns:
        values[code] = min(rest, item_max)
        rest -= values[code]
    assert rest == 0, "total exceeds the scale maximum"
    return values


def responses(
    *rows: Mapping[str, Any], index: Sequence[object] | None = None
) -> pd.DataFrame:
    """A DataFrame like the reader's: base row updated by each ``rows`` entry."""
    full = []
    for number, changes in enumerate(rows, start=1):
        row = base_row() | {"id": number}
        row.update(changes)
        full.append(row)
    columns = list(dict.fromkeys(code for row in [base_row(), *full] for code in row))
    data = {
        code: pd.Series(
            [row.get(code) for row in full],
            dtype=pd.Int64Dtype() if _is_integer(code) else STRING,
        )
        for code in columns
    }
    frame = pd.DataFrame(data, columns=columns)
    if index is not None:
        frame.index = pd.Index(index)
    return frame


@contextmanager
def silent(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail on any warning or log record emitted inside the block."""
    caplog.clear()
    with caplog.at_level(logging.DEBUG), warnings.catch_warnings():
        warnings.simplefilter("error")
        yield
    assert caplog.records == []


# --- complete responses ---------------------------------------------------------------


def test_complete_response_by_hand(caplog: pytest.LogCaptureFixture) -> None:
    row: Row = {
        # PHQ-9: 1+2+0+3+1+0+2+1+1 = 11
        **dict(zip(PHQ9, [1, 2, 0, 3, 1, 0, 2, 1, 1], strict=True)),
        # GAD-7: 0+1+1+0+2+0+0 = 4
        **dict(zip(GAD7, [0, 1, 1, 0, 2, 0, 0], strict=True)),
        # RES: 4+3+2+1+0+4+3+2+1+0 = 20
        **dict(zip(RES, [4, 3, 2, 1, 0, 4, 3, 2, 1, 0], strict=True)),
        # SBI exhaustion 5+4+3+2 = 14, cynicism 1+0+1+0+1 = 3, total 17
        **dict(zip(EXHAUSTION, [5, 4, 3, 2], strict=True)),
        **dict(zip(CYNICISM, [1, 0, 1, 0, 1], strict=True)),
        "SIPHQ": 2,
        "DIAGQ0": "Ja",
        "DIAGQ3[MEDI]": "Y",
    }
    with silent(caplog):
        features = compute_features(responses(row), SPEC)
    got = features.iloc[0].to_dict()
    assert got == {
        "phq9_sum": 11,
        "gad7_sum": 4,
        "phq9_severity": "moderate",
        "gad7_severity": "minimal",
        "phq9_cutoff": True,
        "gad7_cutoff": False,
        "burdened": True,
        "symptom_category": "severe",
        "phq9_item9": 1,
        "impairment": 2,
        "diagnosis": True,
        "treatment_any": True,
        "res_sum": 20,
        "sbi_exhaustion_sum": 14,
        "sbi_cynicism_sum": 3,
        "sbi_total_sum": 17,
    }


def test_columns_and_dtypes_follow_the_contract() -> None:
    features = compute_features(responses({}, {}), SPEC)
    assert tuple(features.columns) == feature_columns(SPEC)
    for column in integer_features(SPEC):
        assert features[column].dtype == pd.Int64Dtype(), column
    for column in BOOLEAN_FEATURES:
        assert features[column].dtype == pd.BooleanDtype(), column
    assert features["phq9_severity"].cat.ordered
    assert tuple(features["phq9_severity"].cat.categories) == PHQ9_SEVERITY_CATEGORIES
    assert tuple(features["gad7_severity"].cat.categories) == GAD7_SEVERITY_CATEGORIES
    category = features["symptom_category"]
    assert category.cat.ordered
    assert (
        tuple(category.cat.categories)
        == SYMPTOM_CATEGORIES
        == (
            "mildnone",
            "medium",
            "severe",
        )
    )
    assert set(CATEGORY_FEATURES) | set(BOOLEAN_FEATURES) | set(
        integer_features(SPEC)
    ) == set(feature_columns(SPEC))


def test_index_is_preserved() -> None:
    df = responses({}, {}, {}, index=[30, 10, 20])
    features = compute_features(df, SPEC)
    assert features.index.equals(df.index)


def test_no_responses_give_an_empty_table() -> None:
    features = compute_features(responses(), SPEC)
    assert len(features) == 0
    assert tuple(features.columns) == feature_columns(SPEC)
    assert features["phq9_sum"].dtype == pd.Int64Dtype()
    assert features["burdened"].dtype == pd.BooleanDtype()


PHQ9_BOUNDARIES = [
    (0, "minimal", False),
    (4, "minimal", False),
    (5, "mild", False),
    (9, "mild", False),
    (10, "moderate", True),
    (14, "moderate", True),
    (15, "moderately_severe", True),
    (19, "moderately_severe", True),
    (20, "severe", True),
    (27, "severe", True),
]


@pytest.mark.parametrize(("total", "category", "cutoff"), PHQ9_BOUNDARIES)
def test_phq9_severity_and_cutoff_at_band_boundaries(
    total: int, category: str, cutoff: bool
) -> None:
    features = compute_features(responses(spread(PHQ9, total, 3)), SPEC)
    assert features.at[0, "phq9_sum"] == total
    assert features.at[0, "phq9_severity"] == category
    assert features.at[0, "phq9_cutoff"] == cutoff


GAD7_BOUNDARIES = [
    (0, "minimal", False),
    (4, "minimal", False),
    (5, "mild", False),
    (9, "mild", False),
    (10, "moderate", True),
    (14, "moderate", True),
    (15, "severe", True),
    (21, "severe", True),
]


@pytest.mark.parametrize(("total", "category", "cutoff"), GAD7_BOUNDARIES)
def test_gad7_severity_and_cutoff_at_band_boundaries(
    total: int, category: str, cutoff: bool
) -> None:
    features = compute_features(responses(spread(GAD7, total, 3)), SPEC)
    assert features.at[0, "gad7_sum"] == total
    assert features.at[0, "gad7_severity"] == category
    assert features.at[0, "gad7_cutoff"] == cutoff


# --- a scale with one empty item ------------------------------------------------------

# The complete response has PHQ-9 12 and GAD-7 6: without PHQ-9, burdened cannot be
# determined (GAD-7 is below its cut-off), nor the symptom category; without GAD-7,
# PHQ-9 alone decides both.
EMPTY_ITEM_CASES = [
    (
        PHQ9[3],
        {"phq9_sum", "phq9_severity", "phq9_cutoff", "burdened", "symptom_category"},
    ),
    (
        PHQ9[8],
        {
            "phq9_sum",
            "phq9_severity",
            "phq9_cutoff",
            "burdened",
            "symptom_category",
            "phq9_item9",
        },
    ),
    (GAD7[0], {"gad7_sum", "gad7_severity", "gad7_cutoff"}),
    (RES[9], {"res_sum"}),
    (EXHAUSTION[1], {"sbi_exhaustion_sum", "sbi_total_sum"}),
    (CYNICISM[0], {"sbi_cynicism_sum", "sbi_total_sum"}),
]


@pytest.mark.parametrize(("empty", "missing"), EMPTY_ITEM_CASES)
def test_one_empty_item_makes_only_that_score_missing(
    empty: str, missing: set[str], caplog: pytest.LogCaptureFixture
) -> None:
    complete = {**spread(PHQ9, 12, 3), **spread(GAD7, 6, 3), **spread(RES, 25, 4)}
    with silent(caplog):
        features = compute_features(responses(complete | {empty: None}), SPEC)
    row = features.iloc[0]
    assert {column for column, value in row.items() if pd.isna(value)} == missing


def test_one_empty_item_does_not_affect_other_respondents() -> None:
    df = responses(spread(PHQ9, 12, 3) | {PHQ9[0]: None}, spread(PHQ9, 12, 3))
    features = compute_features(df, SPEC)
    assert features["phq9_sum"].isna().tolist() == [True, False]
    assert features.at[1, "phq9_sum"] == 12


def test_a_score_missing_is_left_out_of_its_denominator() -> None:
    df = responses(
        spread(PHQ9, 12, 3),
        spread(PHQ9, 3, 3),
        spread(PHQ9, 12, 3) | {PHQ9[2]: None},
    )
    cutoff = compute_features(df, SPEC)["phq9_cutoff"]
    metric = Proportion.from_mask(cutoff.dropna(), n_missing=int(cutoff.isna().sum()))
    assert (metric.k, metric.n, metric.n_missing) == (1, 2, 1)


# --- burdened -------------------------------------------------------------------------

# (PHQ-9 sum, GAD-7 sum, burdened); None means the score is missing (one empty item).
BURDENED_TABLE = [
    (9, 9, False),
    (10, 9, True),
    (9, 10, True),
    (10, 10, True),
    (10, None, True),
    (None, 10, True),
    (9, None, None),
    (None, 9, None),
    (None, None, None),
]


@pytest.mark.parametrize(("phq9", "gad7", "expected"), BURDENED_TABLE)
def test_burdened_truth_table(
    phq9: int | None, gad7: int | None, expected: bool | None
) -> None:
    row: Row = {}
    for columns, total in ((PHQ9, phq9), (GAD7, gad7)):
        if total is None:
            row |= spread(columns, 9, 3) | {columns[0]: None}
        else:
            row |= spread(columns, total, 3)
    burdened = compute_features(responses(row), SPEC).at[0, "burdened"]
    if expected is None:
        assert burdened is pd.NA
    else:
        assert burdened == expected


# (PHQ-9 sum, GAD-7 sum, symptom category); None means the score is missing.
SYMPTOM_CATEGORY_TABLE = [
    (0, 0, "mildnone"),
    (4, 4, "mildnone"),
    (5, 0, "medium"),
    (0, 5, "medium"),
    (9, 9, "medium"),
    (10, 0, "severe"),
    (0, 10, "severe"),
    (27, 21, "severe"),
    (12, None, "severe"),  # the present score decides although the other is missing
    (None, 10, "severe"),
    (9, None, None),  # the missing score could be 10 or more
    (0, None, None),
    (None, 4, None),
    (None, None, None),
]


@pytest.mark.parametrize(("phq9", "gad7", "expected"), SYMPTOM_CATEGORY_TABLE)
def test_symptom_category_truth_table(
    phq9: int | None, gad7: int | None, expected: str | None
) -> None:
    row: Row = {}
    for columns, total in ((PHQ9, phq9), (GAD7, gad7)):
        if total is None:
            row |= spread(columns, 9, 3) | {columns[0]: None}
        else:
            row |= spread(columns, total, 3)
    category = compute_features(responses(row), SPEC).at[0, "symptom_category"]
    if expected is None:
        assert category is pd.NA or pd.isna(category)
    else:
        assert category == expected


# --- an empty multi-select option -----------------------------------------------------

TREATMENT_CASES = [
    ({}, False),  # every option empty: nothing selected
    ({"DIAGQ3[NOT]": "Y"}, False),  # the none option is not a treatment
    ({"DIAGQ3[MEDI]": "Y"}, True),
    ({"DIAGQ3[THER]": "Y"}, True),
    ({"DIAGQ3[THER]": "Y", "DIAGQ3[NOT]": "Y"}, True),  # as in the previous program
    ({"DIAGQ3[STAT]": None}, False),  # optional, present, empty
    ({"DIAGQ3[STAT]": "Y"}, True),  # optional option present and selected
    # A filled "other" text is a chosen option (ADR 0004); only filled-or-not counts.
    ({"DIAGQ3[other]": "x"}, True),
    ({"DIAGQ3[other]": "   "}, False),
    ({"DIAGQ3[other]": "x", "DIAGQ3[NOT]": "Y"}, True),
]


@pytest.mark.parametrize(("options", "expected"), TREATMENT_CASES)
def test_treatment_any(
    options: Row, expected: bool, caplog: pytest.LogCaptureFixture
) -> None:
    with silent(caplog):
        features = compute_features(responses(options | {"DIAGQ0": "Ja"}), SPEC)
    assert features.at[0, "treatment_any"] == expected


def test_empty_multi_select_option_keeps_the_respondent_in_the_denominator(
    caplog: pytest.LogCaptureFixture,
) -> None:
    df = responses({"DIAGQ3[MEDI]": "Y"}, {}, {"DIAGQ3[NOT]": "Y"})
    with silent(caplog):
        treatment = compute_features(df, SPEC)["treatment_any"]
    assert treatment.tolist() == [True, False, False]
    assert not treatment.isna().any()
    metric = Proportion.from_mask(treatment, n_missing=0)
    assert (metric.k, metric.n, metric.n_missing) == (1, 3, 0)


def test_treatment_options_come_from_the_spec() -> None:
    raw = yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "src/spot_report/questionnaire/specs/2026.1.yaml"
        ).read_text(encoding="utf-8")
    )
    del raw["multi_select"]["DIAGQ3"]["none_option"]
    without_none_option = spec_from_mapping(raw)
    df = responses({"DIAGQ3[NOT]": "Y"})
    assert not compute_features(df, SPEC).at[0, "treatment_any"]
    assert compute_features(df, without_none_option).at[0, "treatment_any"]


# --- an empty follow-up question ------------------------------------------------------


def test_empty_diagnosis_question_is_left_out_of_its_denominator(
    caplog: pytest.LogCaptureFixture,
) -> None:
    df = responses({"DIAGQ0": "Ja"}, {"DIAGQ0": "Nein"}, {"DIAGQ0": None})
    with silent(caplog):
        diagnosis = compute_features(df, SPEC)["diagnosis"]
    assert diagnosis.dtype == pd.BooleanDtype()
    assert diagnosis.iloc[:2].tolist() == [True, False]
    assert diagnosis.iloc[2] is pd.NA

    metric = Proportion.from_mask(
        diagnosis.dropna(), n_missing=int(diagnosis.isna().sum())
    )
    assert (metric.k, metric.n, metric.n_missing) == (1, 2, 1)


def test_empty_numeric_follow_up_questions_are_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    df = responses({"SIPHQ": None}, {"SIPHQ": 3})
    with silent(caplog):
        features = compute_features(df, SPEC)
    assert features["impairment"].isna().tolist() == [True, False]
    assert features.at[1, "impairment"] == 3


def test_display_conditions_are_not_modelled() -> None:
    # Treatment options ticked without a diagnosis still count; restricting the
    # denominator to diagnosed respondents is up to the metric.
    df = responses({"DIAGQ0": "Nein", "DIAGQ3[THER]": "Y"}, {"DIAGQ0": None})
    features = compute_features(df, SPEC)
    assert features["treatment_any"].tolist() == [True, False]


# --- input errors (ruled out by validation) -------------------------------------------


def test_missing_required_column_is_an_input_error() -> None:
    df = responses({}).drop(columns=[PHQ9[4]])
    with pytest.raises(FeatureInputError, match=r"PHQ9\[PHQQ5\] is missing"):
        compute_features(df, SPEC)


def test_numeric_column_left_as_text_is_an_input_error() -> None:
    df = responses({})
    df["SIPHQ"] = df["SIPHQ"].astype(STRING)
    with pytest.raises(FeatureInputError, match="SIPHQ is not Int64"):
        compute_features(df, SPEC)


def test_code_column_with_nan_semantics_is_an_input_error() -> None:
    df = responses({})
    df["DIAGQ0"] = df["DIAGQ0"].astype(pd.StringDtype(na_value=float("nan")))
    with pytest.raises(FeatureInputError, match="DIAGQ0 is not a string column"):
        compute_features(df, SPEC)


# --- reader and fixtures --------------------------------------------------------------


def test_reader_gives_the_same_features(tmp_path: Path) -> None:
    df = responses(
        spread(PHQ9, 12, 3) | {"DIAGQ0": "Ja", "DIAGQ3[THER]": "Y"},
        {PHQ9[0]: None, "DIAGQ0": None, "SIPHQ": None},
    )
    path = tmp_path / "responses.csv"
    df.to_csv(path, index=False, lineterminator="\n")
    read = read_csv_responses(path, SPEC)
    pd.testing.assert_frame_equal(
        compute_features(read, SPEC), compute_features(df, SPEC)
    )


def _load(path: Path) -> pd.DataFrame:
    return read_responses(path, path.suffix.lower().lstrip("."), SPEC)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_features(path: Path, caplog: pytest.LogCaptureFixture) -> None:
    df = _load(path)
    with silent(caplog):
        features = compute_features(df, SPEC)
    assert features.index.equals(df.index)
    assert tuple(features.columns) == feature_columns(SPEC)
    for column in integer_features(SPEC):
        assert features[column].dtype == pd.Int64Dtype(), column
    for column in BOOLEAN_FEATURES:
        assert features[column].dtype == pd.BooleanDtype(), column
    for column in CATEGORY_FEATURES:
        assert isinstance(features[column].dtype, pd.CategoricalDtype), column

    # Fixture scales are complete, so no score (or anything derived from it) is NA.
    scores = [c for c in integer_features(SPEC) if c.endswith("_sum")]
    derived = [*scores, *CATEGORY_FEATURES, "phq9_cutoff", "gad7_cutoff", "burdened"]
    missing = {c: int(n) for c, n in features[derived].isna().sum().items() if n}
    assert missing == {}
    assert not features["treatment_any"].isna().any()

    ranges = {"phq9_sum": 27, "gad7_sum": 21, "res_sum": 40, "sbi_total_sum": 45}
    for column, maximum in ranges.items():
        assert features[column].between(0, maximum).all(), column


@pytest.mark.parametrize(
    "stem", sorted({p.stem for p in FIXTURES}), ids=lambda stem: stem
)
def test_fixture_formats_give_identical_features(stem: str) -> None:
    paths = [p for p in FIXTURES if p.stem == stem]
    if len(paths) < 2:
        pytest.skip("only one format present")
    first, *others = (compute_features(_load(p), SPEC) for p in paths)
    for other in others:
        pd.testing.assert_frame_equal(first, other)


def test_option_selected_is_never_missing() -> None:
    df = responses({"DIAGQ2[PSYO]": "Y"}, {})
    ticked = option_selected(df, SPEC.question("DIAGQ2[PSYO]"))
    assert ticked.tolist() == [True, False]
    assert not ticked.isna().any()
    # An optional option column that is absent counts as not selected.
    klin = SPEC.question("DIAGQ2[KLIN]")
    assert klin.code not in df.columns
    assert option_selected(df, klin).tolist() == [False, False]
