"""Structural validation: each rule on hand-made frames, and the acceptance tests.

Acceptance (R09): a fixture with injected errors gives exactly the expected findings;
a fixture with empty cells, including columns empty for every respondent, gives none.
Injected errors go through a CSV file and the production reader, as in a real run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from spot_report.ingest import (
    Finding,
    Rule,
    Severity,
    has_errors,
    read_csv_responses,
    validate,
    validate_bundle,
)
from spot_report.questionnaire import QuestionKind, QuestionnaireSpec, load_spec
from tests.conftest import BundleWriter, manifest_dict

STRING = pd.StringDtype(na_value=pd.NA)

SCALE_ITEM = "PHQ9[PHQQ1]"
OTHER_ITEM = "PHQ9[PHQQ2]"
SINGLE = "DQSEX"
MARKER = "DIAGQ1[DEPR]"
NUMERIC_QUESTION = "DQAGE"


@pytest.fixture(scope="module")
def spec() -> QuestionnaireSpec:
    return load_spec("2026.1")


def clean_frame(spec: QuestionnaireSpec, rows: int = 5) -> pd.DataFrame:
    """A hand-made frame with every required column and valid values."""
    data: dict[str, pd.Series] = {}
    for q in spec.questions:
        if not q.required:
            continue
        if q.code == spec.response_id or q.kind is QuestionKind.NUMERIC:
            low = q.min_value if q.min_value is not None else 1
            values = [low + i % 2 for i in range(rows)]
            if q.code == spec.response_id:
                values = list(range(1, rows + 1))
            data[q.code] = pd.Series(values, dtype="Int64")
            continue
        if q.kind is QuestionKind.SINGLE_CHOICE:
            cell = q.codes[0]
        elif q.kind is QuestionKind.MULTI_SELECT_OPTION:
            cell = q.selected or ""
        else:
            cell = "text"
        data[q.code] = pd.Series([cell] * rows, dtype=STRING)
    return pd.DataFrame(data)


def only(findings: tuple[Finding, ...], rule: Rule) -> list[Finding]:
    return [f for f in findings if f.rule is rule]


def finding(rule: Rule, column: str | None, count: int) -> Finding:
    return Finding(Severity.ERROR, rule, column, count)


# --- hand-made frames, one rule at a time ----------------------------------------


def test_clean_frame_has_no_findings(spec: QuestionnaireSpec) -> None:
    assert validate(clean_frame(spec), spec) == ()
    assert not has_errors(())


@pytest.mark.parametrize("code", ["PHQ9[PHQQ1]", "DQSEX", "DIAGQ1[DEPR]", "submitdate"])
def test_missing_required_column(spec: QuestionnaireSpec, code: str) -> None:
    df = clean_frame(spec).drop(columns=[code])
    assert validate(df, spec) == (finding(Rule.MISSING_COLUMN, code, 1),)


def test_missing_response_id_is_reported_once(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec).drop(columns=[spec.response_id])
    assert validate(df, spec) == (finding(Rule.MISSING_COLUMN, spec.response_id, 1),)


def test_optional_columns_may_be_absent(spec: QuestionnaireSpec) -> None:
    optional = [q.code for q in spec.questions if not q.required]
    assert optional
    df = clean_frame(spec)
    assert not set(optional) & set(df.columns)
    assert validate(df, spec) == ()


def test_optional_columns_are_checked_when_present(spec: QuestionnaireSpec) -> None:
    optional = next(
        q for q in spec.questions
        if not q.required and q.kind is QuestionKind.MULTI_SELECT_OPTION
    )  # fmt: skip
    df = clean_frame(spec)
    df[optional.code] = pd.Series(["nope", None, None, None, None], dtype=STRING)
    assert validate(df, spec) == (finding(Rule.INVALID_MARKER, optional.code, 1),)


def test_single_choice_code_not_allowed(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    df[SINGLE] = pd.Series(["M", "W", "X", "x", None], dtype=STRING)
    # Case matters; the empty cell is not counted.
    assert validate(df, spec) == (finding(Rule.INVALID_CODE, SINGLE, 2),)


def test_multi_select_marker_must_equal_selected(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    df[MARKER] = pd.Series(["Y", "y", "1", None, "Y"], dtype=STRING)
    assert validate(df, spec) == (finding(Rule.INVALID_MARKER, MARKER, 2),)


@pytest.mark.parametrize("code", [SCALE_ITEM, NUMERIC_QUESTION])
def test_numeric_out_of_range_on_both_sides(spec: QuestionnaireSpec, code: str) -> None:
    question = spec.question(code)
    assert question.min_value is not None
    assert question.max_value is not None
    df = clean_frame(spec)
    df[code] = pd.Series(
        [question.min_value - 1, question.min_value, question.max_value,
         question.max_value + 1, None],
        dtype="Int64",
    )  # fmt: skip
    assert validate(df, spec) == (finding(Rule.OUT_OF_RANGE, code, 2),)


def test_text_in_numeric_column_is_not_an_integer(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    # What the reader leaves behind: a text column. "7" is an integer but out of
    # range; "abc" and "1.5" are not integers; the empty cell is ignored.
    df[SCALE_ITEM] = pd.Series(["0", "abc", "1.5", "7", None], dtype=STRING)
    assert validate(df, spec) == (
        finding(Rule.NOT_AN_INTEGER, SCALE_ITEM, 2),
        finding(Rule.OUT_OF_RANGE, SCALE_ITEM, 1),
    )


def test_duplicate_ids_are_counted_as_repeated_rows(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    df[spec.response_id] = pd.Series([1, 2, 2, 2, 3], dtype="Int64")
    assert validate(df, spec) == (finding(Rule.DUPLICATE_ID, spec.response_id, 2),)


def test_empty_response_ids(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    df[spec.response_id] = pd.Series([1, None, 3, None, None], dtype="Int64")
    # Empty ids are not "duplicates of each other".
    assert validate(df, spec) == (finding(Rule.EMPTY_ID, spec.response_id, 3),)


def test_text_id_is_not_an_integer(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    df[spec.response_id] = pd.Series(["1", "2", "x", "4", "5"], dtype=STRING)
    assert validate(df, spec) == (finding(Rule.NOT_AN_INTEGER, spec.response_id, 1),)


def test_unchecked_columns_are_not_findings(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    df["submitdate"] = pd.Series(["not a date"] * 5, dtype=STRING)
    df["DIAGQ1[other]"] = pd.Series(["anything at all"] * 5, dtype=STRING)
    df["SomeNewColumn"] = pd.Series(["??"] * 5, dtype=STRING)
    assert validate(df, spec) == ()


def test_findings_are_sorted_and_deterministic(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec).drop(columns=["GAD7[GADQ1]", "DQSEX"])
    df[SCALE_ITEM] = pd.Series([9, 9, 0, 0, 0], dtype="Int64")
    df[MARKER] = pd.Series(["no"] * 5, dtype=STRING)
    first = validate(df, spec)
    assert first == validate(df.iloc[:, ::-1], spec)
    keys = [(f.rule.value, f.column) for f in first]
    assert keys == sorted(keys)
    assert has_errors(first)


def test_findings_hold_no_values(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    df[SINGLE] = pd.Series(["SECRET-CODE"] * 5, dtype=STRING)
    df[SCALE_ITEM] = pd.Series(["SECRET-TEXT", "0", "0", "0", "0"], dtype=STRING)
    text = repr(validate(df, spec))
    assert "SECRET" not in text


# --- empty cells are never a finding (D12) --------------------------------------------


def checkable_columns(spec: QuestionnaireSpec) -> list[str]:
    return [c for c in spec.known_columns if c != spec.response_id]


def test_scattered_empty_cells_everywhere(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec, rows=9)
    for position, code in enumerate(checkable_columns(spec)):
        if code in df.columns:
            df.loc[position % 4 :: 4, code] = pd.NA
    assert validate(df, spec) == ()


@pytest.mark.parametrize("code", ["PHQ9[PHQQ1]", "DQAGE", "DQSEX", "DIAGQ1[DEPR]"])
def test_a_column_empty_for_every_respondent(
    spec: QuestionnaireSpec, code: str
) -> None:
    df = clean_frame(spec)
    df[code] = pd.Series([pd.NA] * 5, dtype=df[code].dtype)
    assert validate(df, spec) == ()


def test_every_column_empty_for_every_respondent_in_turn(
    spec: QuestionnaireSpec,
) -> None:
    for code in checkable_columns(spec):
        df = clean_frame(spec)
        if code in df.columns:
            df[code] = pd.Series([pd.NA] * 5, dtype=df[code].dtype)
        assert validate(df, spec) == (), code


def test_all_cells_empty_except_the_id(spec: QuestionnaireSpec) -> None:
    df = clean_frame(spec)
    for code in checkable_columns(spec):
        if code in df.columns:
            df[code] = pd.Series([pd.NA] * 5, dtype=df[code].dtype)
    assert validate(df, spec) == ()


def test_an_empty_scale_column_that_stayed_text_is_not_a_finding(
    spec: QuestionnaireSpec,
) -> None:
    df = clean_frame(spec)
    df[SCALE_ITEM] = pd.Series([pd.NA] * 5, dtype=STRING)
    assert validate(df, spec) == ()


# --- acceptance on a fixture ----------------------------------------------------------


def read_modified(
    raw: pd.DataFrame, tmp_path: Path, spec: QuestionnaireSpec
) -> pd.DataFrame:
    path = tmp_path / "modified.csv"
    raw.to_csv(path, index=False, lineterminator="\n")
    return read_csv_responses(path, spec)


def test_unmodified_fixture_has_no_findings(
    raw_fixture: pd.DataFrame, tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    assert validate(read_modified(raw_fixture, tmp_path, spec), spec) == ()


def test_injected_errors_give_exactly_the_expected_findings(
    raw_fixture: pd.DataFrame, tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    raw = raw_fixture
    raw.loc[0:2, "PHQ9[PHQQ1]"] = "4711"  # out of range, 3 cells
    raw.loc[5:6, "DQSEX"] = "ZZ99"  # unknown code, 2 cells
    raw.loc[10, "GAD7[GADQ3]"] = "3.5x"  # not an integer
    raw.loc[11, "GAD7[GADQ3]"] = "9"  # integer, out of range
    raw.loc[3:6, "DIAGQ1[DEPR]"] = "Q"  # wrong marker, 4 cells
    raw.loc[21, "id"] = raw.loc[20, "id"]  # duplicated id
    raw.loc[30, "id"] = ""  # response without id
    raw = raw.drop(columns=["FEHLTAGQ0"])  # required column missing

    findings = validate(read_modified(raw, tmp_path, spec), spec)

    assert findings == (
        finding(Rule.DUPLICATE_ID, "id", 1),
        finding(Rule.EMPTY_ID, "id", 1),
        finding(Rule.INVALID_CODE, "DQSEX", 2),
        finding(Rule.INVALID_MARKER, "DIAGQ1[DEPR]", 4),
        finding(Rule.MISSING_COLUMN, "FEHLTAGQ0", 1),
        finding(Rule.NOT_AN_INTEGER, "GAD7[GADQ3]", 1),
        finding(Rule.OUT_OF_RANGE, "GAD7[GADQ3]", 1),
        finding(Rule.OUT_OF_RANGE, "PHQ9[PHQQ1]", 3),
    )
    assert has_errors(findings)
    assert "4711" not in repr(findings)
    assert "ZZ99" not in repr(findings)


def test_injected_empty_cells_give_no_findings(
    raw_fixture: pd.DataFrame, tmp_path: Path, spec: QuestionnaireSpec
) -> None:
    raw = raw_fixture
    for code in ("PHQ9[PHQQ1]", "PHQ9[PHQQ5]", "GAD7[GADQ2]", "SIPHQ", "DQAGE"):
        raw.loc[::7, code] = ""  # scattered empty scale items and numbers
    raw["FEHLTAGQ1"] = ""  # a follow-up question nobody saw
    raw["GAD7[GADQ4]"] = ""  # a scale item empty for every respondent
    raw["DQSEX"] = ""  # a single-choice column empty for every respondent
    raw["DIAGQ2[NIEM]"] = ""  # a multi-select option nobody ticked

    df = read_modified(raw, tmp_path, spec)

    assert df["FEHLTAGQ1"].isna().all()
    assert df["GAD7[GADQ4]"].isna().all()
    assert validate(df, spec) == ()


# --- bundles --------------------------------------------------------------------------


def test_validate_bundle_clean(
    raw_fixture: pd.DataFrame, write_bundle: BundleWriter
) -> None:
    assert validate_bundle(write_bundle(raw_fixture)) == ()


def test_validate_bundle_reports_data_findings(
    raw_fixture: pd.DataFrame, write_bundle: BundleWriter
) -> None:
    raw_fixture.loc[0, "DQSEX"] = "ZZ99"
    assert validate_bundle(write_bundle(raw_fixture)) == (
        finding(Rule.INVALID_CODE, "DQSEX", 1),
    )


def test_missing_bundle_directory_is_an_invalid_manifest(tmp_path: Path) -> None:
    (result,) = validate_bundle(tmp_path / "nothing-here")
    assert (result.severity, result.rule) == (Severity.ERROR, Rule.INVALID_MANIFEST)
    assert result.column is None
    assert "manifest.json" in result.message


def test_malformed_manifest(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{not json")
    (result,) = validate_bundle(tmp_path)
    assert result.rule is Rule.INVALID_MANIFEST


def test_manifest_violating_the_schema(tmp_path: Path) -> None:
    manifest = manifest_dict()
    del manifest["wave"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (result,) = validate_bundle(tmp_path)
    assert result.rule is Rule.INVALID_MANIFEST
    assert "wave" in result.message


def test_unknown_questionnaire_version(tmp_path: Path) -> None:
    manifest = manifest_dict(survey={"questionnaire_version": "1999.9"})
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (result,) = validate_bundle(tmp_path)
    assert result.rule is Rule.UNKNOWN_VERSION
    assert "1999.9" not in result.message


def test_responses_file_missing(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(manifest_dict()))
    (result,) = validate_bundle(tmp_path)
    assert (result.severity, result.rule) == (Severity.ERROR, Rule.UNREADABLE_FILE)
    assert "responses.csv" in result.message


def test_responses_file_in_the_wrong_format(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(manifest_dict()))
    (tmp_path / "responses.csv").write_text("id;DQSEX\n1;SECRET\n")
    (result,) = validate_bundle(tmp_path)
    assert result.rule is Rule.UNREADABLE_FILE
    assert "SECRET" not in result.message
