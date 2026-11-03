from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from spot_report.questionnaire import (
    Question,
    QuestionKind,
    QuestionnaireSpec,
    Scale,
    Scoring,
    SpecError,
    UnknownVersionError,
    available_versions,
    load_spec,
    spec_from_mapping,
)

MINIMAL = """
version: "t.1"
response_id: id
metadata: [id]
single_choice:
  Q1:
    codes: ["A", "B"]
numeric:
  N1: {min: 1, max: 5}
multi_select:
  MS:
    selected: "Y"
    options: [ONE, TWO]
    optional_options: [THREE]
free_text:
  - {code: "MS[other]", group: MS}
scales:
  S:
    scoring: sum
    range: [0, 3]
    columns: ["S[A]", "S[B]", "S[C]"]
    subscales:
      LOW: ["S[A]", "S[B]"]
"""


def minimal() -> dict[str, Any]:
    return yaml.safe_load(MINIMAL)


@pytest.fixture(scope="module")
def spec() -> QuestionnaireSpec:
    return load_spec("2026.1")


# --- loader ------------------------------------------------------------------------


def test_available_versions_lists_shipped_spec() -> None:
    assert "2026.1" in available_versions()


def test_load_spec_returns_requested_version(spec: QuestionnaireSpec) -> None:
    assert spec.version == "2026.1"
    assert spec.response_id == "id"


@pytest.mark.parametrize("version", ["1999.9", "", "../2026.1", "2026.1.yaml"])
def test_unknown_version_is_a_clear_error(version: str) -> None:
    with pytest.raises(UnknownVersionError, match="Unknown questionnaire version"):
        load_spec(version)


# --- accessors on the real spec -----------------------------------------------------


def test_scale_columns(spec: QuestionnaireSpec) -> None:
    assert spec.scale("PHQ9").columns == tuple(f"PHQ9[PHQQ{i}]" for i in range(1, 10))
    assert spec.scale("GAD7").columns == tuple(f"GAD7[GADQ{i}]" for i in range(1, 8))
    assert len(spec.scale("RES").columns) == 10
    assert len(spec.scale("STIG").columns) == 5
    assert spec.scale("STIG").scoring is Scoring.ITEMS
    assert spec.scale("PHQ9").scoring is Scoring.SUM


def test_scale_ranges(spec: QuestionnaireSpec) -> None:
    ranges = {s.name: (s.min_value, s.max_value) for s in spec.scales}
    assert ranges["PHQ9"] == (0, 3)
    assert ranges["GAD7"] == (0, 3)
    assert ranges["SBI"] == (0, 5)
    assert ranges["RES"] == (0, 4)


def test_sbi_subscales_partition_the_total(spec: QuestionnaireSpec) -> None:
    sbi = spec.scale("SBI")
    exhaustion = sbi.subscale("EXHAUSTION").columns
    cynicism = sbi.subscale("CYNICISM").columns
    assert (len(exhaustion), len(cynicism), len(sbi.columns)) == (4, 5, 9)
    assert set(exhaustion) | set(cynicism) == set(sbi.columns)
    assert not set(exhaustion) & set(cynicism)


def test_unknown_scale_and_subscale(spec: QuestionnaireSpec) -> None:
    with pytest.raises(KeyError, match="NOPE"):
        spec.scale("NOPE")
    with pytest.raises(KeyError, match="NOPE"):
        spec.scale("SBI").subscale("NOPE")


def test_question_lookup(spec: QuestionnaireSpec) -> None:
    sex = spec.question("DQSEX")
    assert sex.kind is QuestionKind.SINGLE_CHOICE
    assert sex.codes == ("M", "W", "D")

    item = spec.question("PHQ9[PHQQ9]")
    assert item.kind is QuestionKind.NUMERIC
    assert item.scale == "PHQ9"
    assert (item.min_value, item.max_value) == (0, 3)

    with pytest.raises(KeyError, match="NOPE"):
        spec.question("NOPE")


def test_multi_select_options_are_grouped_by_question(spec: QuestionnaireSpec) -> None:
    assert spec.multi_select_groups == ("DIAGQ1", "DIAGQ2", "DIAGQ3")
    options = spec.multi_select_options("DIAGQ3")
    codes = {q.code for q in options}
    assert {"DIAGQ3[NOT]", "DIAGQ3[MEDI]", "DIAGQ3[THER]"} <= codes
    assert all(q.group == "DIAGQ3" and q.selected == "Y" for q in options)
    assert all(not c.startswith(("DIAGQ1", "DIAGQ2")) for c in codes)
    with pytest.raises(KeyError, match="NOPE"):
        spec.multi_select_options("NOPE")


def test_metadata_and_free_text_columns(spec: QuestionnaireSpec) -> None:
    assert set(spec.metadata_columns) == {
        "id",
        "submitdate",
        "lastpage",
        "startlanguage",
        "seed",
        "startdate",
        "datestamp",
    }
    assert "DIAGQ1[other]" in spec.free_text_columns
    assert not set(spec.metadata_columns) & set(spec.columns)
    assert not set(spec.free_text_columns) & set(spec.columns)


