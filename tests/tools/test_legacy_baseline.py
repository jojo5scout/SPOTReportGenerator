"""The pure parts of the legacy baseline driver.

Running the driver needs the previous program and is not part of the test suite; these
tests only check how it turns legacy output into stored entries.
"""

from __future__ import annotations

import json

import pytest

from tools import legacy_baseline
from tools.legacy_baseline import (
    KIND_PERCENT,
    KIND_STATISTIC,
    BaselineError,
    Tagged,
    apply_aliases,
    call_capturing_locals,
    flatten_context,
    parse_display,
    render,
)


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("34%", (34, 0)),
        ("34", (34, 0)),
        ("0.0%", (0.0, 1)),
        ("2.35", (2.35, 2)),
        ("31.20", (31.2, 2)),
        ("—", (None, None)),
        ("n/a", (None, None)),
        ("nan", (None, None)),
    ],
)
def test_parse_display(text: str, parsed: tuple[object, object]) -> None:
    assert parse_display(text) == parsed


def test_parse_display_rejects_text() -> None:
    with pytest.raises(BaselineError):
        parse_display("viele")


def _pct(text: str, numerator: int, denominator: int) -> Tagged:
    return Tagged(
        text,
        kind=KIND_PERCENT,
        unrounded=numerator * 100 / denominator,
        numerator=numerator,
        denominator=denominator,
    )


def test_flatten_context(monkeypatch: pytest.MonkeyPatch) -> None:
    excluded = "other_chapter.left_out"
    monkeypatch.setattr(legacy_baseline, "EXCLUDED_KEYS", {excluded: "reason"})
    context = {
        "chapter": {
            "n": 12,
            "chart": None,
            "pct": {"a": _pct("25%", 3, 12)},
            "mean": Tagged("2.35", kind=KIND_STATISTIC, unrounded=2.3456),
        },
        **_nested(excluded, 5),
    }
    entries = dict(flatten_context(context))
    assert entries == {
        "chapter.n": {"kind": "count", "value": 12},
        "chapter.pct.a": {
            "kind": "percent",
            "value": 25,
            "decimals": 0,
            "unrounded": 25.0,
            "numerator": 3,
            "denominator": 12,
        },
        "chapter.mean": {
            "kind": "statistic",
            "value": 2.35,
            "decimals": 2,
            "unrounded": 2.3456,
        },
    }


def _nested(dotted: str, value: object) -> dict[str, object]:
    result: object = value
    for segment in reversed(dotted.split(".")):
        result = {segment: result}
    assert isinstance(result, dict)
    return result


@pytest.mark.parametrize("leaf", ["some text", 1.5, True, ["a"]])
def test_flatten_context_rejects_untagged_leaves(leaf: object) -> None:
    with pytest.raises(BaselineError, match=r"chapter\.x"):
        dict(flatten_context({"chapter": {"x": leaf}}))


def test_apply_aliases_replaces_the_instrument_segment() -> None:
    assert apply_aliases("resilience.anything.all.mean") == "resilience.res.all.mean"
    assert apply_aliases("burnout.sbi.mean.total") == "burnout.sbi.mean.total"


def test_call_capturing_locals() -> None:
    def legacy_like(x: int) -> int:
        doubled = x * 2
        return doubled + 1

    result, local = call_capturing_locals(legacy_like, 4)
    assert result == 9
    assert local["doubled"] == 8


def test_render_is_deterministic() -> None:
    text = render({"values": {"b": 1, "a": 2}, "header": {}})
    assert text.endswith("\n")
    assert list(json.loads(text)["values"]) == ["a", "b"]
