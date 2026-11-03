"""Every dataset in tests/fixtures/ is a synthetic, code-only response table.

The tests are parametrised over the files present, so a new fixture is checked as soon
as it is added. Assertion messages contain counts and column codes only, never cell
values.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_SUFFIXES = frozenset({".xlsx", ".csv"})
FIXTURES = sorted(
    p for p in FIXTURE_DIR.iterdir() if p.suffix.lower() in FIXTURE_SUFFIXES
)

# A question code such as `DQAGE` or `PHQ9[PHQQ1]`: no spaces, no sentences.
HEADING_CODE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\[[A-Za-z0-9_]+\])?")
# Answer codes are numbers, ISO dates or short tokens; texts would be longer.
MAX_CODE_LENGTH = 20


def load_fixture(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def test_fixtures_are_present() -> None:
    assert FIXTURES, "no fixture files found in tests/fixtures/"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_loads_and_is_not_empty(path: Path) -> None:
    df = load_fixture(path)
    assert len(df) > 0
    assert len(df.columns) > 0


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_headings_are_question_codes(path: Path) -> None:
    df = load_fixture(path)
    not_codes = [
        i for i, c in enumerate(df.columns) if not HEADING_CODE.fullmatch(str(c))
    ]
    assert not_codes == [], f"headings at positions {not_codes} are not codes"
    assert df.columns.is_unique


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_cells_are_codes_not_texts(path: Path) -> None:
    df = load_fixture(path)
    for column in df.columns:
        values = df[column].dropna()
        if pd.api.types.is_numeric_dtype(values):
            continue
        as_text = values.astype(str)
        too_long = int((as_text.str.len() > MAX_CODE_LENGTH).sum())
        with_space = int(as_text.str.contains(r"\s", regex=True).sum())
        assert too_long == 0, f"{column}: {too_long} cells longer than a code"
        assert with_space == 0, f"{column}: {with_space} cells contain whitespace"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_fixture_response_ids_are_unique(path: Path) -> None:
    df = load_fixture(path)
    assert "id" in df.columns
    assert df["id"].is_unique
