"""Legacy parity checks for the metric domains (roadmap R13, ADR 0002).

``tests/fixtures/expected/<dataset>.json`` holds the numbers the previous program
computed from each synthetic fixture (written by ``tools/legacy_baseline.py``). Domain
tests compare their own unrounded results with them::

    from tests.parity import assert_parity

    def test_gender_share_matches_legacy() -> None:
        share = ...  # Proportion.share of the new metric, a number in [0, 1]
        assert_parity("synthetic_300", "demography.gender.pct.M", share)

How a new value is compared depends on the stored entry:

* ``count``: the new value must be an integer equal to the legacy count.
* ``percent``: the new value is a **share** in [0, 1] (as ``Proportion.share``); it
  is converted to a percentage before comparing.
* ``percent`` and ``statistic`` with an unrounded legacy value (``unrounded``, or
  ``decimals`` null): equal within :data:`FLOAT_TOLERANCE` (relative, at least
  absolute) in percent or statistic units.
* otherwise (the legacy shown value only, e.g. a percentage with denominator 0): the
  new value rounded half-up (``decimal.Decimal``) to the legacy ``decimals`` must equal
  the shown legacy value.
* ``None`` (undefined) matches only ``None``.

Known deviations
----------------
A deviation found by a domain task is not fixed there; it is recorded in
``tests/fixtures/expected/known_deviations.yaml`` (dataset or ``*``, key, legacy value
as shown, new value, task, reason). For a recorded key :func:`assert_parity` checks
that the new value still equals the recorded new value (compared like the legacy
value), so any later change is caught; an entry whose key matches the legacy value
again is stale and fails.
"""

from __future__ import annotations

import functools
import json
import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml

__all__ = [
    "EXPECTED_DIR",
    "FLOAT_TOLERANCE",
    "KNOWN_DEVIATIONS_FILE",
    "ExpectedFormatError",
    "ExpectedValue",
    "ExpectedValues",
    "KnownDeviation",
    "Number",
    "assert_parity",
    "expected_datasets",
    "find_deviation",
    "load_expected",
    "load_known_deviations",
    "parse_expected",
    "round_half_up",
]

EXPECTED_DIR = Path(__file__).parent / "fixtures" / "expected"
KNOWN_DEVIATIONS_FILE = EXPECTED_DIR / "known_deviations.yaml"
SCHEMA_VERSION = 1
#: Relative tolerance (and absolute below 1) for unrounded legacy values.
FLOAT_TOLERANCE = 1e-9

Kind = Literal["count", "percent", "statistic"]
KINDS: frozenset[str] = frozenset({"count", "percent", "statistic"})
HEADER_FIELDS = frozenset({"schema_version", "dataset", "source", "generated_by"})
DEVIATION_FIELDS = frozenset({"dataset", "key", "legacy", "new", "task", "reason"})
TASK_ID = re.compile(r"R\d+")
ALL_DATASETS = "*"

Number = int | float | Decimal | Fraction


class ExpectedFormatError(ValueError):
    """An expected-values file or the known-deviations file is malformed."""


# --------------------------------------------------------------------------------------
# Expected values
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedValue:
    """One number of the previous program; field meanings in the fixtures README."""

    key: str
    kind: Kind
    value: int | float | None
    decimals: int | None = None
    unrounded: float | None = None
    numerator: int | None = None
    denominator: int | None = None

    @property
    def is_percent(self) -> bool:
        return self.kind == "percent"

    @property
    def compares_unrounded(self) -> bool:
        """Whether new values are compared with a tolerance instead of rounding."""
        return self.kind != "count" and (
            self.unrounded is not None or self.decimals is None
        )

    @property
    def reference(self) -> int | float | None:
        """The legacy number new values are compared with."""
        return self.unrounded if self.unrounded is not None else self.value

    def to_units(self, new_value: Number) -> Decimal:
        """The new value in the units of this entry (a share becomes a percentage)."""
        number = _to_decimal(new_value)
        return number * 100 if self.is_percent else number

    def matches(self, new_value: Number | None) -> bool:
        """Whether ``new_value`` reproduces the legacy number."""
        return self.matches_reference(new_value, self.reference)

    def matches_reference(
        self, new_value: Number | None, reference: Number | None
    ) -> bool:
        """Whether ``new_value`` equals ``reference``, compared like the legacy value.

        ``reference`` is in the units of the entry (a percentage for ``percent``).
        """
        if new_value is None or reference is None:
            return new_value is None and reference is None
        if self.kind == "count":
            return _is_integral(new_value) and int(new_value) == reference
        units = self.to_units(new_value)
        if self.compares_unrounded:
            return _close(units, _to_decimal(reference))
        assert self.decimals is not None
        return round_half_up(units, self.decimals) == _to_decimal(reference)

    def describe(self, new_value: Number | None) -> str:
        """Legacy and new value side by side, for assertion messages."""
        units = "percent" if self.is_percent else self.kind
        new = None if new_value is None else _plain(self.to_units(new_value))
        lines = [
            f"{self.key} ({units})",
            f"  legacy shown:     {self.value!r} (decimals: {self.decimals})",
        ]
        if self.unrounded is not None:
            lines.append(f"  legacy unrounded: {self.unrounded!r}")
        if self.denominator is not None:
            lines.append(f"  legacy fraction:  {self.numerator}/{self.denominator}")
        lines.append(f"  new:              {new}")
        if (
            new_value is not None
            and self.decimals is not None
            and not self.compares_unrounded
        ):
            rounded = round_half_up(self.to_units(new_value), self.decimals)
            lines.append(f"  new rounded:      {_plain(rounded)}")
        return "\n".join(lines)


