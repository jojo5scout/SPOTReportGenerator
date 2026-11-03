"""SQLite snapshot store (architecture sections 6.3 and 6.4).

One database file holds the snapshots of all schools and waves. Standard library
``sqlite3`` only. The store keeps full, unsuppressed metrics; privacy is applied at
presentation (section 9). It never logs and its error messages contain ids, versions
and counts, never metric values.

Writes are one transaction per snapshot: saving the same (school id, wave label)
again replaces the wave's metadata and metric rows entirely (the wave row and its
``id`` stay).
``created_at`` is store bookkeeping: it is set by :meth:`SQLiteStore.save_snapshot`,
reported by :meth:`SQLiteStore.list_waves` and is not part of the :class:`Snapshot`.

The database records its schema version in the ``schema_version`` table. A database
written by a newer program is refused; there is no migration framework yet.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import resources
from pathlib import Path
from types import TracebackType
from typing import Self

from spot_report.metrics.types import MetricError, MetricSet, metric_from_json
from spot_report.store.snapshot import Snapshot

__all__ = [
    "SCHEMA_VERSION",
    "SQLiteStore",
    "SchoolInfo",
    "SnapshotNotFoundError",
    "StoreError",
    "StoreVersionError",
    "WaveInfo",
    "open_store",
]

#: Schema version this code reads and writes; must match ``schema.sql``.
SCHEMA_VERSION = 1


class StoreError(Exception):
    """The store cannot be opened, read or written."""


class StoreVersionError(StoreError):
    """The database has a schema version this program does not support."""


class SnapshotNotFoundError(StoreError, LookupError):
    """No snapshot is stored for the requested school and wave."""


@dataclass(frozen=True)
class SchoolInfo:
    """A school with at least one stored snapshot, as listed by ``list_schools``."""

    id: str
    name: str


@dataclass(frozen=True)
class WaveInfo:
    """Header of a stored wave, as listed by :meth:`SQLiteStore.list_waves`."""

    label: str
    fieldwork_end: date
    questionnaire_version: str
    metrics_version: int
    created_at: datetime
    fieldwork_start: date | None = None
    archive_path: str | None = None


def open_store(path: str | Path, *, create: bool = True) -> SQLiteStore:
    """Open the store at ``path``; with ``create`` a missing file is initialised.

    The directory of ``path`` must exist. Without ``create`` a missing file raises
    :class:`StoreError` instead of creating an empty database.
    """
    path = Path(path)
    if not create and not path.is_file():
        raise StoreError(f"Store {path.name} does not exist")
    try:
        connection = sqlite3.connect(path, isolation_level=None)
    except sqlite3.Error as exc:
        raise StoreError(f"Cannot open store {path.name}") from exc
    try:
        _prepare(connection, path.name, create=create)
    except BaseException:
        connection.close()
        raise
    return SQLiteStore(connection)


class SQLiteStore:
    """An open snapshot store. Use :func:`open_store`; supports ``with``."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def save_snapshot(
        self, snapshot: Snapshot, *, created_at: datetime | None = None
    ) -> None:
        """Insert the snapshot, or replace the stored one of the same wave.

        Replacing is atomic: the school name is updated, the wave metadata is
        overwritten and all metric rows of the wave are replaced, so metric ids
        absent from the new snapshot disappear. ``created_at`` (timezone-aware;
        default: now, UTC) is the time of this save.
        """
        stamp = created_at if created_at is not None else datetime.now(UTC)
        if stamp.tzinfo is None:
            raise StoreError("created_at must be timezone-aware")
        stored_at = stamp.isoformat()
        rows = [
            (metric_id, metric.kind, metric.to_json())
            for metric_id, metric in snapshot.metrics.items()
        ]
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO school (id, name) VALUES (?, ?) "
                    "ON CONFLICT (id) DO UPDATE SET name = excluded.name",
                    (snapshot.school_id, snapshot.school_name),
                )
                connection.execute(_UPSERT_WAVE, _wave_values(snapshot, stored_at))
                (wave_id,) = connection.execute(
                    "SELECT id FROM wave WHERE school_id = ? AND label = ?",
                    (snapshot.school_id, snapshot.wave_label),
                ).fetchone()
                connection.execute("DELETE FROM metric WHERE wave_id = ?", (wave_id,))
                connection.executemany(
                    "INSERT INTO metric (wave_id, metric_id, kind, payload) "
                    "VALUES (?, ?, ?, ?)",
                    [(wave_id, *row) for row in rows],
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        except sqlite3.Error as exc:
            raise StoreError("Cannot write snapshot") from exc

    def load_snapshot(self, school_id: str, wave_label: str) -> Snapshot:
        """The stored snapshot of a school and wave.

        Raises :class:`SnapshotNotFoundError` if there is none and
        :class:`StoreError` if stored rows are unreadable.
        """
        try:
            row = self._connection.execute(_SELECT_SNAPSHOT, (school_id, wave_label))
            header = row.fetchone()
            if header is None:
                raise SnapshotNotFoundError(
                    f"No snapshot for school {school_id!r}, wave {wave_label!r}"
                )
            wave_id = header[0]
            metric_rows = self._connection.execute(
                "SELECT metric_id, kind, payload FROM metric WHERE wave_id = ?",
                (wave_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("Cannot read snapshot") from exc
        try:
            metrics = {}
            for metric_id, kind, payload in metric_rows:
                metric = metric_from_json(payload)
                if metric.kind != kind:
                    raise StoreError(f"Stored kind of metric {metric_id!r} differs")
                metrics[metric_id] = metric
            return Snapshot(
                school_id=school_id,
                school_name=header[1],
                wave_label=wave_label,
                fieldwork_start=_optional_date(header[2]),
                fieldwork_end=date.fromisoformat(header[3]),
                limesurvey_id=header[4],
                questionnaire_version=header[5],
                program_version=header[6],
                metrics_version=header[7],
                quality_rules_version=header[8],
                archive_path=header[9],
                metrics=MetricSet(metrics),
            )
        except (MetricError, ValueError) as exc:
            raise StoreError(
                f"Stored snapshot of school {school_id!r}, wave {wave_label!r} "
                "is unreadable"
            ) from exc

    def list_schools(self) -> tuple[SchoolInfo, ...]:
        """All schools in the store, ordered by id (plain text order)."""
        try:
            rows = self._connection.execute(
                "SELECT id, name FROM school ORDER BY id"
            ).fetchall()
        except sqlite3.Error as exc:
            raise StoreError("Cannot read schools") from exc
        return tuple(SchoolInfo(id=school_id, name=name) for school_id, name in rows)

    def list_waves(self, school_id: str) -> tuple[WaveInfo, ...]:
        """Waves of a school ordered by ``fieldwork_end`` (earliest first).

        Waves with the same ``fieldwork_end`` are ordered by label (plain text
        order). An unknown school has no waves.
        """
        try:
            rows = self._connection.execute(
                "SELECT label, fieldwork_start, fieldwork_end, questionnaire_version, "
                "metrics_version, archive_path, created_at FROM wave "
                "WHERE school_id = ? ORDER BY fieldwork_end, label",
                (school_id,),
            ).fetchall()
            return tuple(
                WaveInfo(
                    label=label,
                    fieldwork_start=_optional_date(start),
                    fieldwork_end=date.fromisoformat(end),
                    questionnaire_version=questionnaire_version,
                    metrics_version=metrics_version,
                    archive_path=archive_path,
                    created_at=datetime.fromisoformat(created_at),
                )
                for (
                    label,
                    start,
                    end,
                    questionnaire_version,
                    metrics_version,
                    archive_path,
                    created_at,
                ) in rows
            )
        except sqlite3.Error as exc:
            raise StoreError("Cannot read waves") from exc
        except ValueError as exc:
            raise StoreError(
                f"Stored waves of school {school_id!r} are invalid"
            ) from exc


_UPSERT_WAVE = """
INSERT INTO wave (
    school_id, label, fieldwork_start, fieldwork_end, limesurvey_id,
    questionnaire_version, program_version, metrics_version,
    quality_rules_version, archive_path, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (school_id, label) DO UPDATE SET
    fieldwork_start = excluded.fieldwork_start,
    fieldwork_end = excluded.fieldwork_end,
    limesurvey_id = excluded.limesurvey_id,
    questionnaire_version = excluded.questionnaire_version,
    program_version = excluded.program_version,
    metrics_version = excluded.metrics_version,
    quality_rules_version = excluded.quality_rules_version,
    archive_path = excluded.archive_path,
    created_at = excluded.created_at
"""

_SELECT_SNAPSHOT = """
SELECT wave.id, school.name, wave.fieldwork_start, wave.fieldwork_end,
       wave.limesurvey_id, wave.questionnaire_version, wave.program_version,
       wave.metrics_version, wave.quality_rules_version, wave.archive_path
FROM wave JOIN school ON school.id = wave.school_id
WHERE wave.school_id = ? AND wave.label = ?
"""


def _wave_values(snapshot: Snapshot, created_at: str) -> tuple[object, ...]:
    start = snapshot.fieldwork_start
    return (
        snapshot.school_id,
        snapshot.wave_label,
        start.isoformat() if start is not None else None,
        snapshot.fieldwork_end.isoformat(),
        snapshot.limesurvey_id,
        snapshot.questionnaire_version,
        snapshot.program_version,
        snapshot.metrics_version,
        snapshot.quality_rules_version,
        snapshot.archive_path,
        created_at,
    )


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value is not None else None


def _prepare(connection: sqlite3.Connection, name: str, *, create: bool) -> None:
    """Enable foreign keys, create the schema in an empty database, check version."""
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        tables = {
            table
            for (table,) in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not tables:
            if not create:
                raise StoreError(f"{name} is not a snapshot store")
            _create_schema(connection)
        elif "schema_version" not in tables:
            raise StoreError(f"{name} is not a snapshot store")
        row = connection.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()
    except sqlite3.Error as exc:
        raise StoreError(f"Cannot open store {name}") from exc
    version = row[0] if row is not None else None
    if version != SCHEMA_VERSION:
        if isinstance(version, int) and version > SCHEMA_VERSION:
            raise StoreVersionError(
                f"Store {name} has schema version {version}, newer than the "
                f"supported version {SCHEMA_VERSION}; update the program"
            )
        raise StoreVersionError(
            f"Store {name} has an unsupported schema version "
            f"(supported: {SCHEMA_VERSION})"
        )


def _create_schema(connection: sqlite3.Connection) -> None:
    script = resources.files("spot_report.store").joinpath("schema.sql")
    sql = script.read_text(encoding="utf-8")
    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{sql}\nCOMMIT;")
    except sqlite3.Error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
