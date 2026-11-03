"""Demography metrics: gender, school level and age of the respondents.

Every metric is a :class:`~spot_report.metrics.types.Distribution` over the answer
codes of the questionnaire spec, in spec order (age: every integer of the spec range,
as text). Following decision D12, a respondent who left the question empty is not
counted in the distribution (``n``) but in ``n_missing``; ``n + n_missing`` is always
the number of respondents. There is no separate "number of respondents" metric: it is
that sum, the same for all three metrics.

Metric ids (a stored contract)
------------------------------
``demography.gender.distribution``
    ``DQSEX`` over the spec's answer codes.
``demography.level.distribution``
    ``DQSTUFE`` over the spec's answer codes.
``demography.age.distribution``
    ``DQAGE`` over the integers from the spec's minimum to its maximum, categories
    ``"12"`` ... ``"20"`` for spec 2026.1; ages without respondents count 0.

Shares and percentages are derived by the presentation stage, not stored here.
Nothing is suppressed here: the minimum group size rule lives in ``present/privacy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import Distribution, MetricError, MetricSet

if TYPE_CHECKING:
    import pandas as pd

    from spot_report.questionnaire import QuestionnaireSpec

__all__ = ["compute", "definitions"]

DOMAIN = "demography"
SINCE = "2026.1"

GENDER_COLUMN = "DQSEX"
LEVEL_COLUMN = "DQSTUFE"
AGE_COLUMN = "DQAGE"

GENDER_ID = "demography.gender.distribution"
LEVEL_ID = "demography.level.distribution"
AGE_ID = "demography.age.distribution"

_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(GENDER_ID, "distribution", DOMAIN, (GENDER_COLUMN,), SINCE),
    MetricDefinition(LEVEL_ID, "distribution", DOMAIN, (LEVEL_COLUMN,), SINCE),
    MetricDefinition(AGE_ID, "distribution", DOMAIN, (AGE_COLUMN,), SINCE),
)


def definitions(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain (the same for every spec version)."""
    return _DEFINITIONS


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The demography metrics of one wave; see the module docstring for the ids."""
    return MetricSet(
        {
            GENDER_ID: _distribution(
                responses, GENDER_COLUMN, spec.question(GENDER_COLUMN).codes
            ),
            LEVEL_ID: _distribution(
                responses, LEVEL_COLUMN, spec.question(LEVEL_COLUMN).codes
            ),
            AGE_ID: _distribution(responses, AGE_COLUMN, _age_categories(spec)),
        }
    )


def _age_categories(spec: QuestionnaireSpec) -> tuple[str, ...]:
    question = spec.question(AGE_COLUMN)
    if question.min_value is None or question.max_value is None:
        raise MetricError(f"Column {AGE_COLUMN} has no range in the questionnaire spec")
    return tuple(str(age) for age in range(question.min_value, question.max_value + 1))


def _distribution(
    responses: pd.DataFrame, column: str, categories: tuple[str, ...]
) -> Distribution:
    """Count the answers of ``column``; empty answers go to ``n_missing`` (D12)."""
    answers = responses[column]
    answered = answers.notna()
    return Distribution.from_values(
        answers[answered], categories, n_missing=int((~answered).sum())
    )