@dataclass(frozen=True, eq=False)
class ExpectedValues(Mapping[str, ExpectedValue]):
    """All legacy numbers of one dataset, by dotted key."""

    dataset: str
    header: Mapping[str, Any]
    values: Mapping[str, ExpectedValue] = field(repr=False)

    @property
    def generated_by(self) -> str:
        return str(self.header["generated_by"])

    def __getitem__(self, key: str) -> ExpectedValue:
        try:
            return self.values[key]
        except KeyError:
            raise KeyError(f"{self.dataset} has no legacy value {key!r}") from None

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def value(self, key: str) -> int | float | None:
        """The number the previous program showed (rounded as shown)."""
        return self[key].value

    def count(self, key: str) -> int:
        entry = self[key]
        if entry.kind != "count" or not isinstance(entry.value, int):
            raise KeyError(f"{self.dataset}: {key!r} is not a count")
        return entry.value

    def under(self, prefix: str) -> dict[str, ExpectedValue]:
        """The entries whose key starts with ``prefix`` followed by a dot."""
        start = prefix.rstrip(".") + "."
        return {k: v for k, v in self.values.items() if k.startswith(start)}


def expected_datasets(expected_dir: Path = EXPECTED_DIR) -> tuple[str, ...]:
    """The datasets that have an expected-values file."""
    return tuple(sorted(p.stem for p in expected_dir.glob("*.json")))


def load_expected(dataset: str, expected_dir: Path = EXPECTED_DIR) -> ExpectedValues:
    """Load and validate ``<expected_dir>/<dataset>.json`` (cached)."""
    return _load_expected_file(expected_dir.resolve() / f"{dataset}.json")


@functools.cache
def _load_expected_file(path: Path) -> ExpectedValues:
    if not path.is_file():
        raise FileNotFoundError(f"No legacy parity file {path.name}")
    document = json.loads(path.read_text(encoding="utf-8"))
    return parse_expected(document, dataset=path.stem)


def parse_expected(document: object, *, dataset: str) -> ExpectedValues:
    """Validate an expected-values document and turn it into typed entries."""
    if not isinstance(document, Mapping) or set(document) != {"header", "values"}:
        raise ExpectedFormatError(f"{dataset}: expected keys 'header' and 'values'")
    header, raw_values = document["header"], document["values"]
    if not isinstance(header, Mapping) or not set(header) >= HEADER_FIELDS:
        raise ExpectedFormatError(
            f"{dataset}: header needs {', '.join(sorted(HEADER_FIELDS))}"
        )
    if header["schema_version"] != SCHEMA_VERSION:
        raise ExpectedFormatError(f"{dataset}: unsupported schema_version")
    if header["dataset"] != dataset:
        raise ExpectedFormatError(f"{dataset}: header names another dataset")
    if not isinstance(raw_values, Mapping) or not raw_values:
        raise ExpectedFormatError(f"{dataset}: 'values' must be a non-empty object")
    values = {key: _parse_entry(dataset, key, raw) for key, raw in raw_values.items()}
    return ExpectedValues(
        dataset=dataset,
        header=MappingProxyType(dict(header)),
        values=MappingProxyType(values),
    )


