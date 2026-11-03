"""The snapshot: a metric set plus the metadata of the wave it was computed for.

Architecture section 6.3. A snapshot holds the full, unsuppressed metrics; privacy
rules are applied at presentation (section 9). ``created_at`` of the store is
bookkeeping of the store and not part of the snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from spot_report.metrics.types import MetricSet

__all__ = ["Snapshot", "SnapshotError"]


class SnapshotError(ValueError):
    """Snapshot metadata violates the contract."""


@dataclass(frozen=True)
class Snapshot:
    """Metrics of one school and wave, with the provenance needed to recompute them.

    ``school_id`` and ``wave_label`` identify the snapshot in the store;
    ``fieldwork_end`` orders the waves of a school (section 7). ``archive_path`` is
    the archived bundle the metrics were computed from (section 3, "Archive"),
    relative to the archive root; the store keeps the text as given.
    """

    school_id: str
    school_name: str
    wave_label: str
    fieldwork_end: date
    questionnaire_version: str
    program_version: str
    metrics_version: int
    metrics: MetricSet
    fieldwork_start: date | None = None
    limesurvey_id: int | None = None
    quality_rules_version: str | None = None
    archive_path: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "school_id",
            "school_name",
            "wave_label",
            "questionnaire_version",
            "program_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SnapshotError(f"{name} must be a non-empty string")
        for name in ("quality_rules_version", "archive_path"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise SnapshotError(f"{name} must be a string or None")
        if not _is_date(self.fieldwork_end):
            raise SnapshotError("fieldwork_end must be a date")
        if self.fieldwork_start is not None:
            if not _is_date(self.fieldwork_start):
                raise SnapshotError("fieldwork_start must be a date or None")
            if self.fieldwork_start > self.fieldwork_end:
                raise SnapshotError("fieldwork_start is after fieldwork_end")
        if not _is_int(self.metrics_version):
            raise SnapshotError("metrics_version must be an integer")
        if self.limesurvey_id is not None and not _is_int(self.limesurvey_id):
            raise SnapshotError("limesurvey_id must be an integer or None")
        if not isinstance(self.metrics, MetricSet):
            raise SnapshotError("metrics must be a MetricSet")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_date(value: object) -> bool:
    # datetime is a date subclass but would not survive the ISO date column.
    return type(value) is date
