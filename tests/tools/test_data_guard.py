from __future__ import annotations

import pytest

from tools.data_guard import find_violations, main


@pytest.mark.parametrize(
    "path",
    [
        "src/spot_report/dummy.xlsx",
        "responses.csv",
        "docs/export.XLSX",
        "store.sqlite",
        "examples/other/data.csv",
        "tests/fixtures_old/data.csv",
        "tests/survey.lss",
    ],
)
def test_rejects_data_files_outside_allowed_dirs(path: str) -> None:
    assert find_violations([path]) == [path]


@pytest.mark.parametrize(
    "path",
    [
        "tests/fixtures/synthetic_school.xlsx",
        "tests/fixtures/sub/dir/responses.csv",
        "examples/content-demo/labels.csv",
        "./tests/fixtures/responses.csv",
        "src/spot_report/cli.py",
        "tests/fixtures/expected/demo.json",
        "docs/architecture.md",
    ],
)
def test_allows_other_files_and_allowed_dirs(path: str) -> None:
    assert find_violations([path]) == []


def test_main_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tests/fixtures/a.csv", "README.md"]) == 0
    assert main(["tests/fixtures/a.csv", "src/b.csv"]) == 1
    out = capsys.readouterr().out
    assert "src/b.csv" in out
    assert "tests/fixtures/a.csv" not in out
