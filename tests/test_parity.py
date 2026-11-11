"""The legacy parity baseline and its helper (roadmap R13, ADR 0002).

Domain parity tests (R14-R21) live with their domains; this module checks the expected
files themselves and the behaviour of ``assert_parity``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.parity import (
    EXPECTED_DIR,
    KNOWN_DEVIATIONS_FILE,
    ExpectedFormatError,
    Number,
    assert_parity,
    expected_datasets,
    find_deviation,
    load_expected,
    load_known_deviations,
    parse_expected,
    round_half_up,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
DATASETS = expected_datasets()
DOMAINS = (
    "demography",
    "diagnoses",
    "absences",
    "symptoms",
    "assoc",
    "stigma",
    "burnout",
    "resilience",
)

# --------------------------------------------------------------------------------------
# The committed expected files
# --------------------------------------------------------------------------------------


def test_every_fixture_has_an_expected_file() -> None:
    fixtures = {p.stem for p in FIXTURE_DIR.glob("*.xlsx")}
    assert set(DATASETS) == fixtures


@pytest.mark.parametrize("dataset", DATASETS)
def test_expected_file_loads_with_header(dataset: str) -> None:
    expected = load_expected(dataset)
    header = expected.header
    assert header["dataset"] == dataset
    assert header["source"] == f"{dataset}.xlsx"
    assert expected.generated_by.startswith("previous program, commit ")
    assert len(expected) > 0
    # No local paths in the header.
    for value in header.values():
        assert not str(value).startswith(("/", "~")), "absolute path in header"


@pytest.mark.parametrize("dataset", DATASETS)
def test_expected_file_covers_every_domain(dataset: str) -> None:
    expected = load_expected(dataset)
    for domain in DOMAINS:
        assert expected.under(domain), f"no values for {domain}"


@pytest.mark.parametrize("dataset", DATASETS)
def test_aliased_instruments_use_their_alias(dataset: str) -> None:
    expected = load_expected(dataset)
    assert {key.split(".")[1] for key in expected.under("resilience")} == {"res"}


@pytest.mark.parametrize("dataset", DATASETS)
def test_excluded_keys_and_free_text_chapter_are_not_stored(dataset: str) -> None:
    expected = load_expected(dataset)
    excluded = set(expected.header["excluded"])
    assert not excluded & set(expected)
    assert not [key for key in expected if key.startswith("angebotswunsch")]


@pytest.mark.parametrize("dataset", DATASETS)
def test_percentages_are_consistent_with_their_counts(dataset: str) -> None:
    expected = load_expected(dataset)
    for prefix in ("demography.gender", "symptoms.phq9.sev", "diagnoses.help"):
        for key, entry in expected.under(f"{prefix}.pct").items():
            count_key = key.replace(".pct.", ".count.")
            assert entry.numerator == expected.count(count_key), key


@pytest.mark.parametrize("dataset", DATASETS)
def test_values_reproduce_themselves(dataset: str) -> None:
    """Every legacy number passes its own parity check (shares for percentages).

    Keys with a known deviation are skipped: their check expects the recorded new value
    (the domain tests and ``test_known_deviations_file_is_valid`` cover them).
    """
    expected = load_expected(dataset)
    deviations = load_known_deviations()
    for key, entry in expected.items():
        if find_deviation(deviations, dataset, key) is not None:
            continue
        if entry.kind == "percent" and entry.denominator:
            assert entry.numerator is not None
            new: Number | None = Fraction(entry.numerator, entry.denominator)
        else:
            new = entry.reference
        assert_parity(dataset, key, new)


def test_known_deviations_file_is_valid() -> None:
    deviations = load_known_deviations()
    for deviation in deviations:
        datasets = DATASETS if deviation.dataset == "*" else (deviation.dataset,)
        for dataset in datasets:
            entry = load_expected(dataset)[deviation.key]
            assert deviation.legacy == entry.value, deviation.key


# --------------------------------------------------------------------------------------
# assert_parity on hand-made files
# --------------------------------------------------------------------------------------


def _document(dataset: str, values: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "header": {
            "schema_version": 1,
            "dataset": dataset,
            "source": f"{dataset}.xlsx",
            "generated_by": "previous program, commit abc1234",
        },
        "values": values,
    }


def _percent(numerator: int, denominator: int, value: int) -> dict[str, Any]:
    return {
        "kind": "percent",
        "value": value,
        "decimals": 0,
        "unrounded": float(Fraction(numerator, denominator) * 100)
        if denominator
        else None,
        "numerator": numerator,
        "denominator": denominator,
    }


HANDMADE: dict[str, dict[str, Any]] = {
    "demo.count.a": {"kind": "count", "value": 7},
    "demo.pct.tie": _percent(69, 200, 35),
    "demo.pct.third": _percent(1, 3, 33),
    "demo.pct.empty": _percent(0, 0, 0),
    "demo.mean.unrounded": {
        "kind": "statistic",
        "value": 23.32,
        "decimals": 2,
        "unrounded": 23.32,
    },
    "demo.mean.shown_only": {
        "kind": "statistic",
        "value": 2.13,
        "decimals": 2,
        "unrounded": None,
    },
    "demo.mean.undefined": {
        "kind": "statistic",
        "value": None,
        "decimals": None,
        "unrounded": None,
    },
    "demo.box.median": {
        "kind": "statistic",
        "value": 4.5,
        "decimals": None,
        "unrounded": None,
    },
}


@pytest.fixture
def expected_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "expected"
    directory.mkdir()
    for dataset in ("set_a", "set_b"):
        text = json.dumps(_document(dataset, HANDMADE))
        (directory / f"{dataset}.json").write_text(text, encoding="utf-8")
    return directory


def _deviations_file(directory: Path, entries: list[dict[str, Any]]) -> Path:
    path = directory / "known_deviations.yaml"
    path.write_text(yaml.safe_dump({"deviations": entries}), encoding="utf-8")
    return path


@pytest.fixture
def no_deviations(expected_dir: Path) -> Path:
    return _deviations_file(expected_dir, [])


def check(
    key: str,
    new: Number | None,
    expected_dir: Path,
    deviations: Path,
    dataset: str = "set_a",
) -> None:
    assert_parity(
        dataset, key, new, expected_dir=expected_dir, deviations_file=deviations
    )


@pytest.mark.parametrize(
    ("key", "new"),
    [
        ("demo.count.a", 7),
        ("demo.count.a", 7.0),
        ("demo.pct.tie", 69 / 200),
        ("demo.pct.tie", Fraction(69, 200)),
        ("demo.pct.tie", Decimal("0.345")),
        ("demo.pct.third", 1 / 3),
        ("demo.pct.empty", 0.0),
        ("demo.mean.unrounded", 23.32),
        ("demo.mean.unrounded", 23.32 + 1e-12),
        ("demo.mean.shown_only", 2.125),  # half-up at 2 decimals
        ("demo.mean.shown_only", 2.1349),
        ("demo.mean.undefined", None),
        ("demo.box.median", 4.5),
    ],
)
def test_matching_values_pass(
    key: str, new: Number | None, expected_dir: Path, no_deviations: Path
) -> None:
    check(key, new, expected_dir, no_deviations)


@pytest.mark.parametrize(
    ("key", "new"),
    [
        ("demo.count.a", 8),
        ("demo.count.a", 7.4),  # a count must be exact, not rounded
        ("demo.count.a", None),
        ("demo.pct.tie", 0.35),  # the unrounded percentage is compared
        ("demo.pct.tie", 34.5),  # a percentage instead of a share
        ("demo.pct.third", 0.334),
        ("demo.pct.empty", None),  # legacy showed 0 % for an empty denominator
        ("demo.mean.unrounded", 23.3201),
        ("demo.mean.shown_only", 2.1249),
        ("demo.mean.shown_only", 2.135),
        ("demo.mean.undefined", 1.0),
        ("demo.box.median", 4.6),
    ],
)
def test_differing_values_fail(
    key: str, new: Number | None, expected_dir: Path, no_deviations: Path
) -> None:
    with pytest.raises(AssertionError, match="Legacy parity failed"):
        check(key, new, expected_dir, no_deviations)


def test_failure_message_shows_both_values(
    expected_dir: Path, no_deviations: Path
) -> None:
    with pytest.raises(AssertionError) as info:
        check("demo.pct.tie", 0.34, expected_dir, no_deviations)
    message = str(info.value)
    assert "demo.pct.tie (percent)" in message
    assert "legacy fraction:  69/200" in message
    assert "new:              34" in message


def test_unknown_key_and_dataset(expected_dir: Path, no_deviations: Path) -> None:
    with pytest.raises(KeyError, match=r"no legacy value 'demo\.nope'"):
        check("demo.nope", 1, expected_dir, no_deviations)
    with pytest.raises(FileNotFoundError):
        check("demo.count.a", 7, expected_dir, no_deviations, dataset="set_c")


def test_bool_is_rejected(expected_dir: Path, no_deviations: Path) -> None:
    with pytest.raises(TypeError):
        check("demo.count.a", True, expected_dir, no_deviations)


@pytest.mark.parametrize(
    ("value", "decimals", "rounded"),
    [
        (Decimal("34.4999"), 0, "34"),
        (Decimal("34.5"), 0, "35"),
        (0.125, 2, "0.13"),
        (2.675, 2, "2.68"),  # shortest repr is 2.675: half-up, unlike round()
        (-0.5, 0, "-1"),
        (Fraction(1, 8), 2, "0.13"),
        (7, 1, "7.0"),
    ],
)
def test_round_half_up(value: Number, decimals: int, rounded: str) -> None:
    assert round_half_up(value, decimals) == Decimal(rounded)


def test_half_up_ties_in_the_real_baseline() -> None:
    """synthetic_800 has percentages exactly on .5; shares must pass as floats."""
    assert load_expected("synthetic_800")["diagnoses.pct.ADHS"].value == 1
    assert_parity("synthetic_800", "diagnoses.pct.ADHS", 4 / 800)
    assert_parity("synthetic_800", "demography.level.pct.Gym2", 212 / 800)


# --------------------------------------------------------------------------------------
# Known deviations
# --------------------------------------------------------------------------------------


def _deviation(**overrides: object) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "dataset": "set_a",
        "key": "demo.count.a",
        "legacy": 7,
        "new": 9,
        "task": "R14",
        "reason": "Intentional fix, see the pull request.",
    }
    entry.update(overrides)
    return entry


def test_recorded_deviation_passes_with_the_recorded_new_value(
    expected_dir: Path,
) -> None:
    deviations = _deviations_file(expected_dir, [_deviation()])
    check("demo.count.a", 9, expected_dir, deviations)


def test_recorded_deviation_catches_a_later_change(expected_dir: Path) -> None:
    deviations = _deviations_file(expected_dir, [_deviation()])
    with pytest.raises(AssertionError, match="changed since"):
        check("demo.count.a", 10, expected_dir, deviations)


def test_stale_deviation_fails(expected_dir: Path) -> None:
    deviations = _deviations_file(expected_dir, [_deviation()])
    with pytest.raises(AssertionError, match="Stale known deviation"):
        check("demo.count.a", 7, expected_dir, deviations)


def test_deviation_with_wrong_legacy_value_fails(expected_dir: Path) -> None:
    deviations = _deviations_file(expected_dir, [_deviation(legacy=6)])
    with pytest.raises(AssertionError, match="records legacy 6"):
        check("demo.count.a", 9, expected_dir, deviations)


def test_deviation_for_one_dataset_does_not_apply_to_another(
    expected_dir: Path,
) -> None:
    deviations = _deviations_file(expected_dir, [_deviation()])
    check("demo.count.a", 7, expected_dir, deviations, dataset="set_b")
    with pytest.raises(AssertionError, match="Legacy parity failed"):
        check("demo.count.a", 9, expected_dir, deviations, dataset="set_b")


def test_wildcard_deviation_applies_to_every_dataset(expected_dir: Path) -> None:
    deviations = _deviations_file(expected_dir, [_deviation(dataset="*")])
    for dataset in ("set_a", "set_b"):
        check("demo.count.a", 9, expected_dir, deviations, dataset=dataset)


def test_percent_deviation_is_compared_in_percent_units(expected_dir: Path) -> None:
    deviation = _deviation(key="demo.pct.tie", legacy=35, new=40.0)
    deviations = _deviations_file(expected_dir, [deviation])
    check("demo.pct.tie", 0.4, expected_dir, deviations)
    with pytest.raises(AssertionError, match="changed since"):
        check("demo.pct.tie", 0.41, expected_dir, deviations)


def test_shown_only_deviation_is_compared_at_legacy_precision(
    expected_dir: Path,
) -> None:
    deviation = _deviation(key="demo.mean.shown_only", legacy=2.13, new=2.2)
    deviations = _deviations_file(expected_dir, [deviation])
    check("demo.mean.shown_only", 2.196, expected_dir, deviations)


def test_deviation_to_undefined(expected_dir: Path) -> None:
    deviation = _deviation(key="demo.pct.empty", legacy=0, new=None)
    deviations = _deviations_file(expected_dir, [deviation])
    check("demo.pct.empty", None, expected_dir, deviations)
    with pytest.raises(AssertionError, match="Stale"):
        check("demo.pct.empty", 0.0, expected_dir, deviations)


@pytest.mark.parametrize(
    "entries",
    [
        [_deviation(task="16")],
        [_deviation(reason="")],
        [_deviation(new="9")],
        [{k: v for k, v in _deviation().items() if k != "reason"}],
        [{**_deviation(), "note": "extra"}],
        [_deviation(), _deviation(new=10)],
    ],
    ids=["task", "reason", "new-text", "missing", "extra", "duplicate"],
)
def test_malformed_deviations_are_rejected(
    expected_dir: Path, entries: list[dict[str, Any]]
) -> None:
    path = _deviations_file(expected_dir, entries)
    with pytest.raises(ExpectedFormatError):
        load_known_deviations(path)


def test_overlapping_deviations_are_ambiguous(expected_dir: Path) -> None:
    path = _deviations_file(expected_dir, [_deviation(), _deviation(dataset="*")])
    deviations = load_known_deviations(path)
    with pytest.raises(ExpectedFormatError, match="Several"):
        find_deviation(deviations, "set_a", "demo.count.a")


def test_committed_deviations_file_is_the_default() -> None:
    assert KNOWN_DEVIATIONS_FILE.parent == EXPECTED_DIR
    assert KNOWN_DEVIATIONS_FILE.is_file()


# --------------------------------------------------------------------------------------
# Format validation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "entry"),
    [
        ("demo.count", {"kind": "count", "value": 1.5}),
        ("demo.count", {"kind": "count", "value": -1}),
        ("demo.count", {"kind": "count", "value": True}),
        ("demo.count", {"kind": "count", "value": "7"}),
        ("demo.count", {"kind": "count", "value": 7, "decimals": 0}),
        ("demo.x", {"kind": "ratio", "value": 1}),
        ("demo.pct", {**_percent(1, 3, 33), "unrounded": 34.0}),
        ("demo.pct", {**_percent(1, 3, 33), "value": 34}),
        ("demo.pct", {**_percent(1, 3, 33), "numerator": None}),
        ("demo.mean", {"kind": "statistic", "value": 2.135, "decimals": 2}),
        (
            "demo.mean",
            {"kind": "statistic", "value": 2.135, "decimals": 2, "unrounded": None},
        ),
        ("no_dot", {"kind": "count", "value": 1}),
        ("demo.text key", {"kind": "count", "value": 1}),
    ],
)
def test_malformed_entries_are_rejected(key: str, entry: dict[str, Any]) -> None:
    with pytest.raises(ExpectedFormatError):
        parse_expected(_document("set_a", {key: entry}), dataset="set_a")


def test_malformed_header_is_rejected() -> None:
    document = _document("set_a", {"demo.count": {"kind": "count", "value": 1}})
    del document["header"]["generated_by"]
    with pytest.raises(ExpectedFormatError, match="header"):
        parse_expected(document, dataset="set_a")
    document = _document("set_b", {"demo.count": {"kind": "count", "value": 1}})
    with pytest.raises(ExpectedFormatError, match="another dataset"):
        parse_expected(document, dataset="set_a")
