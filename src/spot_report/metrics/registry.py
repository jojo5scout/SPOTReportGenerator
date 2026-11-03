"""Metric registry: which ids exist, of which kind, and what they depend on.

Architecture section 6.2: the registry records for every metric id its kind, domain, the
questionnaire items (column codes) it depends on, and since which questionnaire version
it exists. There is no mutable module-level registry: every domain module exposes a
tuple of :class:`MetricDefinition` and one function assembles a :class:`MetricRegistry`
from all of them.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from spot_report.metrics.types import (
    METRIC_KINDS,
    MetricError,
    MetricSet,
    validate_metric_id,
)

__all__ = ["METRICS_VERSION", "MetricDefinition", "MetricRegistry", "RegistryError"]

METRICS_VERSION = 1
"""Version of the metric definitions, stored per wave (architecture section 6.4).

Bump it whenever a change makes numbers of an existing metric id incomparable with
snapshots stored earlier: a changed computation, scoring rule or cut-off, a changed
meaning of an existing id, or a changed payload layout of an existing kind. Do not bump
it for new ids or for pure refactoring. Renaming an id also needs a migration.
"""

_VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*")


class RegistryError(MetricError):
    """The registry is inconsistent, or a metric set does not match it."""


@dataclass(frozen=True)
class MetricDefinition:
    """Metadata of one metric id.

    ``items`` are the questionnaire column codes the metric depends on; ``since`` is
    the first questionnaire version (for example ``"2026.1"``) for which it exists.
    """

    id: str
    kind: str
    domain: str
    items: tuple[str, ...]
    since: str

    def __post_init__(self) -> None:
        validate_metric_id(self.id)
        if self.kind not in METRIC_KINDS:
            raise RegistryError(
                f"Metric {self.id}: unknown kind {self.kind!r}; "
                f"known: {sorted(METRIC_KINDS)}"
            )
        if self.domain != self.id.split(".")[0]:
            raise RegistryError(
                f"Metric {self.id}: domain {self.domain!r} must equal the first "
                "segment of the id"
            )
        if not isinstance(self.items, tuple) or not all(
            isinstance(item, str) and item for item in self.items
        ):
            raise RegistryError(f"Metric {self.id}: items must be a tuple of codes")
        if not isinstance(self.since, str) or not _VERSION_PATTERN.fullmatch(
            self.since
        ):
            raise RegistryError(f"Metric {self.id}: invalid since version")


class MetricRegistry(Mapping[str, MetricDefinition]):
    """Immutable lookup of :class:`MetricDefinition` by metric id."""

    __slots__ = ("_definitions",)

    def __init__(self, definitions: Sequence[MetricDefinition]) -> None:
        by_id: dict[str, MetricDefinition] = {}
        for definition in definitions:
            if definition.id in by_id:
                raise RegistryError(f"Duplicate metric id {definition.id!r}")
            by_id[definition.id] = definition
        self._definitions: dict[str, MetricDefinition] = dict(sorted(by_id.items()))

    def __getitem__(self, metric_id: str) -> MetricDefinition:
        try:
            return self._definitions[metric_id]
        except KeyError:
            raise KeyError(f"Unknown metric id {metric_id!r}") from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def __repr__(self) -> str:
        return f"MetricRegistry({len(self)} metrics)"

    def check(self, metric_set: MetricSet) -> None:
        """Raise :class:`RegistryError` unless every id is registered with its kind.

        All problems are reported together.
        """
        problems: list[str] = []
        for metric_id, metric in metric_set.items():
            definition = self._definitions.get(metric_id)
            if definition is None:
                problems.append(f"unregistered id {metric_id!r}")
            elif metric.kind != definition.kind:
                problems.append(
                    f"{metric_id!r} has kind {metric.kind!r}, registered as "
                    f"{definition.kind!r}"
                )
        if problems:
            raise RegistryError(
                "Metric set does not match the registry: " + "; ".join(problems)
            )
