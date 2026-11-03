"""Ingest: input bundle manifest, readers and structural validation, archive."""

from __future__ import annotations

from spot_report.ingest.archive import ArchiveError, archive_bundle
from spot_report.ingest.manifest import (
    Manifest,
    ManifestError,
    ResponseCounts,
    ResponseFormat,
    ResponsesRef,
    School,
    Survey,
    Wave,
    load_manifest,
    parse_manifest,
)
from spot_report.ingest.readers import (
    Dataset,
    ReadError,
    load_bundle,
    read_csv_responses,
    read_responses,
    read_xlsx_responses,
    unconverted_columns,
)
from spot_report.ingest.validate import (
    Finding,
    Rule,
    Severity,
    has_errors,
    validate,
    validate_bundle,
)

__all__ = [
    "ArchiveError",
    "Dataset",
    "Finding",
    "Manifest",
    "ManifestError",
    "ReadError",
    "ResponseCounts",
    "ResponseFormat",
    "ResponsesRef",
    "Rule",
    "School",
    "Severity",
    "Survey",
    "Wave",
    "archive_bundle",
    "has_errors",
    "load_bundle",
    "load_manifest",
    "parse_manifest",
    "read_csv_responses",
    "read_responses",
    "read_xlsx_responses",
    "unconverted_columns",
    "validate",
    "validate_bundle",
]
