"""Typed access to a questionnaire version.

A spec lists every column the survey export may contain: its code, the allowed answer
codes or numeric range, the scale it belongs to and which columns are multi-select
options. For a yes/no question it may name the code that means yes, and for a
multi-select question the option that means "none of the others"; the derived features
(``features.py``) read these instead of hard-coding answer codes. It holds codes and
scoring facts only, never item texts. Display conditions are not modelled
(architecture D12).

Specs live as YAML files in the ``specs`` folder next to this module and are loaded
with :func:`load_spec`. The structure is validated on load.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import resources
from typing import Any

import yaml

_VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*")
_SPECS_PACKAGE = "spot_report.questionnaire"
_SPECS_DIR = "specs"
_SUFFIX = ".yaml"


class SpecError(ValueError):
    """The spec is malformed or inconsistent."""


class UnknownVersionError(SpecError):
    """No spec exists for the requested questionnaire version."""


class QuestionKind(StrEnum):
    METADATA = "metadata"
    SINGLE_CHOICE = "single_choice"
    NUMERIC = "numeric"
    MULTI_SELECT_OPTION = "multi_select_option"
    FREE_TEXT = "free_text"


class Scoring(StrEnum):
    SUM = "sum"  # score is the sum of the items (computed in features.py)
    ITEMS = "items"  # items are analysed one by one, no total


@dataclass(frozen=True)
class Question:
    """One column of the survey export.

    ``codes`` holds the allowed answer codes of a single-choice column;
    ``min_value`` and ``max_value`` the inclusive integer range of a numeric column;
    ``selected`` the code that marks a ticked multi-select option (empty cell means
    not selected). ``yes_code`` is set on a single-choice question with exactly two
    codes and names the one that means yes (the other one means no). ``none_option``
    marks the multi-select option that means "none of the other options". ``group``
    names the question a column belongs to (multi-select options and their free-text
    "other" column), ``scale`` the scale a numeric item belongs to. Optional columns
    (``required=False``) may be absent from a file.
    """

    code: str
    kind: QuestionKind
    codes: tuple[str, ...] = ()
    min_value: int | None = None
    max_value: int | None = None
    selected: str | None = None
    group: str | None = None
    scale: str | None = None
    required: bool = True
    yes_code: str | None = None
    none_option: bool = False


@dataclass(frozen=True)
class Subscale:
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Scale:
    """A named set of item columns that share one integer range."""

    name: str
    scoring: Scoring
    min_value: int
    max_value: int
    columns: tuple[str, ...]
    subscales: tuple[Subscale, ...] = ()

    def subscale(self, name: str) -> Subscale:
        for subscale in self.subscales:
            if subscale.name == name:
                return subscale
        raise KeyError(f"Scale {self.name} has no subscale {name}")


@dataclass(frozen=True)
class QuestionnaireSpec:
    """All columns of one questionnaire version, with typed accessors."""

    version: str
    response_id: str
    questions: tuple[Question, ...]
    scales: tuple[Scale, ...]
    _by_code: Mapping[str, Question] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_code: dict[str, Question] = {}
        for question in self.questions:
            if question.code in by_code:
                raise SpecError(f"Duplicate column code: {question.code}")
            by_code[question.code] = question
        object.__setattr__(self, "_by_code", by_code)

        response_id = by_code.get(self.response_id)
        if response_id is None or response_id.kind is not QuestionKind.METADATA:
            raise SpecError(f"Response id {self.response_id} is not a metadata column")

        scale_names: set[str] = set()
        for scale in self.scales:
            if scale.name in scale_names:
                raise SpecError(f"Duplicate scale: {scale.name}")
            scale_names.add(scale.name)
            self._check_scale(scale)

    def _check_scale(self, scale: Scale) -> None:
        if not scale.columns:
            raise SpecError(f"Scale {scale.name} has no columns")
        if len(set(scale.columns)) != len(scale.columns):
            raise SpecError(f"Scale {scale.name} lists a column twice")
        unknown = [c for c in scale.columns if c not in self._by_code]
        if unknown:
            raise SpecError(f"Scale {scale.name} refers to unknown columns: {unknown}")
        for subscale in scale.subscales:
            outside = [c for c in subscale.columns if c not in scale.columns]
            if outside:
                raise SpecError(
                    f"Subscale {scale.name}.{subscale.name} has columns outside "
                    f"the scale: {outside}"
                )

    # --- lookups -----------------------------------------------------------------

    def question(self, code: str) -> Question:
        try:
            return self._by_code[code]
        except KeyError:
            raise KeyError(f"Unknown column code: {code}") from None

    def scale(self, name: str) -> Scale:
        for scale in self.scales:
            if scale.name == name:
                return scale
        raise KeyError(f"Unknown scale: {name}")

    def yes_code(self, code: str) -> str:
        """The answer code that means yes in the yes/no question ``code``."""
        question = self.question(code)
        if question.yes_code is None:
            raise KeyError(f"Column {code} is not a yes/no question")
        return question.yes_code

    def other_text(self, group: str) -> Question | None:
        """The free-text "other" column of a multi-select question, if it has one."""
        columns = [
            q
            for q in self.questions
            if q.kind is QuestionKind.FREE_TEXT and q.group == group
        ]
        if len(columns) > 1:
            raise KeyError(f"Multi-select question {group} has several text columns")
        return columns[0] if columns else None

    def multi_select_options(self, group: str) -> tuple[Question, ...]:
        """The option columns of a multi-select question, in spec order."""
        options = tuple(
            q
            for q in self.questions
            if q.kind is QuestionKind.MULTI_SELECT_OPTION and q.group == group
        )
        if not options:
            raise KeyError(f"Unknown multi-select question: {group}")
        return options

    # --- column sets, all in spec order --------------------------------------------

    def _codes(self, *kinds: QuestionKind) -> tuple[str, ...]:
        return tuple(q.code for q in self.questions if q.kind in kinds)

    @property
    def columns(self) -> tuple[str, ...]:
        """Expected item columns: everything except metadata and free text."""
        return self._codes(
            QuestionKind.SINGLE_CHOICE,
            QuestionKind.NUMERIC,
            QuestionKind.MULTI_SELECT_OPTION,
        )

    @property
    def metadata_columns(self) -> tuple[str, ...]:
        return self._codes(QuestionKind.METADATA)

    @property
    def free_text_columns(self) -> tuple[str, ...]:
        return self._codes(QuestionKind.FREE_TEXT)

    @property
    def known_columns(self) -> tuple[str, ...]:
        """Every column the spec knows, whatever its kind."""
        return tuple(q.code for q in self.questions)

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(q.code for q in self.questions if q.required)

    @property
    def multi_select_groups(self) -> tuple[str, ...]:
        groups = dict.fromkeys(
            q.group
            for q in self.questions
            if q.kind is QuestionKind.MULTI_SELECT_OPTION and q.group
        )
        return tuple(groups)


# --- loading -----------------------------------------------------------------------


def available_versions() -> tuple[str, ...]:
    """Versions for which a spec file ships with the package."""
    folder = resources.files(_SPECS_PACKAGE) / _SPECS_DIR
    names = (p.name for p in folder.iterdir() if p.name.endswith(_SUFFIX))
    return tuple(sorted(n.removesuffix(_SUFFIX) for n in names))


def load_spec(version: str) -> QuestionnaireSpec:
    """Load and validate the spec of a questionnaire version, e.g. ``"2026.1"``."""
    known = available_versions()
    if not _VERSION_PATTERN.fullmatch(version) or version not in known:
        raise UnknownVersionError(
            f"Unknown questionnaire version {version!r}; available: {list(known)}"
        )
    path = resources.files(_SPECS_PACKAGE) / _SPECS_DIR / f"{version}{_SUFFIX}"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"Spec {version} is not valid YAML") from exc
    spec = spec_from_mapping(data)
    if spec.version != version:
        raise SpecError(f"Spec file {version} declares version {spec.version}")
    return spec


def spec_from_mapping(data: object) -> QuestionnaireSpec:
    """Build a spec from parsed YAML, validating structure and values."""
    top = _mapping(
        data, "spec", allowed={"version", "response_id", "metadata"} | _SECTIONS
    )
    questions: list[Question] = []

    metadata = _string_list(top.get("metadata"), "metadata")
    questions.extend(Question(code, QuestionKind.METADATA) for code in metadata)

    for code, body in _mapping(top.get("single_choice", {}), "single_choice").items():
        where = f"single_choice.{code}"
        fields = _mapping(body, where, allowed={"codes", "required", "yes_code"})
        codes = _codes(fields.get("codes"), f"{where}.codes")
        questions.append(
            Question(
                _str(code, where),
                QuestionKind.SINGLE_CHOICE,
                codes=codes,
                required=_bool(fields.get("required", True), f"{where}.required"),
                yes_code=_yes_code(fields.get("yes_code"), codes, f"{where}.yes_code"),
            )
        )

    for code, body in _mapping(top.get("numeric", {}), "numeric").items():
        where = f"numeric.{code}"
        fields = _mapping(body, where, allowed={"min", "max", "required"})
        low, high = _int_range(fields.get("min"), fields.get("max"), where)
        questions.append(
            Question(
                _str(code, where),
                QuestionKind.NUMERIC,
                min_value=low,
                max_value=high,
                required=_bool(fields.get("required", True), f"{where}.required"),
            )
        )

    questions.extend(_multi_select(top.get("multi_select", {})))
    questions.extend(_free_text(top.get("free_text", [])))

    scales: list[Scale] = []
    for name, body in _mapping(top.get("scales", {}), "scales").items():
        scale = _scale(_str(name, "scales"), body)
        scales.append(scale)
        questions.extend(
            Question(
                column,
                QuestionKind.NUMERIC,
                min_value=scale.min_value,
                max_value=scale.max_value,
                scale=scale.name,
            )
            for column in scale.columns
        )

    return QuestionnaireSpec(
        version=_str(top.get("version"), "version"),
        response_id=_str(top.get("response_id"), "response_id"),
        questions=tuple(questions),
        scales=tuple(scales),
    )


_SECTIONS = {"single_choice", "numeric", "multi_select", "free_text", "scales"}


def _multi_select(raw: object) -> list[Question]:
    questions: list[Question] = []
    for group, body in _mapping(raw, "multi_select").items():
        where = f"multi_select.{group}"
        fields = _mapping(
            body,
            where,
            allowed={"selected", "options", "optional_options", "none_option"},
        )
        selected = _str(fields.get("selected"), f"{where}.selected")
        required = _string_list(fields.get("options"), f"{where}.options")
        optional = _string_list(
            fields.get("optional_options", []), f"{where}.optional_options"
        )
        none_option = fields.get("none_option")
        if none_option is not None and (
            _str(none_option, f"{where}.none_option") not in (*required, *optional)
        ):
            raise SpecError(f"{where}.none_option must be one of the options")
        questions.extend(
            Question(
                f"{group}[{option}]",
                QuestionKind.MULTI_SELECT_OPTION,
                selected=selected,
                group=_str(group, where),
                required=is_required,
                none_option=option == none_option,
            )
            for options, is_required in ((required, True), (optional, False))
            for option in options
        )
    return questions


def _free_text(raw: object) -> list[Question]:
    if not isinstance(raw, list):
        raise SpecError("free_text must be a list")
    questions = []
    for index, entry in enumerate(raw):
        where = f"free_text[{index}]"
        fields = _mapping(entry, where, allowed={"code", "group", "required"})
        group = fields.get("group")
        questions.append(
            Question(
                _str(fields.get("code"), f"{where}.code"),
                QuestionKind.FREE_TEXT,
                group=None if group is None else _str(group, f"{where}.group"),
                required=_bool(fields.get("required", True), f"{where}.required"),
            )
        )
    return questions


def _scale(name: str, raw: object) -> Scale:
    where = f"scales.{name}"
    fields = _mapping(raw, where, allowed={"scoring", "range", "columns", "subscales"})
    try:
        scoring = Scoring(fields.get("scoring"))
    except ValueError:
        raise SpecError(
            f"{where}.scoring must be one of {[s.value for s in Scoring]}"
        ) from None
    bounds = fields.get("range")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise SpecError(f"{where}.range must be a list [min, max]")
    low, high = _int_range(bounds[0], bounds[1], where)
    subscales = tuple(
        Subscale(
            _str(sub_name, f"{where}.subscales"),
            tuple(_string_list(columns, f"{where}.subscales.{sub_name}")),
        )
        for sub_name, columns in _mapping(
            fields.get("subscales", {}), f"{where}.subscales"
        ).items()
    )
    return Scale(
        name=name,
        scoring=scoring,
        min_value=low,
        max_value=high,
        columns=tuple(_string_list(fields.get("columns"), f"{where}.columns")),
        subscales=subscales,
    )


# --- small validators --------------------------------------------------------------


def _mapping(
    value: object, where: str, allowed: Iterable[str] | None = None
) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"{where} must be a mapping")
    if allowed is not None:
        unknown = sorted(str(k) for k in value if k not in set(allowed))
        if unknown:
            raise SpecError(f"{where} has unknown keys: {unknown}")
    return value


def _str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise SpecError(f"{where} must be a non-empty string")
    return value


def _bool(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise SpecError(f"{where} must be true or false")
    return value


def _string_list(value: object, where: str) -> list[str]:
    if not isinstance(value, list):
        raise SpecError(f"{where} must be a list")
    return [_str(item, f"{where} item") for item in value]


def _codes(value: object, where: str) -> tuple[str, ...]:
    codes = _string_list(value, where)
    if not codes:
        raise SpecError(f"{where} must not be empty")
    if len(set(codes)) != len(codes):
        raise SpecError(f"{where} has duplicate codes")
    return tuple(codes)


def _yes_code(value: object, codes: tuple[str, ...], where: str) -> str | None:
    if value is None:
        return None
    yes = _str(value, where)
    if len(codes) != 2 or yes not in codes:
        raise SpecError(f"{where} must be one of exactly two codes")
    return yes


def _int_range(low: object, high: object, where: str) -> tuple[int, int]:
    for bound in (low, high):
        if isinstance(bound, bool) or not isinstance(bound, int):
            raise SpecError(f"{where}: range bounds must be integers")
    assert isinstance(low, int)
    assert isinstance(high, int)
    if low > high:
        raise SpecError(f"{where}: range minimum is above maximum")
    return low, high
