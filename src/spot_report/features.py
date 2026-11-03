"""Per-person derived features (architecture sections 4 and 6.5).

:func:`compute_features` turns the normalised responses (``ingest/readers.py``) into
one row of derived values per respondent, with the same index as the input. It is a
pure function: no I/O, no logging, no warnings, no plotting, no aggregates. All column
and answer codes come from the questionnaire spec; this module only names the scales
and questions it uses (``PHQ9``, ``DIAGQ0``, ...).

Missing values (decision D12)
-----------------------------
Empty cells are never an error, a warning or a log message. Every feature uses
nullable dtypes so that "missing" is an explicit ``NA``, never ``False`` or ``0``:

* a scale score is the sum of its items only if **all** items of that (sub)scale are
  present; otherwise it is ``NA`` for that respondent;
* a value derived from a score (severity, cut-off) is ``NA`` when the score is;
* a single-choice or numeric question that is empty was not shown: ``NA``, so the
  respondent is left out of that question's denominator;
* a multi-select option that is empty was not selected: ``False``, the respondent
  stays in the denominator.

Display conditions are not modelled: for example ``treatment_any`` is computed for
every respondent, whether or not they reported a diagnosis. Restricting a denominator
to a subgroup is a decision of the metric that uses the feature.

Feature columns (a contract for the metric domains)
---------------------------------------------------
``phq9_sum``, ``gad7_sum`` (``Int64``)
    PHQ-9 sum (0-27) and GAD-7 sum (0-21).
``phq9_severity``, ``gad7_severity`` (ordered ``category``)
    Standard severity bands of the sum, categories :data:`PHQ9_SEVERITY_CATEGORIES`
    (0-4, 5-9, 10-14, 15-19, 20-27) and :data:`GAD7_SEVERITY_CATEGORIES`
    (0-4, 5-9, 10-14, 15-21).
``phq9_cutoff``, ``gad7_cutoff`` (``boolean``)
    Sum at or above :data:`PHQ9_CUTOFF` / :data:`GAD7_CUTOFF` (10).
``burdened`` (``boolean``)
    PHQ-9 or GAD-7 at or above its cut-off, in three-valued (Kleene) logic: ``True``
    if at least one score is at or above its cut-off (even if the other is missing);
    ``False`` only if both scores are present and below their cut-offs; ``NA``
    otherwise (one score below its cut-off and the other missing, or both missing),
    because then it cannot be determined.
``symptom_category`` (ordered ``category``)
    Combined symptom load, categories :data:`SYMPTOM_CATEGORIES` ``mildnone`` <
    ``moderate`` < ``severe``, from the two sums in three-valued logic: ``severe`` if
    at least one score is at or above 10 (``burdened`` is ``True``, even if the other
    score is missing); otherwise, if both scores are present, ``moderate`` if at least
    one is at or above :data:`SYMPTOM_MODERATE_FROM` (5) and ``mildnone`` if both are
    below it; ``NA`` when ``burdened`` is ``NA``, because a missing score could be 10
    or more. (The names are those of the previous program; ``moderate`` here is the
    5-9 band, not the PHQ-9 band ``moderate``.)
``phq9_item9`` (``Int64``)
    The ninth PHQ-9 item (the ninth column of the scale in the spec), passed through.
``impairment`` (``Int64``)
    The impairment question ``SIPHQ``, passed through.
``diagnosis`` (``boolean``)
    ``DIAGQ0`` equals the spec's yes code; ``NA`` when empty.
``treatment_any`` (``boolean``, never ``NA``)
    At least one ``DIAGQ3`` option other than the spec's ``none_option`` is selected.
``res_sum`` (``Int64``)
    RES sum (0-40).
``sbi_<subscale>_sum`` (``Int64``)
    One column per SBI subscale of the spec, the subscale name in lowercase (for
    2026.1: ``sbi_exhaustion_sum``, ``sbi_cynicism_sum``).
``sbi_total_sum`` (``Int64``)
    SBI sum over all items (0-45).

Intentional differences from the previous program
-------------------------------------------------
* Sums need all items (the previous program summed with ``min_count=1``, so a single
  answered item gave a score).
* Severity is ``NA`` instead of the category ``"missing"``; the code
  ``moderately_severe`` replaces ``mod_severe``.
* Cut-offs and ``burdened`` are ``NA`` when undeterminable (the previous program used
  ``False``; it kept a separate ``any_valid_symptoms`` flag as denominator).
* ``symptom_category`` is ``NA`` unless the present scores determine it; the previous
  program put every respondent with at least one valid score into a category (a
  respondent with one score below 5 and the other missing counted as ``mildnone``).
* ``diagnosis`` compares with the spec's yes code only (the previous program accepted
  several spellings of yes) and is ``NA`` when empty (previously ``False``).
* No warnings are returned for absent columns: required columns are guaranteed by
  validation, absent optional multi-select options count as not selected.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd

from spot_report.questionnaire import Question, QuestionnaireSpec

__all__ = [
    "BOOLEAN_FEATURES",
    "CATEGORY_FEATURES",
    "GAD7_CUTOFF",
    "GAD7_SEVERITY_CATEGORIES",
    "GAD7_SEVERITY_DTYPE",
    "PHQ9_CUTOFF",
    "PHQ9_SEVERITY_CATEGORIES",
    "PHQ9_SEVERITY_DTYPE",
    "SYMPTOM_CATEGORIES",
    "SYMPTOM_CATEGORY_DTYPE",
    "SYMPTOM_MODERATE_FROM",
    "FeatureInputError",
    "any_selected",
    "compute_features",
    "feature_columns",
    "integer_features",
    "option_selected",
    "sbi_subscale_column",
    "scale_sum",
    "severity",
    "symptom_category",
    "yes_no",
]

# --- scales and questions used, by their spec names -----------------------------------

PHQ9_SCALE = "PHQ9"
GAD7_SCALE = "GAD7"
RES_SCALE = "RES"
SBI_SCALE = "SBI"
PHQ9_ITEM9_POSITION = 9  # 1-based position of the item within the PHQ-9 scale
IMPAIRMENT_QUESTION = "SIPHQ"
DIAGNOSIS_QUESTION = "DIAGQ0"
TREATMENT_QUESTION = "DIAGQ3"

# --- published scoring rules of PHQ-9 and GAD-7 ---------------------------------------

PHQ9_CUTOFF = 10
GAD7_CUTOFF = 10

#: Lowest score of the "mild" band of both scales (5-9); the lower bound of the
#: ``moderate`` symptom category.
SYMPTOM_MODERATE_FROM = 5

#: Severity bands as (category code, lowest score of the band), in ascending order.
#: The codes are stored as ``Distribution`` categories; never rename them.
PHQ9_SEVERITY_BANDS: tuple[tuple[str, int], ...] = (
    ("minimal", 0),  # 0-4
    ("mild", 5),  # 5-9
    ("moderate", 10),  # 10-14
    ("moderately_severe", 15),  # 15-19
    ("severe", 20),  # 20-27
)
GAD7_SEVERITY_BANDS: tuple[tuple[str, int], ...] = (
    ("minimal", 0),  # 0-4
    ("mild", 5),  # 5-9
    ("moderate", 10),  # 10-14
    ("severe", 15),  # 15-21
)

PHQ9_SEVERITY_CATEGORIES: tuple[str, ...] = tuple(c for c, _ in PHQ9_SEVERITY_BANDS)
GAD7_SEVERITY_CATEGORIES: tuple[str, ...] = tuple(c for c, _ in GAD7_SEVERITY_BANDS)
#: Categories of ``symptom_category``, lowest load first. Stored (metric ids and
#: ``Distribution`` categories of the association domain); never rename them.
SYMPTOM_CATEGORIES: tuple[str, ...] = ("mildnone", "moderate", "severe")
SYMPTOM_CATEGORY_DTYPE = pd.CategoricalDtype(list(SYMPTOM_CATEGORIES), ordered=True)
PHQ9_SEVERITY_DTYPE = pd.CategoricalDtype(list(PHQ9_SEVERITY_CATEGORIES), ordered=True)
GAD7_SEVERITY_DTYPE = pd.CategoricalDtype(list(GAD7_SEVERITY_CATEGORIES), ordered=True)

# --- column contract ------------------------------------------------------------------

BOOLEAN_FEATURES: tuple[str, ...] = (
    "phq9_cutoff",
    "gad7_cutoff",
    "burdened",
    "diagnosis",
    "treatment_any",
)
CATEGORY_FEATURES: tuple[str, ...] = (
    "phq9_severity",
    "gad7_severity",
    "symptom_category",
)


class FeatureInputError(ValueError):
    """The responses lack a required column or have an unexpected dtype.

    Validation (``ingest/validate.py``) rules this out; the message names the column
    code only, never a value.
    """


def sbi_subscale_column(subscale: str) -> str:
    """Feature column of an SBI subscale sum, e.g. ``sbi_exhaustion_sum``."""
    return f"sbi_{subscale.lower()}_sum"


def _sbi_subscale_columns(spec: QuestionnaireSpec) -> tuple[str, ...]:
    return tuple(sbi_subscale_column(s.name) for s in spec.scale(SBI_SCALE).subscales)


def integer_features(spec: QuestionnaireSpec) -> tuple[str, ...]:
    """The ``Int64`` feature columns for a questionnaire version."""
    return (
        "phq9_sum",
        "gad7_sum",
        "phq9_item9",
        "impairment",
        "res_sum",
        *_sbi_subscale_columns(spec),
        "sbi_total_sum",
    )


def feature_columns(spec: QuestionnaireSpec) -> tuple[str, ...]:
    """All feature columns, in the order :func:`compute_features` returns them."""
    return (
        "phq9_sum",
        "gad7_sum",
        "phq9_severity",
        "gad7_severity",
        "phq9_cutoff",
        "gad7_cutoff",
        "burdened",
        "symptom_category",
        "phq9_item9",
        "impairment",
        "diagnosis",
        "treatment_any",
        "res_sum",
        *_sbi_subscale_columns(spec),
        "sbi_total_sum",
    )


def compute_features(df: pd.DataFrame, spec: QuestionnaireSpec) -> pd.DataFrame:
    """Derive the per-person feature table from validated, normalised responses.

    ``df`` is the reader's DataFrame (numeric columns ``Int64``, codes ``string``)
    and must have passed validation. The result has the same index as ``df``, one
    row per respondent and the columns of :func:`feature_columns`; dtypes are
    described in the module docstring.
    """
    phq9 = spec.scale(PHQ9_SCALE)
    phq9_sum = scale_sum(df, phq9.columns)
    gad7_sum = scale_sum(df, spec.scale(GAD7_SCALE).columns)
    phq9_cutoff = phq9_sum.ge(PHQ9_CUTOFF)
    gad7_cutoff = gad7_sum.ge(GAD7_CUTOFF)
    # Kleene OR: True | NA is True, False | NA is NA.
    burdened = phq9_cutoff | gad7_cutoff

    sbi = spec.scale(SBI_SCALE)
    sbi_subscales = {
        sbi_subscale_column(sub.name): scale_sum(df, sub.columns)
        for sub in sbi.subscales
    }

    features = {
        "phq9_sum": phq9_sum,
        "gad7_sum": gad7_sum,
        "phq9_severity": severity(phq9_sum, PHQ9_SEVERITY_BANDS, PHQ9_SEVERITY_DTYPE),
        "gad7_severity": severity(gad7_sum, GAD7_SEVERITY_BANDS, GAD7_SEVERITY_DTYPE),
        "phq9_cutoff": phq9_cutoff,
        "gad7_cutoff": gad7_cutoff,
        "burdened": burdened,
        "symptom_category": symptom_category(phq9_sum, gad7_sum, burdened),
        "phq9_item9": _integer_column(df, phq9.columns[PHQ9_ITEM9_POSITION - 1]),
        "impairment": _integer_column(df, spec.question(IMPAIRMENT_QUESTION).code),
        "diagnosis": yes_no(df, spec, DIAGNOSIS_QUESTION),
        "treatment_any": any_selected(df, spec, TREATMENT_QUESTION),
        "res_sum": scale_sum(df, spec.scale(RES_SCALE).columns),
        **sbi_subscales,
        "sbi_total_sum": scale_sum(df, sbi.columns),
    }
    return pd.DataFrame(features, index=df.index, columns=feature_columns(spec))


# --- building blocks ------------------------------------------------------------------


def scale_sum(df: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    """Row sum of the item columns; ``NA`` unless every item is present (D12)."""
    items = pd.DataFrame(
        {code: _integer_column(df, code) for code in columns}, index=df.index
    )
    return items.sum(axis=1, skipna=False).astype(pd.Int64Dtype())


def severity(
    scores: pd.Series,
    bands: Sequence[tuple[str, int]],
    dtype: pd.CategoricalDtype,
) -> pd.Series:
    """The band each score falls into; ``NA`` where the score is ``NA``."""
    lower_bounds = [low for _, low in bands]
    buckets = pd.cut(
        scores,
        bins=[*lower_bounds, math.inf],
        right=False,
        labels=[code for code, _ in bands],
    )
    return buckets.astype(dtype)


def symptom_category(
    phq9_sum: pd.Series, gad7_sum: pd.Series, burdened: pd.Series
) -> pd.Series:
    """The symptom category of each respondent; ``NA`` where the scores do not decide.

    ``severe`` where ``burdened`` is ``True``. Where it is ``False`` both scores are
    present and below 10, so ``moderate`` (a score of 5 or more) and ``mildnone`` are
    exact. Where it is ``NA`` a missing score could still be 10 or more: ``NA``.
    """
    determined = burdened.notna()
    severe = burdened.fillna(False).astype(bool)
    raised = (
        (phq9_sum.ge(SYMPTOM_MODERATE_FROM) | gad7_sum.ge(SYMPTOM_MODERATE_FROM))
        .fillna(False)
        .astype(bool)
    )
    labels = pd.Series(pd.NA, index=burdened.index, dtype=object)
    labels[determined] = "mildnone"
    labels[determined & raised] = "moderate"
    labels[severe] = "severe"
    return labels.astype(SYMPTOM_CATEGORY_DTYPE)


def yes_no(df: pd.DataFrame, spec: QuestionnaireSpec, code: str) -> pd.Series:
    """``True`` for the yes code, ``False`` for the other code, ``NA`` if empty."""
    yes = spec.yes_code(code)
    return _string_column(df, code).eq(yes).astype(pd.BooleanDtype())


def any_selected(df: pd.DataFrame, spec: QuestionnaireSpec, group: str) -> pd.Series:
    """Whether any option of a multi-select question is selected; never ``NA``.

    The question's ``none_option`` (if the spec names one) does not count. Empty
    option cells are not selected (D12). An optional option column absent from the
    responses counts as not selected for everyone; an absent required option is an
    input error.
    """
    selected = pd.Series(False, index=df.index, dtype=pd.BooleanDtype())
    for option in spec.multi_select_options(group):
        if option.none_option:
            continue
        selected = selected | option_selected(df, option)
    return selected


def option_selected(df: pd.DataFrame, option: Question) -> pd.Series:
    """Whether one multi-select option is ticked; ``True`` or ``False``, never ``NA``.

    An empty cell is not selected (D12). An optional option column that is absent from
    the responses counts as not selected for everyone; an absent required option is an
    input error.
    """
    if option.code not in df.columns and not option.required:
        return pd.Series(False, index=df.index, dtype=pd.BooleanDtype())
    ticked = _string_column(df, option.code).eq(option.selected).fillna(False)
    return ticked.astype(pd.BooleanDtype())


# --- input access ---------------------------------------------------------------------


def _column(df: pd.DataFrame, code: str) -> pd.Series:
    if code not in df.columns:
        raise FeatureInputError(f"Column {code} is missing; validate the responses")
    return df[code]


def _integer_column(df: pd.DataFrame, code: str) -> pd.Series:
    column = _column(df, code)
    if column.dtype != pd.Int64Dtype():
        raise FeatureInputError(
            f"Column {code} is not Int64; validate the responses first"
        )
    return column


def _string_column(df: pd.DataFrame, code: str) -> pd.Series:
    column = _column(df, code)
    # The reader's string dtype keeps empty cells as pd.NA; pandas' default ``str``
    # dtype would turn them into NaN and comparisons into False.
    if not isinstance(column.dtype, pd.StringDtype) or column.dtype.na_value is not (
        pd.NA
    ):
        raise FeatureInputError(
            f"Column {code} is not a string column; validate the responses first"
        )
    return column
