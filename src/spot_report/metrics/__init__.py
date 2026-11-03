"""Metrics: numbers only (architecture section 6). No formatting, no I/O."""

from __future__ import annotations

from spot_report.metrics.compute import compute_metrics
from spot_report.metrics.domains import default_registry
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
    PatternCounts,
    Proportion,
    Summary,
    metric_from_dict,
    metric_from_json,
    top_patterns,
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
    "PatternCounts",
    "Proportion",
    "RegistryError",
    "Summary",
    "compute_metrics",
    "default_registry",
    "metric_from_dict",
    "metric_from_json",
    "top_patterns",
    "validate_metric_id",
]
