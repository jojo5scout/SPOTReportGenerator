"""Snapshot store: metric sets and wave metadata in SQLite (architecture section 6)."""

from __future__ import annotations

from spot_report.store.snapshot import Snapshot, SnapshotError
from spot_report.store.sqlite_store import (
    SCHEMA_VERSION,
    SnapshotNotFoundError,
    SQLiteStore,
    StoreError,
    StoreVersionError,
    WaveInfo,
    open_store,
)

__all__ = [
    "SCHEMA_VERSION",
    "SQLiteStore",
    "Snapshot",
    "SnapshotError",
    "SnapshotNotFoundError",
    "StoreError",
    "StoreVersionError",
    "WaveInfo",
    "open_store",
]
