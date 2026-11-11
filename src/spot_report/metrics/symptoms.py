"""Symptom metrics: PHQ-9, GAD-7, their combination, PHQ-9 item 9 and impairment.

Everything is read from the feature table (architecture section 6.5): ``phq9_sum``,
``phq9_severity``, ``phq9_cutoff`` and their GAD-7 counterparts, ``burdened``,
``phq9_item9`` and ``impairment``. The diagnosis subgroups also need the tick of one
option of ``DIAGQ1`` in the responses. Severity categories come from
:mod:`spot_report.features`, the value range of item 9 and of the impairment question
from the questionnaire spec.

Populations (decision D12)
--------------------------
* *severity, cut-off*: respondents whose score could be computed (all items present).
  The others are counted in ``n_missing``, so ``n + n_missing`` is the number of
  respondents.
* *combined*: respondents for whom ``burdened`` is known. It is ``NA`` when one score is
  below its cut-off and the other score is missing, or both are missing; those are
  counted in ``n_missing``.
* *item 9, impairment*: respondents who answered the question; an empty answer is
  counted in ``n_missing``.
* *severity among respondents with a diagnosis*: respondents who ticked the depression
  option (PHQ-9) or the anxiety option (GAD-7) of ``DIAGQ1`` (an empty option is not
  ticked, D12). Of these, the ones without a score are counted in ``n_missing``;
  respondents who did not tick the option are not part of the group and are not counted
  as missing (the convention of the diagnosis metrics).

Definitions of the previous program that the architecture does not specify, kept and
confirmed in ADR 0004:

* the subgroups are defined by the ticked option alone, ``DIAGQ0`` is not consulted
  (the diagnosis types are shown only after a "yes" to ``DIAGQ0``);
* the "elevated" answers of item 9 and of the impairment question are the values at or
  above :data:`ELEVATED_FROM` (2).

The previous program's combined share used the respondents with at least one valid
score as denominator and counted a missing score as below its cut-off. With complete
data this is the same as ``burdened`` over the respondents for whom it is known.

Which options mean "depression" and "anxiety" is a fact of the questionnaire's
content. The spec only lists option codes, so the two option codes are constants below
(:data:`DEPRESSION_OPTION`, :data:`ANXIETY_OPTION`); the full column code is built from
the group and looked up in the spec, which raises if the option does not exist.

Metric ids (a stored contract)
------------------------------
``symptoms.phq9.severity``, ``symptoms.gad7.severity``
    ``Distribution`` of the severity band over the respondents with a score, categories
    ``PHQ9_SEVERITY_CATEGORIES`` / ``GAD7_SEVERITY_CATEGORIES`` of ``features``.
``symptoms.phq9.severity.depression_diagnosis``
``symptoms.gad7.severity.anxiety_diagnosis``
    The same distribution among the respondents who ticked the depression (PHQ-9) or
    anxiety (GAD-7) diagnosis option.
``symptoms.phq9.cutoff10``, ``symptoms.gad7.cutoff10``
    ``Proportion``: score at or above the cut-off 10, of the respondents with a score.
``symptoms.combined.burdened``
    ``Proportion``: PHQ-9 or GAD-7 at or above 10, of the respondents for whom this is
    known.
``symptoms.phq9_item9.distribution``
    ``Distribution`` of the answers to PHQ-9 item 9, categories ``"0"`` to ``"3"``
    (the range of the spec) of the respondents who answered it.
``symptoms.phq9_item9.cutoff2``
    ``Proportion``: item 9 at or above 2, of the respondents who answered it.
``symptoms.impairment.distribution``, ``symptoms.impairment.cutoff2``
    The same for the impairment question ``SIPHQ``.

Shares are derived by the presentation stage. Nothing is suppressed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from spot_report.features import (
    GAD7_SCALE,
    GAD7_SEVERITY_CATEGORIES,
    IMPAIRMENT_QUESTION,
    PHQ9_ITEM9_POSITION,
    PHQ9_SCALE,
    PHQ9_SEVERITY_CATEGORIES,
    option_selected,
)
from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import Distribution, Metric, MetricSet, Proportion

if TYPE_CHECKING:
    from spot_report.questionnaire import QuestionnaireSpec

__all__ = [
    "ANXIETY_OPTION",
    "DEPRESSION_OPTION",
    "ELEVATED_FROM",
    "compute",
    "definitions",
]

DOMAIN = "symptoms"
SINCE = "2026.1"

#: Multi-select question "type of diagnosis" and its depression / anxiety options.
DIAGNOSIS_TYPE_GROUP = "DIAGQ1"
DEPRESSION_OPTION = "DEPR"
ANXIETY_OPTION = "ANGS"

#: Item 9 and impairment answers at or above this value count as elevated, as in the
#: previous report (confirmed in ADR 0004).
ELEVATED_FROM = 2

PHQ9_SEVERITY_ID = "symptoms.phq9.severity"
GAD7_SEVERITY_ID = "symptoms.gad7.severity"
PHQ9_SEVERITY_DEPRESSION_ID = "symptoms.phq9.severity.depression_diagnosis"
GAD7_SEVERITY_ANXIETY_ID = "symptoms.gad7.severity.anxiety_diagnosis"
PHQ9_CUTOFF_ID = "symptoms.phq9.cutoff10"
GAD7_CUTOFF_ID = "symptoms.gad7.cutoff10"
COMBINED_ID = "symptoms.combined.burdened"
ITEM9_DISTRIBUTION_ID = "symptoms.phq9_item9.distribution"
ITEM9_ELEVATED_ID = "symptoms.phq9_item9.cutoff2"
IMPAIRMENT_DISTRIBUTION_ID = "symptoms.impairment.distribution"
IMPAIRMENT_ELEVATED_ID = "symptoms.impairment.cutoff2"


def _item9_code(spec: QuestionnaireSpec) -> str:
    return spec.scale(PHQ9_SCALE).columns[PHQ9_ITEM9_POSITION - 1]


def _diagnosis_option(spec: QuestionnaireSpec, option: str) -> str:
    return spec.question(f"{DIAGNOSIS_TYPE_GROUP}[{option}]").code


def definitions(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain for ``spec``."""
    phq9 = spec.scale(PHQ9_SCALE).columns
    gad7 = spec.scale(GAD7_SCALE).columns
    depression = _diagnosis_option(spec, DEPRESSION_OPTION)
    anxiety = _diagnosis_option(spec, ANXIETY_OPTION)

    def definition(metric_id: str, kind: str, *items: str) -> MetricDefinition:
        return MetricDefinition(metric_id, kind, DOMAIN, items, SINCE)

    item9 = _item9_code(spec)
    return (
        definition(PHQ9_SEVERITY_ID, "distribution", *phq9),
        definition(PHQ9_SEVERITY_DEPRESSION_ID, "distribution", *phq9, depression),
        definition(PHQ9_CUTOFF_ID, "proportion", *phq9),
        definition(GAD7_SEVERITY_ID, "distribution", *gad7),
        definition(GAD7_SEVERITY_ANXIETY_ID, "distribution", *gad7, anxiety),
        definition(GAD7_CUTOFF_ID, "proportion", *gad7),
        definition(COMBINED_ID, "proportion", *phq9, *gad7),
        definition(ITEM9_DISTRIBUTION_ID, "distribution", item9),
        definition(ITEM9_ELEVATED_ID, "proportion", item9),
        definition(IMPAIRMENT_DISTRIBUTION_ID, "distribution", IMPAIRMENT_QUESTION),
        definition(IMPAIRMENT_ELEVATED_ID, "proportion", IMPAIRMENT_QUESTION),
    )


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The symptom metrics of one wave; see the module docstring for the ids."""
    depression = option_selected(
        responses, spec.question(_diagnosis_option(spec, DEPRESSION_OPTION))
    ).astype(bool)
    anxiety = option_selected(
        responses, spec.question(_diagnosis_option(spec, ANXIETY_OPTION))
    ).astype(bool)
    item9_values = _answer_range(spec, _item9_code(spec))
    impairment_values = _answer_range(spec, IMPAIRMENT_QUESTION)

    metrics: dict[str, Metric] = {
        PHQ9_SEVERITY_ID: _distribution(
            features["phq9_severity"], PHQ9_SEVERITY_CATEGORIES
        ),
        PHQ9_SEVERITY_DEPRESSION_ID: _distribution(
            features["phq9_severity"][depression], PHQ9_SEVERITY_CATEGORIES
        ),
        PHQ9_CUTOFF_ID: _proportion(features["phq9_cutoff"]),
        GAD7_SEVERITY_ID: _distribution(
            features["gad7_severity"], GAD7_SEVERITY_CATEGORIES
        ),
        GAD7_SEVERITY_ANXIETY_ID: _distribution(
            features["gad7_severity"][anxiety], GAD7_SEVERITY_CATEGORIES
        ),
        GAD7_CUTOFF_ID: _proportion(features["gad7_cutoff"]),
        COMBINED_ID: _proportion(features["burdened"]),
        ITEM9_DISTRIBUTION_ID: _distribution(features["phq9_item9"], item9_values),
        ITEM9_ELEVATED_ID: _proportion(features["phq9_item9"].ge(ELEVATED_FROM)),
        IMPAIRMENT_DISTRIBUTION_ID: _distribution(
            features["impairment"], impairment_values
        ),
        IMPAIRMENT_ELEVATED_ID: _proportion(features["impairment"].ge(ELEVATED_FROM)),
    }
    return MetricSet(metrics)


def _answer_range(spec: QuestionnaireSpec, code: str) -> tuple[str, ...]:
    """The allowed answers of a numeric question as category codes, lowest first."""
    question = spec.question(code)
    assert question.min_value is not None
    assert question.max_value is not None
    return tuple(str(v) for v in range(question.min_value, question.max_value + 1))


def _distribution(values: pd.Series, categories: tuple[str, ...]) -> Distribution:
    """Counts of the respondents with a value; the ``NA`` ones are ``n_missing``."""
    known = values.notna()
    return Distribution.from_values(
        values[known], categories, n_missing=int((~known).sum())
    )


def _proportion(flags: pd.Series) -> Proportion:
    """Share of ``True`` among the respondents whose flag is known."""
    known = flags.notna()
    return Proportion.from_mask(
        flags[known].astype(bool), n_missing=int((~known).sum())
    )
