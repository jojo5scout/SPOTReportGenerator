from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from spot_report import __version__
from spot_report.cli import main
from tests.conftest import BundleWriter, manifest_dict


def test_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: spot-report" in capsys.readouterr().out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_arguments_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: spot-report" in capsys.readouterr().out


# --- validate ------------------------------------------------------------------------


def test_help_lists_validate(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "validate" in capsys.readouterr().out


def test_validate_clean_fixture(
    raw_fixture: pd.DataFrame,
    write_bundle: BundleWriter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", str(write_bundle(raw_fixture))]) == 0
    assert capsys.readouterr().out.strip() == "No findings"


def test_validate_fixture_with_empty_cells_exits_zero(
    raw_fixture: pd.DataFrame,
    write_bundle: BundleWriter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_fixture["FEHLTAGQ1"] = ""
    raw_fixture.loc[::5, "PHQ9[PHQQ3]"] = ""
    assert main(["validate", str(write_bundle(raw_fixture))]) == 0
    assert capsys.readouterr().out.strip() == "No findings"


def test_validate_injected_errors_exit_three_and_print_no_values(
    raw_fixture: pd.DataFrame,
    write_bundle: BundleWriter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_fixture.loc[0:2, "PHQ9[PHQQ1]"] = "4711"
    raw_fixture.loc[5:6, "DQSEX"] = "ZZ99"
    raw_fixture.loc[10, "GAD7[GADQ3]"] = "3.5x"
    raw_fixture.loc[3:6, "DIAGQ1[DEPR]"] = "Q9Q"
    raw_fixture = raw_fixture.drop(columns=["FEHLTAGQ0"])

    assert main(["validate", str(write_bundle(raw_fixture))]) == 3

    out = capsys.readouterr().out.splitlines()
    assert out == [
        "error  invalid_code  column=DQSEX  count=2",
        "error  invalid_marker  column=DIAGQ1[DEPR]  count=4",
        "error  missing_column  column=FEHLTAGQ0  count=1",
        "error  not_an_integer  column=GAD7[GADQ3]  count=1",
        "error  out_of_range  column=PHQ9[PHQQ1]  count=3",
        "5 error(s), 0 warning(s) in 5 finding(s)",
    ]
    text = "\n".join(out)
    for value in ("4711", "ZZ99", "3.5x", "Q9Q"):
        assert value not in text


def test_validate_invalid_manifest_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "manifest.json").write_text("{broken")
    assert main(["validate", str(tmp_path)]) == 3
    out = capsys.readouterr().out
    assert "error  invalid_manifest  count=1" in out
    assert "1 error(s)" in out


def test_validate_missing_bundle_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", str(tmp_path / "missing")]) == 3
    assert "invalid_manifest" in capsys.readouterr().out


def test_validate_unreadable_file_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps(manifest_dict()))
    (tmp_path / "responses.csv").write_bytes(b"\xff\xfe\x00not utf-8")
    assert main(["validate", str(tmp_path)]) == 3
    assert "unreadable_file" in capsys.readouterr().out


def test_validate_unknown_questionnaire_version_exits_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = manifest_dict(survey={"questionnaire_version": "1999.9"})
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert main(["validate", str(tmp_path)]) == 3
    assert "unknown_version" in capsys.readouterr().out


def test_validate_needs_a_bundle_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["validate"])
    assert exc.value.code == 2
    capsys.readouterr()
