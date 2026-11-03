"""Metric value types (architecture section 6.1) and their JSON representation.

Every metric is an immutable dataclass holding raw numbers: no formatting, no rounding,
no I/O. Derived values (shares) are computed properties and never stored. Computation
conventions are fixed for all domains and live next to the types:

* standard deviation with ``ddof=1`` (sample SD), undefined (``None``) for ``n < 2``;
* quartiles and median with the NumPy/pandas default (``linear``);
* floats are plain Python floats, finite (no NaN, no infinity).

JSON representation: ``to_dict`` gives a dict tagged with ``"kind"``, for example
``{"kind": "proportion", "k": 3, "n": 10, "n_missing": 1}``. The kind strings are the
values of the ``kind`` column of the store. ``None`` is written as ``null``; floats
survive a round trip exactly. Adding a new kind means adding a class to
:data:`METRIC_TYPES`; existing payloads do not change.

Error messages never contain values from the data, only counts and names.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType
from typing import Any, ClassVar, Self

import numpy as np
import pandas as pd

__all__ = [
    "METRIC_KINDS",
    "METRIC_TYPES",
    "Distribution",
    "Metric",
    "MetricError",
    "MetricFormatError",
    "MetricIdError",
    "MetricSet",
    "Proportion",
    "Summary",
    "metric_from_dict",
    "metric_from_json",
    "validate_metric_id",
]


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------


class MetricError(ValueError):
    """A metric value, id or payload violates the metric contract."""


class MetricIdError(MetricError):
    """A metric id does not follow ``domain.instrument.measure[.subgroup]``."""


class MetricFormatError(MetricError):
    """A JSON payload is not a well-formed metric."""


# --------------------------------------------------------------------------------------
# Metric ids
# --------------------------------------------------------------------------------------

_SEGMENT = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def validate_metric_id(metric_id: str) -> str:
    """Return ``metric_id`` unchanged if it is valid, else raise :class:`MetricIdError`.

    Pattern: ``domain.instrument.measure[.subgroup]``, that is 3 or 4 segments separated
    by single dots, every segment non-empty and made of ``[a-z0-9_]`` only.
    """
    if not isinstance(metric_id, str):
        raise MetricIdError(
            f"Metric id must be a string, got {type(metric_id).__name__}"
        )
    segments = metric_id.split(".")
    if len(segments) not in (3, 4):
        raise MetricIdError(
            f"Invalid metric id {metric_id!r}: expected 3 or 4 dot-separated segments "
            f"(domain.instrument.measure[.subgroup]), found {len(segments)}"
        )
    for segment in segments:
        if not segment or not set(segment) <= _SEGMENT:
            raise MetricIdError(
                f"Invalid metric id {metric_id!r}: every segment must be non-empty "
                "and consist of [a-z0-9_] only"
            )
    return metric_id


# --------------------------------------------------------------------------------------
# Field validation helpers
# --------------------------------------------------------------------------------------


def _count(owner: str, name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MetricError(f"{owner}.{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise MetricError(f"{owner}.{name} must not be negative")
    return value


def _optional_float(owner: str, name: str, value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MetricError(
            f"{owner}.{name} must be a number or None, got {type(value).__name__}"
        )
    result = float(value)
    if not math.isfinite(result):
        raise MetricError(f"{owner}.{name} must be finite (use None for undefined)")
    return result


def _no_missing_values(values: pd.Series, what: str) -> None:
    if not isinstance(values, pd.Series):
        raise TypeError(f"{what} must be a pandas Series")
    count = int(values.isna().sum())
    if count:
        raise ValueError(
            f"{what} contains {count} missing value(s); drop them and pass their "
            "number as n_missing"
        )


# --------------------------------------------------------------------------------------
# Metric base class
# --------------------------------------------------------------------------------------


class Metric(ABC):
    """Common interface of all metric types: a ``kind`` tag and JSON conversion."""

    kind: ClassVar[str]
    n_missing: int

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible dict, including the ``"kind"`` tag."""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Inverse of :meth:`to_dict`; raises :class:`MetricFormatError`."""

    def to_json(self) -> str:
        """Compact JSON text (NaN and infinity are rejected on construction)."""
        return _dumps(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> Self:
        metric = metric_from_json(text)
        if not isinstance(metric, cls):
            raise MetricFormatError(
                f"Expected a {cls.kind!r} payload, got {metric.kind!r}"
            )
        return metric


def _dumps(obj: object) -> str:
    return json.dumps(obj, allow_nan=False, separators=(",", ":"))


def _check_payload(
    cls: type[Metric], data: Mapping[str, Any], fields: Sequence[str]
) -> None:
    """Strict structure check: a mapping with exactly ``kind`` plus ``fields``."""
    if not isinstance(data, Mapping):
        raise MetricFormatError(f"{cls.kind} payload must be an object")
    if data.get("kind") != cls.kind:
        raise MetricFormatError(f"Payload is not of kind {cls.kind!r}")
    expected = {"kind", *fields}
    missing = sorted(expected - data.keys())
    extra = sorted(str(key) for key in data.keys() - expected)
    if missing or extra:
        raise MetricFormatError(
            f"{cls.kind} payload has missing keys {missing} and unexpected keys {extra}"
        )


def _construct[M: Metric](cls: type[M], **fields: object) -> M:
    """Build ``cls`` from payload fields; invariant violations become format errors."""
    try:
        return cls(**fields)
    except MetricError as exc:
        raise MetricFormatError(f"Invalid {cls.kind} payload: {exc}") from exc


# --------------------------------------------------------------------------------------
# Proportion
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Proportion(Metric):
    """``k`` of ``n`` valid answers; ``n_missing`` respondents were left out."""

    kind: ClassVar[str] = "proportion"

    k: int
    n: int
    n_missing: int = 0

    def __post_init__(self) -> None:
        owner = type(self).__name__
        _count(owner, "k", self.k)
        _count(owner, "n", self.n)
        _count(owner, "n_missing", self.n_missing)
        if self.k > self.n:
            raise MetricError(f"{owner}: k must not exceed n")

    @property
    def share(self) -> float | None:
        """``k / n`` as a fraction in [0, 1]; ``None`` when ``n == 0``."""
        return self.k / self.n if self.n else None

    @classmethod
    def from_mask(cls, mask: pd.Series, n_missing: int = 0) -> Proportion:
        """Count ``True`` in a boolean Series of the valid respondents.

        ``mask`` has one entry per respondent that counts for this metric (``n`` is its
        length) and must not contain missing values; respondents who are left out are
        passed as ``n_missing``.
        """
        _no_missing_values(mask, "mask")
        if not pd.api.types.is_bool_dtype(mask.dtype):
            raise TypeError("mask must have a boolean dtype")
        return cls(k=int(mask.sum()), n=len(mask), n_missing=n_missing)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "k": self.k,
            "n": self.n,
            "n_missing": self.n_missing,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Proportion:
        _check_payload(cls, data, ("k", "n", "n_missing"))
        return _construct(cls, k=data["k"], n=data["n"], n_missing=data["n_missing"])


# --------------------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------------------

_SUMMARY_STATS = ("mean", "sd", "median", "q1", "q3", "min", "max")


@dataclass(frozen=True)
class Summary(Metric):
    """Descriptive statistics of a numeric variable over ``n`` valid values.

    * ``n == 0``: all statistics are ``None``.
    * ``n == 1``: the sample SD (``ddof=1``) is undefined and ``None``; the other
      statistics are defined.
    * ``n >= 2``: all statistics are numbers.

    Quartiles use the NumPy/pandas default method (``linear``).
    """

    kind: ClassVar[str] = "summary"

    n: int
    n_missing: int
    mean: float | None
    sd: float | None
    median: float | None
    q1: float | None
    q3: float | None
    min: float | None
    max: float | None

    def __post_init__(self) -> None:
        owner = type(self).__name__
        _count(owner, "n", self.n)
        _count(owner, "n_missing", self.n_missing)
        for name in _SUMMARY_STATS:
            object.__setattr__(
                self, name, _optional_float(owner, name, getattr(self, name))
            )
        if self.n == 0:
            if any(getattr(self, name) is not None for name in _SUMMARY_STATS):
                raise MetricError(f"{owner}: all statistics must be None when n == 0")
            return
        defined = [name for name in _SUMMARY_STATS if name != "sd"]
        if any(getattr(self, name) is None for name in defined):
            raise MetricError(f"{owner}: statistics must not be None when n >= 1")
        if self.n == 1:
            if self.sd is not None:
                raise MetricError(f"{owner}: sd must be None when n == 1")
        elif self.sd is None:
            raise MetricError(f"{owner}: sd must not be None when n >= 2")
        if self.sd is not None and self.sd < 0:
            raise MetricError(f"{owner}: sd must not be negative")
        ordered = [
            value
            for value in (self.min, self.q1, self.median, self.q3, self.max)
            if value is not None
        ]
        if any(a > b for a, b in pairwise(ordered)):
            raise MetricError(f"{owner}: expected min <= q1 <= median <= q3 <= max")

    @classmethod
    def from_values(cls, values: pd.Series, n_missing: int = 0) -> Summary:
        """Summarise the valid values of a numeric Series.

        ``values`` holds only the respondents that count for this metric (``n`` is its
        length) and must not contain missing values; respondents who are left out are
        passed as ``n_missing``. Mean and SD (``ddof=1``) are computed with NumPy,
        median and quartiles with ``numpy.quantile`` (``linear``). No rounding.
        """
        _no_missing_values(values, "values")
        if pd.api.types.is_bool_dtype(values.dtype) or not (
            pd.api.types.is_numeric_dtype(values.dtype)
        ):
            raise TypeError("values must have a numeric (non-boolean) dtype")
        array = values.to_numpy(dtype="float64")
        n = len(array)
        if n == 0:
            return cls(n, n_missing, None, None, None, None, None, None, None)
        q1, median, q3 = np.quantile(array, [0.25, 0.5, 0.75])
        return cls(
            n=n,
            n_missing=n_missing,
            mean=float(np.mean(array)),
            sd=float(np.std(array, ddof=1)) if n >= 2 else None,
            median=float(median),
            q1=float(q1),
            q3=float(q3),
            min=float(np.min(array)),
            max=float(np.max(array)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "n": self.n,
            "n_missing": self.n_missing,
            **{name: getattr(self, name) for name in _SUMMARY_STATS},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Summary:
        _check_payload(cls, data, ("n", "n_missing", *_SUMMARY_STATS))
        return _construct(
            cls, **{key: value for key, value in data.items() if key != "kind"}
        )


# --------------------------------------------------------------------------------------
# Distribution
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Distribution(Metric):
    """Counts per category, in a defined order (the order of ``categories``).

    A distribution without categories is valid (``n == 0``).
    """

    kind: ClassVar[str] = "distribution"

    categories: tuple[str, ...]
    counts: tuple[int, ...]
    n_missing: int = 0

    def __post_init__(self) -> None:
        owner = type(self).__name__
        if not isinstance(self.categories, tuple) or not all(
            isinstance(c, str) for c in self.categories
        ):
            raise MetricError(f"{owner}.categories must be a tuple of str")
        if not isinstance(self.counts, tuple):
            raise MetricError(f"{owner}.counts must be a tuple of int")
        for count in self.counts:
            _count(owner, "counts", count)
        _count(owner, "n_missing", self.n_missing)
        if len(self.categories) != len(self.counts):
            raise MetricError(f"{owner}: categories and counts differ in length")
        if len(set(self.categories)) != len(self.categories):
            raise MetricError(f"{owner}: categories must be unique")

    @property
    def n(self) -> int:
        """Valid answers: the sum of all counts."""
        return sum(self.counts)

    @property
    def shares(self) -> tuple[float, ...] | None:
        """Fraction per category (``count / n``); ``None`` when ``n == 0``."""
        n = self.n
        return tuple(count / n for count in self.counts) if n else None

    @classmethod
    def from_values(
        cls, values: pd.Series, categories: Sequence[str], n_missing: int = 0
    ) -> Distribution:
        """Count how often each category occurs in ``values``.

        ``values`` is compared as text (``astype("string")``), so integer codes match
        categories such as ``"3"``. It must not contain missing values and no value
        outside ``categories``; respondents who are left out are passed as
        ``n_missing``. The order of ``categories`` is kept.
        """
        _no_missing_values(values, "values")
        categories = tuple(categories)
        counted = values.astype("string").value_counts()
        unexpected = int((~counted.index.isin(categories)).sum())
        if unexpected:
            raise ValueError(f"values contain {unexpected} value(s) outside categories")
        counts = tuple(int(counted.get(category, 0)) for category in categories)
        return cls(categories=categories, counts=counts, n_missing=n_missing)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "categories": list(self.categories),
            "counts": list(self.counts),
            "n_missing": self.n_missing,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Distribution:
        _check_payload(cls, data, ("categories", "counts", "n_missing"))
        categories, counts = data["categories"], data["counts"]
        if not isinstance(categories, list) or not isinstance(counts, list):
            raise MetricFormatError("distribution categories and counts must be lists")
        return _construct(
            cls,
            categories=tuple(categories),
            counts=tuple(counts),
            n_missing=data["n_missing"],
        )


# --------------------------------------------------------------------------------------
# Kinds and dispatch
# --------------------------------------------------------------------------------------

#: All metric types. A new kind is added here and nowhere else.
METRIC_TYPES: tuple[type[Metric], ...] = (Proportion, Summary, Distribution)

#: ``kind`` tag -> type; the tags are the values of the store's ``kind`` column.
METRIC_KINDS: Mapping[str, type[Metric]] = MappingProxyType(
    {metric_type.kind: metric_type for metric_type in METRIC_TYPES}
)


def metric_from_dict(data: Mapping[str, Any]) -> Metric:
    """Build the metric named by ``data["kind"]``; raises :class:`MetricFormatError`."""
    if not isinstance(data, Mapping):
        raise MetricFormatError("Metric payload must be an object")
    kind = data.get("kind")
    metric_type = METRIC_KINDS.get(kind) if isinstance(kind, str) else None
    if metric_type is None:
        raise MetricFormatError(f"Unknown metric kind {kind!r}")
    return metric_type.from_dict(data)


def metric_from_json(text: str) -> Metric:
    """Parse JSON text produced by :meth:`Metric.to_json`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetricFormatError("Metric payload is not valid JSON") from exc
    return metric_from_dict(data)


