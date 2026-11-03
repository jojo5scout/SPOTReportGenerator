"""Burnout metrics (School Burnout Inventory, SBI): a summary per subscale and total.

Everything is read from the feature table (architecture section 6.5): the per-person
sums ``sbi_<subscale>_sum`` of every subscale in the questionnaire spec (subscale name
in lowercase) and ``sbi_total_sum`` over all items of the scale. The subscales and
their items are those of the spec; no subscale name or column code is hard-coded here.

Populations (decision D12)
--------------------------
Respondents whose sum could be computed, i.e. who answered every item of the subscale
(or of the scale for the total). The others are counted in ``n_missing``, so
``n + n_missing`` is the number of respondents. The previous program summed the answered
items of a person and only treated a person as missing when all items were empty; a
partial sum is not computed here (D12). Complete data gives identical numbers.

Statistics are those of :meth:`Summary.from_values`: mean and SD of the per-person sums,
SD with ``ddof=1`` (``None`` for a single value; the previous program showed 0.00),
quartiles linear.

The scatter plot of burnout against the ``RES`` sum in the previous report is a chart
of person-level values (architecture section 10), not a metric: the chart reads the
features ``sbi_total_sum`` and ``res_sum`` itself, nothing is computed here for it.

Metric ids (a stored contract), ``<subscale>`` = subscale name of the spec in lowercase
(for 2026.1: ``exhaustion``, ``cynicism``)
----------------------------------------------------------------------------------
``burnout.sbi.<subscale>``
    ``Summary`` of the subscale sum over the respondents who answered all its items.
``burnout.sbi.total``
    ``Summary`` of the sum over all items of the scale.

Nothing is suppressed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spot_report.features import SBI_SCALE, sbi_subscale_column
from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import Metric, MetricSet, Summary

if TYPE_CHECKING:
    import pandas as pd

    from spot_report.questionnaire import QuestionnaireSpec

__all__ = ["TOTAL_SEGMENT", "compute", "definitions", "subscale_id"]

DOMAIN = "burnout"
SINCE = "2026.1"

#: Last id segment of the total score.
TOTAL_SEGMENT = "total"


def subscale_id(subscale: str) -> str:
    """Metric id of an SBI subscale (its spec name) or of the total (``"total"``)."""
    return f"{DOMAIN}.sbi.{subscale.lower()}"


def definitions(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain for ``spec``."""
    sbi = spec.scale(SBI_SCALE)
    return (
        *(
            MetricDefinition(
                subscale_id(sub.name), "summary", DOMAIN, sub.columns, SINCE
            )
            for sub in sbi.subscales
        ),
        MetricDefinition(
            subscale_id(TOTAL_SEGMENT), "summary", DOMAIN, sbi.columns, SINCE
        ),
    )


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The burnout metrics of one wave; see the module docstring for the ids."""
    metrics: dict[str, Metric] = {
        subscale_id(sub.name): _summary(features[sbi_subscale_column(sub.name)])
        for sub in spec.scale(SBI_SCALE).subscales
    }
    metrics[subscale_id(TOTAL_SEGMENT)] = _summary(features["sbi_total_sum"])
    return MetricSet(metrics)


def _summary(sums: pd.Series) -> Summary:
    """Summary of the computed sums; the ones that could not be computed are missing."""
    computed = sums.notna()
    return Summary.from_values(sums[computed], n_missing=int((~computed).sum()))
