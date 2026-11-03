"""Compute the metrics of all domains for one wave."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spot_report.metrics.domains import DOMAINS, default_registry
from spot_report.metrics.types import Metric, MetricError, MetricSet

if TYPE_CHECKING:
    import pandas as pd

    from spot_report.questionnaire import QuestionnaireSpec

__all__ = ["compute_metrics"]


def compute_metrics(
    responses: pd.DataFrame, features: pd.DataFrame, spec: QuestionnaireSpec
) -> MetricSet:
    """Run every domain's ``compute`` and merge the results into one metric set.

    A metric id produced by two domains raises :class:`MetricError`; the merged set is
    checked against the default registry of ``spec`` (every id registered, with its
    kind).
    """
    merged: dict[str, Metric] = {}
    for module in DOMAINS:
        for metric_id, metric in module.compute(responses, features, spec).items():
            if metric_id in merged:
                raise MetricError(f"Metric id {metric_id!r} is computed twice")
            merged[metric_id] = metric
    result = MetricSet(merged)
    default_registry(spec).check(result)
    return result
