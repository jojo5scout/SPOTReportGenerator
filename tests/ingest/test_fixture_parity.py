"""Acceptance test of R08: the same dataset as CSV and as XLSX reads identically.

Compared with ``assert_frame_equal`` including dtypes, index and column order, for
every fixture. Assertion messages are pandas' own and contain no cell values beyond
what pandas prints for a mismatch; the fixtures are synthetic anyway.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from spot_report.ingest import read_responses, unconverted_columns
from spot_report.questionnaire import QuestionnaireSpec, load_spec

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
XLSX_FILES = sorted(FIXTURES.glob("*.xlsx"))


@pytest.fixture(scope="module")
def spec() -> QuestionnaireSpec:
    return load_spec("2026.1")


def test_fixtures_exist() -> None:
    assert XLSX_FILES


@pytest.mark.parametrize("xlsx", XLSX_FILES, ids=lambda p: p.name)
def test_every_xlsx_fixture_has_a_csv_version(xlsx: Path) -> None:
    assert xlsx.with_suffix(".csv").is_file()


@pytest.mark.parametrize("xlsx", XLSX_FILES, ids=lambda p: p.name)
def test_csv_and_xlsx_give_identical_frames(
    xlsx: Path, spec: QuestionnaireSpec
) -> None:
    from_csv = read_responses(xlsx.with_suffix(".csv"), "csv", spec)
    from_xlsx = read_responses(xlsx, "xlsx", spec)
    pd.testing.assert_frame_equal(from_csv, from_xlsx, check_exact=True)


@pytest.mark.parametrize("xlsx", XLSX_FILES, ids=lambda p: p.name)
def test_fixture_dtypes_follow_the_spec(xlsx: Path, spec: QuestionnaireSpec) -> None:
    df = read_responses(xlsx, "xlsx", spec)
    assert unconverted_columns(df, spec) == ()
    numeric = [q.code for q in spec.questions if q.code in df.columns and q.scale]
    assert numeric
    assert all(df[code].dtype == pd.Int64Dtype() for code in numeric)
    assert df["id"].dtype == pd.Int64Dtype()
    assert df["DQSEX"].dtype == pd.StringDtype(na_value=pd.NA)
    assert df["id"].is_unique
