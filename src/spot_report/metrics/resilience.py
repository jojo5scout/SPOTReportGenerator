"""Resilience metrics (``RES``): the sum score overall, by symptom load, as histogram.

Questions used: the items of the scale ``RES`` in the questionnaire spec. The per-person
sum ``res_sum`` and the flag ``burdened`` come from the feature table (architecture
section 6.5). No column code is hard-coded here.

Populations (decision D12)
--------------------------
The sum is computed only if every item was answered; the others have no sum.

* *all respondents*: respondents with a sum; the others are counted in ``n_missing``, so
  ``n + n_missing`` is the number of respondents. The previous program summed the
  answered items of a person and only treated a person as missing when all items were
  empty; a partial sum is not computed here (D12). Complete data gives identical
  numbers.
* *burdened*: respondents with ``burdened == True`` (PHQ-9 or GAD-7 at or above 10).
  Respondents with ``burdened`` ``False`` or ``NA`` are not part of the group and are
  not counted as missing. Within the group, a missing sum is counted in ``n_missing``.
* *non-burdened*: respondents with ``burdened == False``, i.e. both symptom scores
  present and below their cut-offs (ADR 0004). Respondents with ``burdened`` ``NA`` (one
  score below its cut-off and the other missing, which could be 10 or more) are in
  neither group and not counted as missing. The previous program also counted them as
  non-burdened; with complete symptom data the two definitions agree. Within the group,
  a missing sum is counted in ``n_missing``.
* *histogram*: respondents with a sum; the others are counted in ``n_missing``.

Statistics are those of :meth:`Summary.from_values`: SD with ``ddof=1`` (``None`` for a
single value; the previous program showed 0.00), quartiles linear. The reference value
and the vertical lines of the previous histogram are presentation, not metrics.

Metric ids (a stored contract)
------------------------------
``resilience.res.total``
    ``Summary`` of the sum over the respondents with a sum.
``resilience.res.total.burdened``
    The same among the burdened respondents.
``resilience.res.total.nonburdened``
    The same among the non-burdened respondents (definition above).
``resilience.res.histogram``
    ``Distribution`` of the sum over every possible score, categories ``"0"`` to the
    highest possible sum (``"40"`` for 2026.1: item count times the upper end of the
    range of the spec; the lowest is the item count times the lower end).

Nothing is suppressed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spot_report.features import RES_SCALE
from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import Distribution, Metric, MetricSet, Summary

if TYPE_CHECKING:
    import pandas as pd

    from spot_report.questionnaire import QuestionnaireSpec

__all__ = [
    "BURDENED_SUBGROUP",
    "HISTOGRAM_ID",
    "NONBURDENED_SUBGROUP",
    "TOTAL_ID",
    "compute",
    "definitions",
    "score_categories",
    "total_id",
]

DOMAIN = "resilience"
SINCE = "2026.1"

BURDENED_SUBGROUP = "burdened"
NONBURDENED_SUBGROUP = "nonburdened"
TOTAL_ID = f"{DOMAIN}.res.total"
HISTOGRAM_ID = f"{DOMAIN}.res.histogram"


def total_id(subgroup: str | None = None) -> str:
    """Metric id of the sum summary, optionally for a subgroup."""
    return TOTAL_ID if subgroup is None else f"{TOTAL_ID}.{subgroup}"


def score_categories(spec: QuestionnaireSpec) -> tuple[str, ...]:
    """Every possible sum, as text, lowest first."""
    scale = spec.scale(RES_SCALE)
    items = len(scale.columns)
    return tuple(
        str(score)
        for score in range(items * scale.min_value, items * scale.max_value + 1)
    )


def definitions(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain for ``spec``."""
    columns = spec.scale(RES_SCALE).columns
    return (
        *(
            MetricDefinition(total_id(subgroup), "summary", DOMAIN, columns, SINCE)
            for subgroup in (None, BURDENED_SUBGROUP, NONBURDENED_SUBGROUP)
        ),
        MetricDefinition(HISTOGRAM_ID, "distribution", DOMAIN, columns, SINCE),
    )


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The resilience metrics of one wave; see the module docstring for the ids."""
    sums = features["res_sum"]
    burdened = features["burdened"].fillna(False).astype(bool)
    nonburdened = (~features["burdened"]).fillna(False).astype(bool)

    computed = sums.notna()
    histogram = Distribution.from_values(
        sums[computed], score_categories(spec), n_missing=int((~computed).sum())
    )
    metrics: dict[str, Metric] = {
        total_id(): _summary(sums),
        total_id(BURDENED_SUBGROUP): _summary(sums[burdened]),
        total_id(NONBURDENED_SUBGROUP): _summary(sums[nonburdened]),
        HISTOGRAM_ID: histogram,
    }
    return MetricSet(metrics)


def _summary(sums: pd.Series) -> Summary:
    """Summary of the computed sums; the ones that could not be computed are missing."""
    computed = sums.notna()
    return Summary.from_values(sums[computed], n_missing=int((~computed).sum()))