_ENTRY_FIELDS: Mapping[str, frozenset[str]] = {
    "count": frozenset({"kind", "value"}),
    "percent": frozenset(
        {"kind", "value", "decimals", "unrounded", "numerator", "denominator"}
    ),
    "statistic": frozenset({"kind", "value", "decimals", "unrounded"}),
}
_KEY = re.compile(r"[A-Za-z0-9_+]+(\.[A-Za-z0-9_+]+)+")


def _parse_entry(dataset: str, key: str, raw: object) -> ExpectedValue:
    where = f"{dataset}: {key!r}"
    if not _KEY.fullmatch(key):
        raise ExpectedFormatError(f"{where}: malformed key")
    if not isinstance(raw, Mapping) or raw.get("kind") not in KINDS:
        raise ExpectedFormatError(f"{where}: missing or unknown kind")
    kind = raw["kind"]
    if set(raw) != _ENTRY_FIELDS[kind]:
        raise ExpectedFormatError(f"{where}: wrong fields for kind {kind}")
    entry = ExpectedValue(
        key=key,
        kind=kind,
        value=raw["value"],
        decimals=raw.get("decimals"),
        unrounded=raw.get("unrounded"),
        numerator=raw.get("numerator"),
        denominator=raw.get("denominator"),
    )
    _check_entry(where, entry)
    return entry


def _check_entry(where: str, entry: ExpectedValue) -> None:
    if entry.kind == "count":
        if not _is_count(entry.value):
            raise ExpectedFormatError(f"{where}: a count must be an integer >= 0")
        return
    if entry.value is not None and not _is_finite_number(entry.value):
        raise ExpectedFormatError(f"{where}: value must be a finite number or null")
    if entry.unrounded is not None and not _is_finite_number(entry.unrounded):
        raise ExpectedFormatError(f"{where}: unrounded must be a finite number")
    if entry.decimals is not None and not _is_count(entry.decimals):
        raise ExpectedFormatError(f"{where}: decimals must be an integer >= 0")
    if entry.value is None and entry.unrounded is not None:
        raise ExpectedFormatError(f"{where}: unrounded without a shown value")
    if entry.value is not None and entry.decimals is not None:
        shown = round_half_up(_to_decimal(entry.value), entry.decimals)
        if shown != _to_decimal(entry.value):
            raise ExpectedFormatError(f"{where}: value has more than decimals places")
    if entry.kind == "percent":
        _check_percent(where, entry)


def _check_percent(where: str, entry: ExpectedValue) -> None:
    if not (_is_count(entry.numerator) and _is_count(entry.denominator)):
        raise ExpectedFormatError(f"{where}: numerator and denominator must be counts")
    assert entry.numerator is not None
    assert entry.denominator is not None
    if entry.decimals is None or entry.value is None:
        raise ExpectedFormatError(f"{where}: a percentage needs value and decimals")
    if entry.denominator == 0:
        if entry.unrounded is not None:
            raise ExpectedFormatError(f"{where}: unrounded with denominator 0")
        return
    exact = Fraction(entry.numerator, entry.denominator) * 100
    if entry.unrounded is None or not math.isclose(
        entry.unrounded, float(exact), rel_tol=FLOAT_TOLERANCE
    ):
        raise ExpectedFormatError(f"{where}: unrounded does not match the fraction")
    # The previous program rounded the exact percentage half-up.
    shown = round_half_up(Decimal(entry.numerator) * 100 / entry.denominator, 0)
    if entry.decimals == 0 and shown != _to_decimal(entry.value):
        raise ExpectedFormatError(f"{where}: value is not the rounded fraction")


# --------------------------------------------------------------------------------------
# Known deviations
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KnownDeviation:
    """A documented difference between the new program and the previous one."""

    dataset: str  # a dataset name or "*" for every dataset
    key: str
    legacy: int | float | None  # the legacy value as shown (`value` of the entry)
    new: int | float | None  # the new value, in the units of the entry
    task: str  # roadmap id of the task that found it, e.g. "R16"
    reason: str

    def applies_to(self, dataset: str) -> bool:
        return self.dataset in (ALL_DATASETS, dataset)


