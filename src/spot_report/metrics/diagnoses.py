"""Diagnosis, help-source and treatment metrics.

Questions used: ``DIAGQ0`` (diagnosis yes/no, as the feature ``diagnosis``) and the
multi-select questions ``DIAGQ1`` (type of diagnosis), ``DIAGQ2`` (help sources) and
``DIAGQ3`` (treatment). Option codes, the "nobody" option of ``DIAGQ2`` and the
selected marker come from the questionnaire spec. Free-text columns are never read
(D14); the ``OTHER`` option of ``DIAGQ1`` and ``DIAGQ3`` is a ticked option of the spec
and is counted like any other option.

Populations
-----------
The architecture does not define them, so the definitions of the previous program are
kept:

* *diagnosis reported*: respondents with an answer to ``DIAGQ0``; an empty answer is
  not shown and counted in ``n_missing`` (D12).
* *type of diagnosis*: all respondents are the denominator (``n``); a respondent counts
  for a type if they reported a diagnosis and ticked the type. An empty option is not
  selected, the respondent stays in ``n`` (D12). ``n_missing`` is 0.
* *help source, help usage, help combinations, treatment*: respondents who reported a
  diagnosis (``diagnosed``). A respondent whose ``DIAGQ0`` is empty cannot be assigned
  and is counted in ``n_missing`` (not in ``n``); respondents without a diagnosis are
  simply not part of the group. Inside the group an empty option is not selected and
  the respondent stays in ``n`` (D12).

The ticked "nobody" option of ``DIAGQ2`` overrides the other help sources, as in the
previous program: such a respondent uses no help source (usage 0, empty combination).
This also holds for the optional clinic option. The raw tick of every option, "nobody"
included, is still counted in ``diagnoses.help.<option>.diagnosed``.

Metric ids (a stored contract)
------------------------------
In the ids ``<option>`` is the option code of the spec in lowercase (for 2026.1:
``DIAGQ1`` ``depr angs esst adhs ptbs bipo psyc bord other``, ``DIAGQ2`` ``niem haus
kind schu psyo psya selb bera klin``, ``DIAGQ3`` ``not medi ther stat other``). Options
that are optional in the spec and absent from the responses count as not selected, so
the ids do not depend on the file.

``diagnoses.diagnosis.reported``
    ``Proportion``: respondents who reported a diagnosis of those who answered.
``diagnoses.type.<option>``
    ``Proportion``: diagnosis type ticked by a diagnosed respondent, of all respondents.
``diagnoses.help.<option>.diagnosed``
    ``Proportion``: help source ticked, of the diagnosed.
``diagnoses.help_usage.sources.diagnosed``
    ``Distribution`` of the number of help sources per diagnosed respondent (the
    options of ``DIAGQ2`` except "nobody"), categories ``0 1 2 3 4plus``.
``diagnoses.help_patterns.combinations.diagnosed``
    ``PatternCounts``: respondents per exact combination of help sources (options of
    ``DIAGQ2`` except "nobody", in spec order; the empty combination is stored). The
    help-source chart picks its columns from it with ``top_patterns``.
``diagnoses.treatment.<option>.diagnosed``
    ``Proportion``: treatment option ticked (``not`` included), of the diagnosed.

Shares are derived by the presentation stage. Nothing is suppressed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from spot_report.features import option_selected
from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import (
    Distribution,
    Metric,
    MetricSet,
    PatternCounts,
    Proportion,
)
from spot_report.questionnaire import Question, load_spec

if TYPE_CHECKING:
    from spot_report.questionnaire import QuestionnaireSpec

__all__ = ["DEFINITIONS", "USAGE_CATEGORIES", "compute", "definitions_for"]

DOMAIN = "diagnoses"
SINCE = "2026.1"

DIAGNOSIS_QUESTION = "DIAGQ0"
DIAGNOSIS_FEATURE = "diagnosis"
TYPE_GROUP = "DIAGQ1"
HELP_GROUP = "DIAGQ2"
TREATMENT_GROUP = "DIAGQ3"

REPORTED_ID = "diagnoses.diagnosis.reported"
USAGE_ID = "diagnoses.help_usage.sources.diagnosed"
PATTERNS_ID = "diagnoses.help_patterns.combinations.diagnosed"

#: Categories of the help-source count; "4plus" is four or more. Stored, never rename.
USAGE_CATEGORIES: tuple[str, ...] = ("0", "1", "2", "3", "4plus")
_USAGE_TOP = len(USAGE_CATEGORIES) - 1


def type_id(option: str) -> str:
    return f"diagnoses.type.{option.lower()}"


def help_id(option: str) -> str:
    return f"diagnoses.help.{option.lower()}.diagnosed"


def treatment_id(option: str) -> str:
    return f"diagnoses.treatment.{option.lower()}.diagnosed"


def option_name(group: str, question: Question) -> str:
    """The option code of a multi-select column, e.g. ``SCHU`` for ``DIAGQ2[SCHU]``."""
    return question.code.removeprefix(f"{group}[").removesuffix("]")


def definitions_for(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain for the options of ``spec``."""

    def definition(metric_id: str, kind: str, *items: str) -> MetricDefinition:
        return MetricDefinition(
            metric_id, kind, DOMAIN, (DIAGNOSIS_QUESTION, *items), SINCE
        )

    types = spec.multi_select_options(TYPE_GROUP)
    help_sources = spec.multi_select_options(HELP_GROUP)
    treatments = spec.multi_select_options(TREATMENT_GROUP)
    help_items = tuple(q.code for q in help_sources)
    return (
        MetricDefinition(
            REPORTED_ID, "proportion", DOMAIN, (DIAGNOSIS_QUESTION,), SINCE
        ),
        *(
            definition(type_id(option_name(TYPE_GROUP, q)), "proportion", q.code)
            for q in types
        ),
        *(
            definition(help_id(option_name(HELP_GROUP, q)), "proportion", q.code)
            for q in help_sources
        ),
        definition(USAGE_ID, "distribution", *help_items),
        definition(PATTERNS_ID, "pattern_counts", *help_items),
        *(
            definition(
                treatment_id(option_name(TREATMENT_GROUP, q)), "proportion", q.code
            )
            for q in treatments
        ),
    )


