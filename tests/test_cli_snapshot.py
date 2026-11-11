"""``spot-report snapshot list`` and ``snapshot export``."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from spot_report import __version__
from spot_report.cli import EXIT_INVALID_INPUT, main
from spot_report.config import store_path as configured_store
from spot_report.features import compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    METRICS_VERSION,
    MetricSet,
    Proportion,
    compute_metrics,
)
from spot_report.questionnaire import load_spec
from spot_report.store import SCHEMA_VERSION, Snapshot, open_store

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_300.xlsx"


def snapshot(**overrides: object) -> Snapshot:
    fields: dict[str, object] = {
        "school_id": "demo",
        "school_name": "Gymnasium Bäume",
        "wave_label": "2026",
        "fieldwork_start": date(2026, 4, 20),
        "fieldwork_end": date(2026, 5, 15),
        "questionnaire_version": "2026.1",
        "program_version": __version__,
        "metrics_version": METRICS_VERSION,
        "metrics": MetricSet({"test.a.b": Proportion(1, 2, 0)}),
    }
    fields.update(overrides)
    return Snapshot(**fields)  # type: ignore[arg-type]


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "store.sqlite"


@pytest.fixture
def fixture_snapshot() -> Snapshot:
    spec = load_spec("2026.1")
    responses = read_responses(FIXTURE, "xlsx", spec)
    metrics = compute_metrics(responses, compute_features(responses, spec), spec)
    return snapshot(
        archive_path="demo/2026/001",
        limesurvey_id=4711,
        quality_rules_version="q1",
        metrics=metrics,
    )


def save(path: Path, *snapshots: Snapshot) -> None:
    with open_store(path) as store:
        for index, item in enumerate(snapshots):
            stamp = datetime(2026, 6, 1, 8, index, tzinfo=UTC)
            store.save_snapshot(item, created_at=stamp)


@pytest.fixture
def two_schools(store_path: Path) -> Path:
    # Inserted out of order on purpose; waves are listed by fieldwork_end.
    save(
        store_path,
        snapshot(wave_label="a-late", fieldwork_end=date(2027, 5, 1)),
        snapshot(wave_label="z-early", fieldwork_end=date(2026, 5, 1)),
        snapshot(school_id="beta", school_name="Beta", wave_label="w1"),
        snapshot(school_id="alpha", school_name="Alpha", wave_label="w1"),
    )
    return store_path


# --- export -------------------------------------------------------------------------


def test_export_is_readable_json_with_metadata_and_metrics(
    store_path: Path,
    fixture_snapshot: Snapshot,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save(store_path, fixture_snapshot)
    args = ["snapshot", "export", "--store", str(store_path)]
    assert main([*args, "--school", "demo", "--wave", "2026"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["school_id"] == "demo"
    assert data["school_name"] == "Gymnasium Bäume"  # not escaped
    assert data["wave_label"] == "2026"
    assert data["fieldwork_start"] == "2026-04-20"
    assert data["fieldwork_end"] == "2026-05-15"
    assert data["limesurvey_id"] == 4711
    assert data["questionnaire_version"] == "2026.1"
    assert data["program_version"] == __version__
    assert data["metrics_version"] == METRICS_VERSION
    assert data["quality_rules_version"] == "q1"
    assert data["archive_path"] == "demo/2026/001"
    assert MetricSet.from_dict(data["metrics"]) == fixture_snapshot.metrics
    assert len(data["metrics"]) > 50


def test_export_text_is_indented_utf8_and_deterministic(
    store_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save(store_path, snapshot())
    args = ["snapshot", "export", "--store", str(store_path)]
    args += ["--school", "demo", "--wave", "2026"]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    assert capsys.readouterr().out == first
    assert first.startswith('{\n  "school_id": "demo",\n')
    assert "Gymnasium Bäume" in first
    assert first.endswith("}\n")


def test_export_of_minimal_snapshot_has_null_optional_fields(
    store_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    save(store_path, snapshot(fieldwork_start=None, metrics=MetricSet()))
    args = ["snapshot", "export", "--store", str(store_path)]
    assert main([*args, "--school", "demo", "--wave", "2026"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["fieldwork_start"] is None
    assert data["archive_path"] is None
    assert data["metrics"] == {}


def test_export_unknown_wave_exits_3(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["snapshot", "export", "--store", str(two_schools)]
    assert main([*args, "--school", "alpha", "--wave", "nope"]) == EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert "alpha" in captured.err
    assert "nope" in captured.err
    assert "Traceback" not in captured.err


def test_export_unknown_school_exits_3(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["snapshot", "export", "--store", str(two_schools)]
    assert main([*args, "--school", "nobody", "--wave", "w1"]) == EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nobody" in captured.err


def test_export_requires_school_and_wave(
    store_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for args in (
        ["--store", str(store_path), "--school", "demo"],
        ["--store", str(store_path), "--wave", "2026"],
    ):
        with pytest.raises(SystemExit) as exc:
            main(["snapshot", "export", *args])
        assert exc.value.code == 2
    capsys.readouterr()


# --- list ---------------------------------------------------------------------------


def wave_lines(out: str) -> list[str]:
    return out.strip().splitlines()


def test_list_orders_schools_by_id_and_waves_by_fieldwork_end(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["snapshot", "list", "--store", str(two_schools)]) == 0
    lines = wave_lines(capsys.readouterr().out)
    assert [(" ".join(line.split("  ")[:2])) for line in lines] == [
        "school=alpha wave=w1",
        "school=beta wave=w1",
        "school=demo wave=z-early",
        "school=demo wave=a-late",
    ]


def test_list_line_shows_the_wave_header(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["snapshot", "list", "--store", str(two_schools)]) == 0
    line = wave_lines(capsys.readouterr().out)[2]
    assert line == (
        "school=demo  wave=z-early  fieldwork=2026-04-20..2026-05-01  "
        f"questionnaire=2026.1  metrics_version={METRICS_VERSION}  "
        "saved=2026-06-01T08:01:00+00:00  name=Gymnasium Bäume"
    )


def test_list_shows_unknown_start_as_question_mark(
    store_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    save(store_path, snapshot(fieldwork_start=None))
    assert main(["snapshot", "list", "--store", str(store_path)]) == 0
    assert "fieldwork=?..2026-05-15" in capsys.readouterr().out


def test_list_filters_by_school(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["snapshot", "list", "--store", str(two_schools), "--school", "demo"]
    assert main(args) == 0
    lines = wave_lines(capsys.readouterr().out)
    assert len(lines) == 2
    assert all(line.startswith("school=demo  ") for line in lines)


def test_list_of_unknown_school_exits_3(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["snapshot", "list", "--store", str(two_schools), "--school", "nobody"]
    assert main(args) == EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nobody" in captured.err
    assert captured.err.count("\n") == 1


def test_list_of_empty_store_says_so_and_exits_0(
    store_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with open_store(store_path):
        pass
    assert main(["snapshot", "list", "--store", str(store_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "No snapshots\n"
    assert captured.err == ""


# --- store problems and read-only behaviour ---------------------------------------


@pytest.fixture(params=["list", "export"])
def command(request: pytest.FixtureRequest) -> list[str]:
    if request.param == "list":
        return ["snapshot", "list"]
    return ["snapshot", "export", "--school", "demo", "--wave", "2026"]


def test_missing_store_exits_3_and_is_not_created(
    tmp_path: Path, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.sqlite"
    assert main([*command, "--store", str(missing)]) == EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "missing.sqlite" in captured.err
    assert captured.err.count("\n") == 1
    assert list(tmp_path.iterdir()) == []


def test_directory_as_store_exits_3(
    tmp_path: Path, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*command, "--store", str(tmp_path)]) == EXIT_INVALID_INPUT
    assert capsys.readouterr().err.startswith("error: ")


def test_file_that_is_not_a_store_exits_3_and_is_untouched(
    tmp_path: Path, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "other.sqlite"
    other.write_bytes(b"this is not a database, just some bytes" * 10)
    before = other.read_bytes()
    assert main([*command, "--store", str(other)]) == EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err
    assert other.read_bytes() == before


def test_foreign_sqlite_database_exits_3_and_is_not_changed(
    tmp_path: Path, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "foreign.sqlite"
    with sqlite3.connect(other) as connection:
        connection.execute("CREATE TABLE notes (text TEXT)")
    connection.close()
    assert main([*command, "--store", str(other)]) == EXIT_INVALID_INPUT
    assert "not a snapshot store" in capsys.readouterr().err
    with sqlite3.connect(other) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master").fetchall()
    connection.close()
    assert tables == [("notes",)]


def test_newer_schema_version_exits_3(
    store_path: Path, command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    save(store_path, snapshot())
    with sqlite3.connect(store_path) as connection:
        connection.execute(
            "UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,)
        )
    connection.close()
    assert main([*command, "--store", str(store_path)]) == EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "update the program" in captured.err


def test_read_commands_leave_the_store_file_unchanged(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = two_schools.read_bytes()
    assert main(["snapshot", "list", "--store", str(two_schools)]) == 0
    export = ["snapshot", "export", "--store", str(two_schools)]
    assert main([*export, "--school", "alpha", "--wave", "w1"]) == 0
    capsys.readouterr()
    assert two_schools.read_bytes() == before
    assert sorted(path.name for path in two_schools.parent.iterdir()) == [
        "store.sqlite"
    ]


# --- usage ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", [{}, {"SPOT_STORE": "  "}])
def test_without_store_option_or_variable_exits_3(
    command: list[str], env: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """No silent default location (ADR 0004)."""
    assert main(command, env=env) == EXIT_INVALID_INPUT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--store" in captured.err
    assert "SPOT_STORE" in captured.err


def test_store_setting_reads_the_variable() -> None:
    assert configured_store({"SPOT_STORE": "/some/store.sqlite"}) == Path(
        "/some/store.sqlite"
    )
    assert configured_store({}) is None
    assert configured_store({"SPOT_STORE": "  "}) is None


def test_store_comes_from_the_environment(
    two_schools: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {"SPOT_STORE": str(two_schools)}
    assert main(["snapshot", "list"], env=env) == 0
    assert len(wave_lines(capsys.readouterr().out)) == 4


def test_store_option_overrides_the_environment(
    two_schools: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {"SPOT_STORE": str(tmp_path / "elsewhere.sqlite")}
    args = ["snapshot", "list", "--store", str(two_schools)]
    assert main(args, env=env) == 0
    assert len(wave_lines(capsys.readouterr().out)) == 4
    assert not (tmp_path / "elsewhere.sqlite").exists()


def test_snapshot_without_action_prints_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["snapshot"]) == 0
    out = capsys.readouterr().out
    assert "list" in out
    assert "export" in out


def test_help_lists_snapshot(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "snapshot" in capsys.readouterr().out