def load_known_deviations(
    path: Path = KNOWN_DEVIATIONS_FILE,
) -> tuple[KnownDeviation, ...]:
    """Read and validate the known-deviations file."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping) or set(document) != {"deviations"}:
        raise ExpectedFormatError(f"{path.name}: expected one key 'deviations'")
    raw_entries = document["deviations"]
    if not isinstance(raw_entries, list):
        raise ExpectedFormatError(f"{path.name}: 'deviations' must be a list")
    deviations = tuple(
        _parse_deviation(path.name, i, raw) for i, raw in enumerate(raw_entries, 1)
    )
    seen: set[tuple[str, str]] = set()
    for deviation in deviations:
        ident = (deviation.dataset, deviation.key)
        if ident in seen:
            raise ExpectedFormatError(f"{path.name}: duplicate entry {ident}")
        seen.add(ident)
    return deviations


def _parse_deviation(source: str, index: int, raw: object) -> KnownDeviation:
    where = f"{source}: entry {index}"
    if not isinstance(raw, Mapping) or set(raw) != DEVIATION_FIELDS:
        raise ExpectedFormatError(
            f"{where}: needs exactly {', '.join(sorted(DEVIATION_FIELDS))}"
        )
    for name in ("dataset", "key", "task", "reason"):
        if not isinstance(raw[name], str) or not raw[name].strip():
            raise ExpectedFormatError(f"{where}: {name} must be a non-empty string")
    if not TASK_ID.fullmatch(raw["task"]):
        raise ExpectedFormatError(f"{where}: task must be a roadmap id like R16")
    for name in ("legacy", "new"):
        if raw[name] is not None and not _is_finite_number(raw[name]):
            raise ExpectedFormatError(f"{where}: {name} must be a number or null")
    return KnownDeviation(
        dataset=raw["dataset"],
        key=raw["key"],
        legacy=raw["legacy"],
        new=raw["new"],
        task=raw["task"],
        reason=raw["reason"],
    )


def find_deviation(
    deviations: tuple[KnownDeviation, ...], dataset: str, key: str
) -> KnownDeviation | None:
    """The deviation recorded for ``key`` in ``dataset``, if any."""
    matches = [d for d in deviations if d.key == key and d.applies_to(dataset)]
    if len(matches) > 1:
        raise ExpectedFormatError(f"Several known deviations for {dataset}: {key}")
    return matches[0] if matches else None


# --------------------------------------------------------------------------------------
# The parity check
# --------------------------------------------------------------------------------------


def assert_parity(
    dataset: str,
    key: str,
    new_value: Number | None,
    *,
    expected_dir: Path = EXPECTED_DIR,
    deviations_file: Path = KNOWN_DEVIATIONS_FILE,
) -> None:
    """Assert that a new, unrounded value reproduces the previous program's number.

    For a percentage ``new_value`` is a share in [0, 1]. If the key is recorded as a
    known deviation, the new value must equal the recorded new value instead, and the
    entry must still be needed (see the module docstring).
    """
    if isinstance(new_value, bool):
        raise TypeError("assert_parity needs a number, not a bool")
    entry = load_expected(dataset, expected_dir)[key]
    deviation = find_deviation(load_known_deviations(deviations_file), dataset, key)
    matches_legacy = entry.matches(new_value)

    if deviation is None:
        if not matches_legacy:
            raise AssertionError(
                f"Legacy parity failed for {dataset}:\n{entry.describe(new_value)}\n"
                "Fix the metric, or record a known deviation (ADR 0002)."
            )
        return

    context = f"known deviation {dataset}: {key} ({deviation.task})"
    if deviation.legacy != entry.value:
        raise AssertionError(
            f"The {context} records legacy {deviation.legacy!r}, the expected file "
            f"has {entry.value!r}; update the entry."
        )
    if matches_legacy:
        raise AssertionError(
            f"Stale {context}: the new value matches the legacy value again; "
            "remove the entry."
        )
    if not entry.matches_reference(new_value, deviation.new):
        raise AssertionError(
            f"The new value changed since the {context} was recorded "
            f"(recorded new: {deviation.new!r}):\n{entry.describe(new_value)}"
        )


# --------------------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------------------


def round_half_up(value: Number, decimals: int) -> Decimal:
    """``value`` rounded half-up to ``decimals`` places, as the previous program did.

    Floats are taken by their shortest representation (``repr``), so that a share such
    as ``69 / 200`` rounds like the exact fraction (34.5 % becomes 35 %).
    """
    return _to_decimal(value).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)


def _to_decimal(value: Number) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("parity values must be finite")
        return Decimal(repr(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    # NumPy scalars and similar: go through float / int.
    if float(value) == int(value):
        return Decimal(int(value))
    return Decimal(repr(float(value)))


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= Decimal(repr(FLOAT_TOLERANCE)) * max(Decimal(1), abs(b))


def _is_integral(value: Number) -> bool:
    try:
        return _to_decimal(value) == _to_decimal(value).to_integral_value()
    except (ValueError, TypeError, OverflowError):
        return False


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")
