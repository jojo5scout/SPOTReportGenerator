"""The committed CSV fixtures are exactly what the generator produces."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.make_csv_fixtures import FIXTURE_DIR, main, xlsx_to_csv_bytes

XLSX_FILES = sorted(FIXTURE_DIR.glob("*.xlsx"))


@pytest.mark.parametrize("xlsx", XLSX_FILES, ids=lambda p: p.name)
def test_committed_csv_is_up_to_date(xlsx: Path) -> None:
    assert xlsx.with_suffix(".csv").read_bytes() == xlsx_to_csv_bytes(xlsx)


def test_check_mode_succeeds() -> None:
    assert main(["--check"]) == 0


@pytest.mark.parametrize("xlsx", XLSX_FILES, ids=lambda p: p.name)
def test_csv_has_the_limesurvey_layout(xlsx: Path) -> None:
    raw = xlsx.with_suffix(".csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
    assert b"\r" not in raw  # LF line endings
    assert raw.endswith(b"\n")
    assert b'"' not in raw  # nothing needs quoting
    widths = {line.count(b",") for line in raw.splitlines()}
    assert len(widths) == 1
