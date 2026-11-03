"""Metrics: numbers only (architecture section 6). No formatting, no I/O."""

from __future__ import annotations

from spot_report.metrics.registry import (
    METRICS_VERSION,
    MetricDefinition,
    MetricRegistry,
    RegistryError,
)
from spot_report.metrics.types import (
    Distribution,
    Metric,
    MetricError,
    MetricFormatError,
    MetricIdError,
    MetricSet,
    Proportion,
    Summary,
    metric_from_dict,
    metric_from_json,
    validate_metric_id,
)

__all__ = [
    "METRICS_VERSION",
    "Distribution",
    "Metric",
    "MetricDefinition",
    "MetricError",
    "MetricFormatError",
    "MetricIdError",
    "MetricRegistry",
    "MetricSet",
    "Proportion",
    "RegistryError",
    "Summary",
    "metric_from_dict",
    "metric_from_json",
    "validate_metric_id",
]