# --------------------------------------------------------------------------------------
# MetricSet
# --------------------------------------------------------------------------------------


class MetricSet(Mapping[str, Metric]):
    """Immutable mapping of metric id to metric value.

    Ids are validated on construction. Iteration and serialisation use the ids in
    sorted order, so the JSON text is stable. Equality is mapping equality.
    """

    __slots__ = ("_metrics",)

    def __init__(self, metrics: Mapping[str, Metric] | None = None) -> None:
        items = dict(metrics or {})
        for metric_id, metric in items.items():
            validate_metric_id(metric_id)
            if not isinstance(metric, Metric):
                raise MetricError(f"Value of {metric_id!r} is not a metric")
        self._metrics: Mapping[str, Metric] = MappingProxyType(
            dict(sorted(items.items()))
        )

    def __getitem__(self, metric_id: str) -> Metric:
        return self._metrics[metric_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._metrics)

    def __len__(self) -> int:
        return len(self._metrics)

    def __repr__(self) -> str:
        return f"MetricSet({len(self)} metrics)"

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """``{metric_id: metric.to_dict()}`` with ids in sorted order."""
        return {metric_id: metric.to_dict() for metric_id, metric in self.items()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MetricSet:
        if not isinstance(data, Mapping):
            raise MetricFormatError("MetricSet payload must be an object")
        return cls({key: metric_from_dict(value) for key, value in data.items()})

    def to_json(self) -> str:
        return _dumps(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> MetricSet:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MetricFormatError("MetricSet payload is not valid JSON") from exc
        return cls.from_dict(data)
