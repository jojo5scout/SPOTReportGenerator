"""The metric domains and the registry assembled from them.

Each domain is a module ``metrics/<domain>.py`` with a tuple ``DEFINITIONS`` of
:class:`~spot_report.metrics.registry.MetricDefinition` and a pure function
``compute(responses, features, spec) -> MetricSet``. Adding a domain means adding its
module to :data:`DOMAINS`; the registry and :func:`spot_report.metrics.compute_metrics`
pick it up from there.
"""

from __future__ import annotations

from types import ModuleType

from spot_report.metrics import demography
from spot_report.metrics.registry import MetricRegistry

__all__ = ["DOMAINS", "default_registry"]

DOMAINS: tuple[ModuleType, ...] = (demography,)


def default_registry() -> MetricRegistry:
    """The registry of all metrics of all domains (duplicate ids raise)."""
    return MetricRegistry([d for module in DOMAINS for d in module.DEFINITIONS])
