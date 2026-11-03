"""Absence metrics: whether students missed school and for how long.

Questions used: ``FEHLTAGQ0`` (yes/no: any absence) and ``FEHLTAGQ1`` (the follow-up
question: amount of absence, answer buckets in the order of the questionnaire spec).
The yes code of ``FEHLTAGQ0`` and the bucket codes come from the spec.

Populations (decision D12, display conditions are not modelled)
---------------------------------------------------------------
* *any absence*: respondents with an answer to ``FEHLTAGQ0``; an empty answer counts
  in ``n_missing``.
* *absence buckets*: respondents with an answer to ``FEHLTAGQ1``; an empty answer
  counts in ``n_missing`` (so ``n + n_missing`` is the number of respondents, and
  respondents who were not shown the follow-up question are among the missing).
  The population is "answered the question", not "answered yes to ``FEHLTAGQ0``".

The previous program differs in both denominators: it divided the "any absence" count
by all respondents (an empty ``FEHLTAGQ0`` counted as no) and restricted the buckets to
respondents with the yes answer, dividing by all of them (an empty ``FEHLTAGQ1`` stayed
in the denominator). On clean data (every yes answer has a bucket, no bucket without a
yes answer) the numbers are identical.

Metric ids (a stored contract)
------------------------------
``absences.absence.reported``
    ``Proportion``: respondents who reported an absence, of those who answered.
``absences.days.distribution``
    ``Distribution`` of the answers to ``FEHLTAGQ1`` over the spec's codes, in spec
    order (``FE01 FE05 FE10 FE20`` for 2026.1).

Shares are derived by the presentation stage. Nothing is suppressed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spot_report.features import yes_no
from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import Distribution, MetricSet, Proportion

if TYPE_CHECKING:
    import pandas as pd

    from spot_report.questionnaire import QuestionnaireSpec

__all__ = ["compute", "definitions"]

DOMAIN = "absences"
SINCE = "2026.1"

ANY_QUESTION = "FEHLTAGQ0"
DAYS_QUESTION = "FEHLTAGQ1"

REPORTED_ID = "absences.absence.reported"
DAYS_ID = "absences.days.distribution"

_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(REPORTED_ID, "proportion", DOMAIN, (ANY_QUESTION,), SINCE),
    MetricDefinition(DAYS_ID, "distribution", DOMAIN, (DAYS_QUESTION,), SINCE),
)


def definitions(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain (the same for every spec version)."""
    return _DEFINITIONS


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The absence metrics of one wave; see the module docstring for the ids."""
    reported = yes_no(responses, spec, ANY_QUESTION)
    answered_any = reported.notna()
    days = responses[DAYS_QUESTION]
    answered_days = days.notna()
    return MetricSet(
        {
            REPORTED_ID: Proportion.from_mask(
                reported[answered_any].astype(bool),
                n_missing=int((~answered_any).sum()),
            ),
            DAYS_ID: Distribution.from_values(
                days[answered_days],
                spec.question(DAYS_QUESTION).codes,
                n_missing=int((~answered_days).sum()),
            ),
        }
    )