def test_column_sets_are_consistent(spec: QuestionnaireSpec) -> None:
    all_columns = set(spec.known_columns)
    assert len(spec.known_columns) == len(all_columns)
    assert all_columns == (
        set(spec.columns) | set(spec.metadata_columns) | set(spec.free_text_columns)
    )
    assert set(spec.required_columns) <= all_columns
    assert spec.question("ANGE2").required is False
    assert spec.question("DIAGQ3[STAT]").required is False


def test_every_scale_column_is_a_known_question(spec: QuestionnaireSpec) -> None:
    for scale in spec.scales:
        for column in scale.columns:
            assert spec.question(column).scale == scale.name


# --- loader on snippets --------------------------------------------------------------


def test_minimal_snippet_loads() -> None:
    spec = spec_from_mapping(minimal())
    assert spec.columns == (
        "Q1",
        "N1",
        "MS[ONE]",
        "MS[TWO]",
        "MS[THREE]",
        "S[A]",
        "S[B]",
        "S[C]",
    )
    assert spec.question("MS[THREE]").required is False
    assert spec.question("MS[other]").kind is QuestionKind.FREE_TEXT


Edit = tuple[str, tuple[str | int, ...], Any]


def _edited(*edits: Edit) -> dict[str, Any]:
    """The minimal spec with edits applied: ("set" | "append" | "drop", path, value)."""
    data = minimal()
    for action, path, value in edits:
        parent: Any = data
        for step in path[:-1]:
            parent = parent[step]
        if action == "set":
            parent[path[-1]] = value
        elif action == "append":
            parent[path[-1]].append(value)
        else:
            del parent[path[-1]]
    return data


MALFORMED: list[tuple[Edit, str]] = [
    (("set", ("extra",), 1), "unknown keys"),
    (("set", ("single_choice", "Q1", "extra"), 1), "unknown keys"),
    (("set", ("scales", "S", "extra"), 1), "unknown keys"),
    (("set", ("multi_select", "MS", "extra"), 1), "unknown keys"),
    (("set", ("free_text", 0, "extra"), 1), "unknown keys"),
    (("drop", ("version",), None), "version"),
    (("set", ("version",), 2026.1), "version"),
    (("set", ("response_id",), "Q1"), "not a metadata column"),
    (("set", ("response_id",), "missing"), "not a metadata column"),
    (("append", ("metadata",), "Q1"), "Duplicate column code: Q1"),
    (("set", ("numeric", "Q1"), {"min": 0, "max": 1}), "Duplicate column code: Q1"),
    (("append", ("free_text",), {"code": "N1"}), "Duplicate column code: N1"),
    (("append", ("multi_select", "MS", "options"), "ONE"), "Duplicate column code"),
    (("append", ("scales", "S", "columns"), "N1"), "Duplicate column code: N1"),
    (("append", ("scales", "S", "columns"), "S[A]"), "Duplicate column code: S[A]"),
    (("append", ("scales", "S", "subscales", "LOW"), "N1"), "outside"),
    (("set", ("scales", "S", "scoring"), "mean"), "scoring"),
    (("set", ("scales", "S", "range"), [3, 0]), "above maximum"),
    (("set", ("scales", "S", "range"), [0]), "range"),
    (("set", ("scales", "S", "columns"), []), "no columns"),
    (("set", ("numeric", "N1"), {"min": 1.5, "max": 5}), "integers"),
    (("set", ("numeric", "N1"), {"min": 1}), "integers"),
    (("set", ("single_choice", "Q1", "codes"), []), "must not be empty"),
    (("set", ("single_choice", "Q1", "codes"), ["A", "A"]), "duplicate codes"),
    (("set", ("single_choice", "Q1", "codes"), [True, False]), "string"),
    (("set", ("multi_select", "MS", "selected"), True), "selected"),
    (("set", ("single_choice", "Q1", "required"), "yes"), "true or false"),
    (("set", ("free_text",), {}), "list"),
    (("set", ("metadata",), "id"), "list"),
]


@pytest.mark.parametrize(("edit", "message"), MALFORMED)
def test_malformed_snippets_are_rejected(edit: Edit, message: str) -> None:
    with pytest.raises(SpecError, match=re.escape(message)):
        spec_from_mapping(_edited(edit))


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(SpecError, match="mapping"):
        spec_from_mapping(["not", "a", "mapping"])


def test_duplicate_scale_is_rejected() -> None:
    columns = ("A", "B")
    scale = Scale("S", Scoring.SUM, 0, 1, columns)
    questions = tuple(Question(c, QuestionKind.NUMERIC) for c in ("id", *columns))
    questions = (Question("id", QuestionKind.METADATA), *questions[1:])
    with pytest.raises(SpecError, match="Duplicate scale"):
        QuestionnaireSpec("t", "id", questions, (scale, scale))


def test_scale_with_unknown_columns_is_rejected() -> None:
    scale = Scale("S", Scoring.SUM, 0, 1, ("A", "MISSING"))
    questions = (
        Question("id", QuestionKind.METADATA),
        Question("A", QuestionKind.NUMERIC),
    )
    with pytest.raises(SpecError, match=r"unknown columns: \['MISSING'\]"):
        QuestionnaireSpec("t", "id", questions, (scale,))
