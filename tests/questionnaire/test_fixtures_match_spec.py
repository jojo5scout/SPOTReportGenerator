"""Every synthetic fixture must be consistent with the questionnaire spec.

Messages contain column codes and counts only, never response values.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spot_report.questionnaire import QuestionKind, QuestionnaireSpec, load_spec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE_FILES = sorted(FIXTURES.glob("*.xlsx"))


@pytest.fixture(scope="module")
def spec() -> QuestionnaireSpec:
    return load_spec("2026.1")


@pytest.fixture(scope="module", params=FIXTURE_FILES, ids=lambda p: p.name)
def frame(request: pytest.FixtureRequest) -> pd.DataFrame:
    # Read every cell as text so that codes compare as written; empty cells become NaN.
    return pd.read_excel(request.param, dtype=str)


def test_fixtures_exist() -> None:
    assert FIXTURE_FILES


def test_every_required_spec_column_is_in_the_fixture(
    spec: QuestionnaireSpec, frame: pd.DataFrame
) -> None:
    missing = [c for c in spec.required_columns if c not in frame.columns]
    assert not missing, f"{len(missing)} required spec columns missing: {missing}"


def test_optional_spec_columns_may_be_absent_but_nothing_else(
    spec: QuestionnaireSpec, frame: pd.DataFrame
) -> None:
    absent = set(spec.known_columns) - set(frame.columns)
    optional = set(spec.known_columns) - set(spec.required_columns)
    assert absent <= optional


def test_every_fixture_column_is_known_to_the_spec(
    spec: QuestionnaireSpec, frame: pd.DataFrame
) -> None:
    unknown = [c for c in frame.columns if c not in set(spec.known_columns)]
    assert not unknown, f"{len(unknown)} fixture columns unknown to the spec: {unknown}"


def test_response_id_is_unique(spec: QuestionnaireSpec, frame: pd.DataFrame) -> None:
    ids = frame[spec.response_id]
    assert ids.notna().all()
    assert ids.is_unique


def test_every_non_empty_value_is_allowed(
    spec: QuestionnaireSpec, frame: pd.DataFrame
) -> None:
    problems: list[str] = []
    for column in frame.columns:
        question = spec.question(column)
        values = frame[column].dropna()
        if question.kind is QuestionKind.SINGLE_CHOICE:
            bad = int((~values.isin(question.codes)).sum())
        elif question.kind is QuestionKind.MULTI_SELECT_OPTION:
            bad = int((values != question.selected).sum())
        elif question.kind is QuestionKind.NUMERIC:
            numbers = pd.to_numeric(values, errors="coerce")
            assert question.min_value is not None
            assert question.max_value is not None
            outside = ~numbers.between(question.min_value, question.max_value)
            bad = int((outside | (numbers != numbers.round())).sum())
        else:  # metadata and free text are not value-checked
            continue
        if bad:
            problems.append(f"{column}: {bad} of {len(values)} values not allowed")
    assert not problems, "; ".join(problems)
