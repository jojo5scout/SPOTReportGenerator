"""The metric domains and the registry assembled from them.

Each domain is a module ``metrics/<domain>.py`` with a pure function
``definitions(spec) -> tuple[MetricDefinition, ...]`` (the
:class:`~spot_report.metrics.registry.MetricDefinition` of its ids for a questionnaire
spec; no file access) and a pure function
``compute(responses, features, spec) -> MetricSet``. Adding a domain means adding its
module to :data:`DOMAINS`; the registry and :func:`spot_report.metrics.compute_metrics`
pick it up from there.
"""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

from spot_report.metrics import (
    absences,
    association,
    demography,
    diagnoses,
    stigma,
    symptoms,
)
from spot_report.metrics.registry import MetricRegistry

if TYPE_CHECKING:
    from spot_report.questionnaire import QuestionnaireSpec

__all__ = ["DOMAINS", "default_registry"]

DOMAINS: tuple[ModuleType, ...] = (
    demography,
    diagnoses,
    absences,
    symptoms,
    association,
    stigma,
)


def default_registry(spec: QuestionnaireSpec) -> MetricRegistry:
    """The registry of all metrics of all domains for ``spec`` (duplicate ids raise)."""
    return MetricRegistry([d for module in DOMAINS for d in module.definitions(spec)])
