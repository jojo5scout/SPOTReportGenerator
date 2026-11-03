"""SQLite snapshot store: round trip, upsert, wave order, schema version."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

import pytest

from spot_report import __version__
from spot_report.features import compute_features
from spot_report.ingest import read_responses
from spot_report.metrics import (
    METRICS_VERSION,
    Distribution,
    MetricSet,
    PatternCounts,
    Proportion,
    Summary,
    compute_metrics,
)
from spot_report.questionnaire import load_spec
from spot_report.store import (
    SCHEMA_VERSION,
    Snapshot,
    SnapshotNotFoundError,
    SQLiteStore,
    StoreError,
    StoreVersionError,
    open_store,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_300.xlsx"
STAMP = datetime(2026, 6, 1, 8, 30, tzinfo=UTC)

#: One metric of every kind, with None fields and awkward floats.
ALL_KINDS = MetricSet(
    {
        "test.kinds.proportion": Proportion(3, 10, 1),
        "test.kinds.proportion_empty": Proportion(0, 0, 4),
        "test.kinds.summary": Summary(
            n=5,
            n_missing=2,
            mean=0.1 + 0.2,
            sd=1 / 3,
            median=1 / 3,
            q1=1e-9,
            q3=2.5,
            min=-0.0,
            max=123456789.123456789,
        ),
        "test.kinds.summary_empty": Summary(
            0, 3, None, None, None, None, None, None, None
        ),
        "test.kinds.summary_single": Summary(1, 0, 2.0, None, 2.0, 2.0, 2.0, 2.0, 2.0),
        "test.kinds.distribution": Distribution(("a", "b", "ä"), (4, 0, 2), 1),
        "test.kinds.patterns": PatternCounts(
            ("A", "B", "C"), ((), ("B",), ("A", "C")), (2, 1, 3), 1
        ),
        "test.kinds.patterns_empty": PatternCounts((), (), (), 2),
    }
)


def make_snapshot(**overrides: object) -> Snapshot:
    fields: dict[str, object] = {
        "school_id": "demo",
        "school_name": "Gymnasium Bäume",
        "wave_label": "2026",
        "fieldwork_start": date(2026, 4, 20),
        "fieldwork_end": date(2026, 5, 15),
        "limesurvey_id": 123456,
        "questionnaire_version": "2026.1",
        "program_version": "0.1.0",
        "metrics_version": 3,
        "quality_rules_version": "q1",
        "archive_path": "demo/2026/002",
        "metrics": ALL_KINDS,
    }
    fields.update(overrides)
    return Snapshot(**fields)  # type: ignore[arg-type]


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "store.sqlite"


@pytest.fixture
def store(store_path: Path) -> SQLiteStore:
    with open_store(store_path) as opened:
        yield opened


def count(path: Path, table: str, where: str = "1") -> int:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}"
        ).fetchone()
    connection.close()
    return row[0]


# --- round trip ---------------------------------------------------------------------


def test_round_trip_of_every_kind_and_field(store: SQLiteStore) -> None:
    snapshot = make_snapshot()
    store.save_snapshot(snapshot, created_at=STAMP)
    loaded = store.load_snapshot("demo", "2026")
    assert loaded == snapshot
    assert dict(loaded.metrics) == dict(ALL_KINDS)
    # Floats come back bit-identical, including the sign of zero.
    summary = loaded.metrics["test.kinds.summary"]
    assert isinstance(summary, Summary)
    assert summary.mean == 0.1 + 0.2
    assert str(summary.min) == "-0.0"


def test_round_trip_with_minimal_metadata_and_no_metrics(store: SQLiteStore) -> None:
    snapshot = make_snapshot(
        fieldwork_start=None,
        limesurvey_id=None,
        quality_rules_version=None,
        archive_path=None,
        metrics=MetricSet(),
    )
    store.save_snapshot(snapshot)
    assert store.load_snapshot("demo", "2026") == snapshot


def test_round_trip_survives_closing_and_reopening(store_path: Path) -> None:
    snapshot = make_snapshot()
    with open_store(store_path) as first:
        first.save_snapshot(snapshot)
    with open_store(store_path) as second:
        assert second.load_snapshot("demo", "2026") == snapshot


def test_round_trip_of_a_computed_fixture_snapshot(store: SQLiteStore) -> None:
    spec = load_spec("2026.1")
    responses = read_responses(FIXTURE, "xlsx", spec)
    metrics = compute_metrics(responses, compute_features(responses, spec), spec)
    assert len(metrics) > 50
    snapshot = make_snapshot(
        school_id="fixture",
        wave_label="fixture-2026",
        program_version=__version__,
        metrics_version=METRICS_VERSION,
        metrics=metrics,
    )
    store.save_snapshot(snapshot)
    loaded = store.load_snapshot("fixture", "fixture-2026")
    assert loaded == snapshot
    assert loaded.metrics.to_json() == metrics.to_json()


def test_created_at_is_bookkeeping_and_not_part_of_the_snapshot(
    store: SQLiteStore,
) -> None:
    snapshot = make_snapshot()
    store.save_snapshot(snapshot, created_at=STAMP)
    first = store.load_snapshot("demo", "2026")
    store.save_snapshot(snapshot, created_at=STAMP + timedelta(days=1))
    assert store.load_snapshot("demo", "2026") == first == snapshot
    assert not hasattr(first, "created_at")
    (info,) = store.list_waves("demo")
    assert info.created_at == STAMP + timedelta(days=1)


def test_created_at_defaults_to_now_in_utc(store: SQLiteStore) -> None:
    before = datetime.now(UTC)
    store.save_snapshot(make_snapshot())
    (info,) = store.list_waves("demo")
    assert before <= info.created_at <= datetime.now(UTC)
    assert info.created_at.utcoffset() == timedelta(0)


def test_created_at_keeps_its_offset(store: SQLiteStore) -> None:
    stamp = datetime(2026, 6, 1, 10, 30, tzinfo=timezone(timedelta(hours=2)))
    store.save_snapshot(make_snapshot(), created_at=stamp)
    (info,) = store.list_waves("demo")
    assert info.created_at == stamp


def test_naive_created_at_is_rejected(store: SQLiteStore) -> None:
    with pytest.raises(StoreError, match="timezone"):
        store.save_snapshot(make_snapshot(), created_at=datetime(2026, 6, 1))
    assert store.list_waves("demo") == ()


def test_load_of_missing_snapshot(store: SQLiteStore) -> None:
    store.save_snapshot(make_snapshot())
    with pytest.raises(SnapshotNotFoundError, match="other"):
        store.load_snapshot("demo", "other")
    with pytest.raises(SnapshotNotFoundError):
        store.load_snapshot("nobody", "2026")
    assert issubclass(SnapshotNotFoundError, LookupError)


# --- upsert -------------------------------------------------------------------------


def test_saving_the_same_wave_twice_keeps_one_snapshot(
    store: SQLiteStore, store_path: Path
) -> None:
    snapshot = make_snapshot()
    store.save_snapshot(snapshot)
    store.save_snapshot(snapshot)
    assert count(store_path, "school") == 1
    assert count(store_path, "wave") == 1
    assert count(store_path, "metric") == len(ALL_KINDS)
    assert len(store.list_waves("demo")) == 1
    assert store.load_snapshot("demo", "2026") == snapshot


def test_upsert_replaces_metadata_and_metrics_entirely(
    store: SQLiteStore, store_path: Path
) -> None:
    store.save_snapshot(make_snapshot(), created_at=STAMP)
    wave_id = _wave_id(store_path)
    replacement = make_snapshot(
        school_name="Gymnasium Renamed",
        fieldwork_start=None,
        fieldwork_end=date(2026, 5, 20),
        limesurvey_id=None,
        questionnaire_version="2026.2",
        program_version="0.2.0",
        metrics_version=4,
        quality_rules_version=None,
        archive_path="demo/2026/003",
        metrics=MetricSet(
            {
                "test.kinds.proportion": Proportion(9, 10, 0),  # changed
                "test.kinds.new": Proportion(1, 1, 0),  # added
            }
        ),
    )
    store.save_snapshot(replacement, created_at=STAMP + timedelta(days=2))
    assert store.load_snapshot("demo", "2026") == replacement
    # Ids absent from the new set are gone, the others are not duplicated.
    assert count(store_path, "metric") == 2
    assert count(store_path, "wave") == 1
    assert count(store_path, "school") == 1
    assert _wave_id(store_path) == wave_id
    (info,) = store.list_waves("demo")
    assert info.created_at == STAMP + timedelta(days=2)
    assert info.fieldwork_end == date(2026, 5, 20)


def test_upsert_leaves_other_waves_and_schools_alone(store: SQLiteStore) -> None:
    other_wave = make_snapshot(wave_label="2027", fieldwork_end=date(2027, 5, 1))
    other_school = make_snapshot(school_id="other", school_name="Other")
    store.save_snapshot(other_wave)
    store.save_snapshot(other_school)
    store.save_snapshot(make_snapshot())
    store.save_snapshot(make_snapshot(metrics=MetricSet()))
    assert store.load_snapshot("demo", "2027") == other_wave
    assert store.load_snapshot("other", "2026") == other_school
    assert dict(store.load_snapshot("demo", "2026").metrics) == {}


def test_school_name_is_updated_for_all_its_waves(store: SQLiteStore) -> None:
    store.save_snapshot(make_snapshot())
    store.save_snapshot(
        make_snapshot(
            wave_label="2027", fieldwork_end=date(2027, 5, 1), school_name="New Name"
        )
    )
    assert store.load_snapshot("demo", "2026").school_name == "New Name"
    assert store.load_snapshot("demo", "2027").school_name == "New Name"


def test_failed_replacement_leaves_the_old_snapshot_untouched(
    store: SQLiteStore, store_path: Path
) -> None:
    original = make_snapshot()
    store.save_snapshot(original)
    with sqlite3.connect(store_path) as raw:
        raw.execute(
            "CREATE TRIGGER boom BEFORE INSERT ON metric "
            "WHEN NEW.metric_id = 'test.boom.boom' "
            "BEGIN SELECT RAISE(ABORT, 'boom'); END"
        )
    raw.close()
    broken = make_snapshot(
        school_name="Changed",
        metrics=MetricSet(
            {"test.a.a": Proportion(1, 1, 0), "test.boom.boom": Proportion(1, 1, 0)}
        ),
    )
    with pytest.raises(StoreError):
        store.save_snapshot(broken)
    assert store.load_snapshot("demo", "2026") == original
    # The connection is usable afterwards.
    store.save_snapshot(make_snapshot(metrics=MetricSet()))


def _wave_id(path: Path) -> int:
    with sqlite3.connect(path) as raw:
        (wave_id,) = raw.execute("SELECT id FROM wave").fetchone()
    raw.close()
    return wave_id


def test_foreign_keys_are_enforced(store: SQLiteStore, store_path: Path) -> None:
    store.save_snapshot(make_snapshot())
    connection = store._connection  # the pragma is per connection
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO wave (school_id, label, fieldwork_end, "
            "questionnaire_version, program_version, metrics_version, created_at) "
            "VALUES ('nobody', 'x', '2026-01-01', 'v', 'p', 1, 't')"
        )
    # Deleting a wave removes its metrics.
    connection.execute("DELETE FROM wave")
    assert count(store_path, "metric") == 0


# --- wave order ---------------------------------------------------------------------


def test_waves_are_ordered_by_fieldwork_end_not_label_or_insertion(
    store: SQLiteStore,
) -> None:
    for label, end in [
        ("b-late", date(2028, 5, 1)),
        ("z-early", date(2026, 5, 1)),
        ("a-middle", date(2027, 5, 1)),
    ]:
        store.save_snapshot(make_snapshot(wave_label=label, fieldwork_end=end))
    waves = store.list_waves("demo")
    assert [wave.label for wave in waves] == ["z-early", "a-middle", "b-late"]
    assert [wave.fieldwork_end for wave in waves] == [
        date(2026, 5, 1),
        date(2027, 5, 1),
        date(2028, 5, 1),
    ]


def test_replacing_a_wave_with_a_new_end_date_moves_it(store: SQLiteStore) -> None:
    store.save_snapshot(make_snapshot(wave_label="a", fieldwork_end=date(2026, 5, 1)))
    store.save_snapshot(make_snapshot(wave_label="b", fieldwork_end=date(2027, 5, 1)))
    store.save_snapshot(make_snapshot(wave_label="a", fieldwork_end=date(2028, 5, 1)))
    assert [wave.label for wave in store.list_waves("demo")] == ["b", "a"]


def test_equal_fieldwork_end_is_ordered_by_label(store: SQLiteStore) -> None:
    end = date(2026, 5, 15)
    for label in ("2026b", "2026a", "2026c"):
        store.save_snapshot(make_snapshot(wave_label=label, fieldwork_end=end))
    assert [wave.label for wave in store.list_waves("demo")] == [
        "2026a",
        "2026b",
        "2026c",
    ]


def test_list_waves_is_per_school_and_empty_for_unknown(store: SQLiteStore) -> None:
    store.save_snapshot(make_snapshot())
    store.save_snapshot(make_snapshot(school_id="other", wave_label="9"))
    assert [wave.label for wave in store.list_waves("demo")] == ["2026"]
    assert [wave.label for wave in store.list_waves("other")] == ["9"]
    assert store.list_waves("nobody") == ()


def test_wave_info_carries_the_header(store: SQLiteStore) -> None:
    store.save_snapshot(make_snapshot(), created_at=STAMP)
    store.save_snapshot(
        make_snapshot(
            wave_label="2027",
            fieldwork_end=date(2027, 5, 1),
            fieldwork_start=None,
            archive_path=None,
        )
    )
    first, second = store.list_waves("demo")
    assert first.label == "2026"
    assert first.fieldwork_start == date(2026, 4, 20)
    assert first.questionnaire_version == "2026.1"
    assert first.metrics_version == 3
    assert first.archive_path == "demo/2026/002"
    assert first.created_at == STAMP
    assert second.fieldwork_start is None
    assert second.archive_path is None


# --- schema and version -------------------------------------------------------------


def test_schema_sql_is_package_data() -> None:
    schema = resources.files("spot_report.store").joinpath("schema.sql")
    assert schema.is_file()
    text = schema.read_text(encoding="utf-8")
    for table in ("schema_version", "school", "wave", "metric"):
        assert f"CREATE TABLE {table}" in text


def test_new_store_records_the_schema_version(
    store: SQLiteStore, store_path: Path
) -> None:
    with sqlite3.connect(store_path) as raw:
        rows = raw.execute("SELECT id, version FROM schema_version").fetchall()
    raw.close()
    assert rows == [(1, SCHEMA_VERSION)]


def test_open_store_creates_the_file_but_not_the_directory(tmp_path: Path) -> None:
    with open_store(tmp_path / "new.sqlite"):
        pass
    assert (tmp_path / "new.sqlite").is_file()
    with pytest.raises(StoreError, match="Cannot open"):
        open_store(tmp_path / "missing-dir" / "store.sqlite")


def test_open_without_create_does_not_create_a_file(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite"
    with pytest.raises(StoreError, match="does not exist"):
        open_store(path, create=False)
    assert not path.exists()


def test_open_without_create_accepts_an_existing_store(store_path: Path) -> None:
    with open_store(store_path) as first:
        first.save_snapshot(make_snapshot())
    with open_store(store_path, create=False) as second:
        assert second.load_snapshot("demo", "2026") == make_snapshot()


def test_open_without_create_rejects_an_empty_database_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()
    with pytest.raises(StoreError, match="not a snapshot store"):
        open_store(path, create=False)


def test_newer_schema_version_is_refused(store_path: Path) -> None:
    open_store(store_path).close()
    with sqlite3.connect(store_path) as raw:
        raw.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))
    raw.close()
    with pytest.raises(StoreVersionError, match="newer"):
        open_store(store_path)
    with pytest.raises(StoreVersionError):
        open_store(store_path, create=False)


@pytest.mark.parametrize("version", [0, "x"])
def test_other_schema_versions_are_refused(store_path: Path, version: object) -> None:
    open_store(store_path).close()
    with sqlite3.connect(store_path) as raw:
        raw.execute("UPDATE schema_version SET version = ?", (version,))
    raw.close()
    with pytest.raises(StoreVersionError, match="unsupported"):
        open_store(store_path)


def test_missing_version_row_is_refused(store_path: Path) -> None:
    open_store(store_path).close()
    with sqlite3.connect(store_path) as raw:
        raw.execute("DELETE FROM schema_version")
    raw.close()
    with pytest.raises(StoreVersionError):
        open_store(store_path)


def test_foreign_database_is_not_touched(tmp_path: Path) -> None:
    path = tmp_path / "other.sqlite"
    with sqlite3.connect(path) as raw:
        raw.execute("CREATE TABLE something (x)")
    raw.close()
    with pytest.raises(StoreError, match="not a snapshot store"):
        open_store(path)
    assert count(path, "sqlite_master", "name = 'schema_version'") == 0


def test_file_that_is_not_a_database(tmp_path: Path) -> None:
    path = tmp_path / "text.sqlite"
    path.write_text("this is not a database " * 20)
    with pytest.raises(StoreError):
        open_store(path)


# --- unreadable rows ----------------------------------------------------------------


def test_unreadable_payload_raises_store_error(
    store: SQLiteStore, store_path: Path
) -> None:
    store.save_snapshot(make_snapshot())
    with sqlite3.connect(store_path) as raw:
        raw.execute(
            'UPDATE metric SET payload = \'{"kind": "nope"}\' '
            "WHERE metric_id = 'test.kinds.proportion'"
        )
    raw.close()
    with pytest.raises(StoreError, match="unreadable"):
        store.load_snapshot("demo", "2026")


def test_kind_column_must_match_the_payload(
    store: SQLiteStore, store_path: Path
) -> None:
    store.save_snapshot(make_snapshot())
    with sqlite3.connect(store_path) as raw:
        raw.execute("UPDATE metric SET kind = 'summary'")
    raw.close()
    with pytest.raises(StoreError):
        store.load_snapshot("demo", "2026")


def test_kind_column_holds_the_metric_kind(
    store: SQLiteStore, store_path: Path
) -> None:
    store.save_snapshot(make_snapshot())
    with sqlite3.connect(store_path) as raw:
        kinds = dict(raw.execute("SELECT metric_id, kind FROM metric"))
    raw.close()
    assert kinds["test.kinds.proportion"] == "proportion"
    assert kinds["test.kinds.summary"] == "summary"
    assert kinds["test.kinds.distribution"] == "distribution"
    assert kinds["test.kinds.patterns"] == "pattern_counts"