DEFINITIONS: tuple[MetricDefinition, ...] = definitions_for(load_spec(SINCE))


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The diagnosis, help-source and treatment metrics; see the module docstring."""
    diagnosis = features[DIAGNOSIS_FEATURE]
    answered = diagnosis.notna()
    diagnosed = diagnosis.fillna(False).astype(bool)
    left_out = int((~answered).sum())

    metrics: dict[str, Metric] = {
        REPORTED_ID: Proportion.from_mask(diagnosed[answered], n_missing=left_out),
    }

    for question in spec.multi_select_options(TYPE_GROUP):
        ticked = _ticked(responses, question)
        metrics[type_id(option_name(TYPE_GROUP, question))] = Proportion.from_mask(
            ticked & diagnosed
        )

    # Everything below is about the diagnosed respondents only.
    help_sources = spec.multi_select_options(HELP_GROUP)
    for question in help_sources:
        metrics[help_id(option_name(HELP_GROUP, question))] = _among_diagnosed(
            _ticked(responses, question), diagnosed, left_out
        )

    effective = _effective_help(responses, help_sources, diagnosed)
    usage = effective.sum(axis=1).map(lambda k: USAGE_CATEGORIES[min(k, _USAGE_TOP)])
    metrics[USAGE_ID] = Distribution.from_values(
        usage, USAGE_CATEGORIES, n_missing=left_out
    )
    metrics[PATTERNS_ID] = PatternCounts.from_selections(effective, n_missing=left_out)

    for question in spec.multi_select_options(TREATMENT_GROUP):
        metrics[treatment_id(option_name(TREATMENT_GROUP, question))] = (
            _among_diagnosed(_ticked(responses, question), diagnosed, left_out)
        )
    return MetricSet(metrics)


def _ticked(responses: pd.DataFrame, question: Question) -> pd.Series:
    """Plain boolean Series: option ticked (empty or absent column: not selected)."""
    return option_selected(responses, question).astype(bool)


def _among_diagnosed(
    ticked: pd.Series, diagnosed: pd.Series, n_missing: int
) -> Proportion:
    return Proportion.from_mask(ticked[diagnosed], n_missing=n_missing)


def _effective_help(
    responses: pd.DataFrame,
    help_sources: tuple[Question, ...],
    diagnosed: pd.Series,
) -> pd.DataFrame:
    """Help sources the diagnosed use: one boolean column per option except "nobody".

    Columns are named by option code, in spec order. The "nobody" option, if ticked,
    clears all other options of that respondent.
    """
    nobody = pd.Series(False, index=responses.index)
    chosen: dict[str, pd.Series] = {}
    for question in help_sources:
        ticked = _ticked(responses, question)
        if question.none_option:
            nobody |= ticked
        else:
            chosen[option_name(HELP_GROUP, question)] = ticked
    table = pd.DataFrame(chosen, index=responses.index).loc[diagnosed]
    table.loc[nobody[diagnosed], :] = False
    return table
