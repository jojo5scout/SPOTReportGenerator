"""Stigma metrics (``STIG``): one summary per item, for everybody and for the burdened.

Questions used: the five single-item columns of the scale ``STIG`` in the
questionnaire spec, in spec order (``item1`` to ``item5`` are the first to the fifth
column). The items are not combined into a score; each item stands for itself and is
reported by position only. The feature ``burdened`` (PHQ-9 or GAD-7 at or above 10,
architecture section 6.5) defines the subgroup.

Populations (decision D12)
--------------------------
* *all respondents*: respondents who answered the item; an empty answer counts in
  ``n_missing``, so ``n + n_missing`` is the number of respondents.
* *burdened*: respondents with ``burdened == True``. Respondents with ``burdened``
  ``NA`` (undeterminable) and the ones with ``False`` are not part of the group and are
  not counted as missing. Within the group, an empty item answer counts in
  ``n_missing``.

Statistics are those of :meth:`Summary.from_values`: SD with ``ddof=1`` (``None`` for
a single value), quartiles linear. The previous program printed the SD of a single value
as "nan"; here it is ``None``. The whiskers of the box plots are chart geometry and are
computed by the chart from person-level values with
:func:`spot_report.metrics.stats.box_whiskers`; they are not metrics.

Metric ids (a stored contract), ``N`` = 1 to 5
----------------------------------------------
``stigma.stig.itemN``
    ``Summary`` of item ``N`` over all respondents who answered it.
``stigma.stig.itemN.burdened``
    The same among the respondents with ``burdened == True``.

Nothing is suppressed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import Metric, MetricSet, Summary

if TYPE_CHECKING:
    import pandas as pd

    from spot_report.questionnaire import QuestionnaireSpec

__all__ = ["BURDENED_SUBGROUP", "compute", "definitions", "item_id"]

DOMAIN = "stigma"
SINCE = "2026.1"

#: Name of the scale in the questionnaire spec (the neutral alias of the instrument).
STIG_SCALE = "STIG"
BURDENED_SUBGROUP = "burdened"


def item_id(position: int, subgroup: str | None = None) -> str:
    """Metric id of the item at ``position`` (1-based), optionally for a subgroup."""
    base = f"{DOMAIN}.stig.item{position}"
    return base if subgroup is None else f"{base}.{subgroup}"


def definitions(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain for ``spec``."""
    columns = spec.scale(STIG_SCALE).columns
    return tuple(
        MetricDefinition(item_id(position, subgroup), "summary", DOMAIN, (code,), SINCE)
        for position, code in enumerate(columns, start=1)
        for subgroup in (None, BURDENED_SUBGROUP)
    )


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The stigma metrics of one wave; see the module docstring for the ids."""
    burdened = features["burdened"].fillna(False).astype(bool)
    metrics: dict[str, Metric] = {}
    for position, code in enumerate(spec.scale(STIG_SCALE).columns, start=1):
        metrics[item_id(position)] = _summary(responses[code])
        metrics[item_id(position, BURDENED_SUBGROUP)] = _summary(
            responses[code][burdened]
        )
    return MetricSet(metrics)


def _summary(values: pd.Series) -> Summary:
    """Summary of the answered values; the empty ones are ``n_missing``."""
    answered = values.notna()
    return Summary.from_values(values[answered], n_missing=int((~answered).sum()))
