"""Association metrics: symptom category by diagnosis and treatment status and level.

The report cross-tabulates the combined symptom load (PHQ-9 and GAD-7) with whether a
respondent reports a diagnosis and whether a diagnosed respondent is in treatment,
for all respondents and for each school level. Everything is read from the feature
table (architecture section 6.5): ``symptom_category``, ``diagnosis`` and
``treatment_any``; the school level comes from ``DQSTUFE`` in the responses and its
codes from the questionnaire spec.

Symptom category
----------------
``symptom_category`` is derived in :mod:`spot_report.features` from the two sums, in
three-valued logic (decision D12: a missing score is never replaced by a value):

* ``severe``: PHQ-9 or GAD-7 at or above 10, even if the other score is missing
  (this is exactly ``burdened``);
* ``medium``: both scores present, both below 10, at least one at or above 5;
* ``mildnone``: both scores present and both below 5;
* ``NA`` otherwise (a present score below 10 and a missing score, or both missing),
  because the missing score could be 10 or more. Such a respondent is counted in no
  category.

This is the same reading as for ``burdened``; the previous program put every
respondent with at least one valid score into a category. ``medium`` is the previous
program's ``moderate`` (the 5-9 band), renamed so that it cannot be mistaken for the
PHQ-9/GAD-7 band ``moderate`` (ADR 0004); its legacy keys keep the old name.

Diagnosis status
----------------
A partition of the respondents by ``DIAGQ0`` and the feature ``treatment_any``:

* ``diagnosed_treated``: diagnosis reported and at least one treatment option ticked;
* ``diagnosed_untreated``: diagnosis reported and no treatment option ticked;
* ``not_diagnosed``: no diagnosis reported.

An empty ``DIAGQ0`` (D12: not shown) belongs to none of them and is counted in
``n_missing``. The previous program's counts follow from the partition:
``known_diag`` = ``diagnosed_treated`` + ``diagnosed_untreated``, ``treated`` =
``diagnosed_treated``, ``unknown_diag`` = ``not_diagnosed`` (the previous program's
three columns overlapped; ``treated`` is a part of ``known_diag``).

Populations
-----------
* ``association.symptoms.category``: every respondent; those whose category is
  undetermined are ``n_missing``. This is where they are visible.
* Per category and status: the respondents in that category (and, for the level
  metrics, in that level). Respondents of other categories or levels are not part of
  the group and not counted as missing (the convention of the diagnosis metrics). Of
  the group, those with an empty ``DIAGQ0`` are ``n_missing``. A respondent with an
  empty ``DQSTUFE`` is in no level subgroup (see ``demography.level.distribution``).
* Every subgroup is computed whatever its size; suppression is the presentation's job.

The overlap counts of the previous program are rows of these metrics (symptoms
``burdened`` is the category ``severe``): symptoms and diagnosis = ``severe`` known
(treated + untreated), symptoms and diagnosis and treated = ``severe`` treated,
symptoms without diagnosis = ``severe`` not diagnosed, moderate without diagnosis =
``medium`` not diagnosed.

Metric ids (a stored contract)
------------------------------
In the ids ``<category>`` is ``mildnone``, ``medium`` or ``severe`` and ``<level>``
the code of a ``DQSTUFE`` answer of the spec in lowercase (for 2026.1: ``gym1`` to
``gym4``).

``association.symptoms.category``
    ``Distribution`` of the symptom category over all respondents, categories
    ``mildnone medium severe``.
``association.<category>.diagnosis_status``
    ``Distribution`` of the diagnosis status among the respondents of the category,
    categories ``diagnosed_treated diagnosed_untreated not_diagnosed``.
``association.<category>.diagnosis_status.<level>``
    The same among the respondents of the category who are in the school level.

Shares are derived by the presentation stage. Nothing is suppressed here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from spot_report.features import (
    DIAGNOSIS_QUESTION,
    GAD7_SCALE,
    PHQ9_SCALE,
    SYMPTOM_CATEGORIES,
    TREATMENT_QUESTION,
)
from spot_report.metrics.demography import LEVEL_COLUMN
from spot_report.metrics.registry import MetricDefinition
from spot_report.metrics.types import Distribution, Metric, MetricSet

if TYPE_CHECKING:
    from spot_report.questionnaire import QuestionnaireSpec

__all__ = [
    "STATUS_CATEGORIES",
    "category_id",
    "compute",
    "definitions",
    "level_id",
]

DOMAIN = "association"
SINCE = "2026.1"

CATEGORY_ID = "association.symptoms.category"

#: Diagnosis status, a partition of the respondents with a known ``DIAGQ0``. Stored as
#: ``Distribution`` categories; never rename them.
DIAGNOSED_TREATED = "diagnosed_treated"
DIAGNOSED_UNTREATED = "diagnosed_untreated"
NOT_DIAGNOSED = "not_diagnosed"
STATUS_CATEGORIES: tuple[str, ...] = (
    DIAGNOSED_TREATED,
    DIAGNOSED_UNTREATED,
    NOT_DIAGNOSED,
)


def category_id(category: str) -> str:
    """Id of the status distribution of a symptom category, all levels."""
    return f"{DOMAIN}.{category}.diagnosis_status"


def level_id(category: str, level: str) -> str:
    """Id of the status distribution of a symptom category in one school level."""
    return f"{category_id(category)}.{level.lower()}"


def definitions(spec: QuestionnaireSpec) -> tuple[MetricDefinition, ...]:
    """The metric definitions of this domain for the levels and options of ``spec``."""
    scores = (*spec.scale(PHQ9_SCALE).columns, *spec.scale(GAD7_SCALE).columns)
    treatment = tuple(
        q.code
        for q in spec.multi_select_options(TREATMENT_QUESTION)
        if not q.none_option
    )
    status_items = (*scores, DIAGNOSIS_QUESTION, *treatment)
    levels = spec.question(LEVEL_COLUMN).codes

    def definition(metric_id: str, *items: str) -> MetricDefinition:
        return MetricDefinition(metric_id, "distribution", DOMAIN, items, SINCE)

    return (
        definition(CATEGORY_ID, *scores),
        *(
            definition(category_id(category), *status_items)
            for category in SYMPTOM_CATEGORIES
        ),
        *(
            definition(level_id(category, level), *status_items, LEVEL_COLUMN)
            for category in SYMPTOM_CATEGORIES
            for level in levels
        ),
    )


def compute(
    responses: pd.DataFrame,
    features: pd.DataFrame,
    spec: QuestionnaireSpec,
) -> MetricSet:
    """The association metrics of one wave; see the module docstring for the ids."""
    category = features["symptom_category"].astype(object)
    status = _diagnosis_status(features)
    level = responses[LEVEL_COLUMN]

    metrics: dict[str, Metric] = {
        CATEGORY_ID: _distribution(category, SYMPTOM_CATEGORIES)
    }
    for name in SYMPTOM_CATEGORIES:
        in_category = category.eq(name).fillna(False).astype(bool)
        metrics[category_id(name)] = _distribution(
            status[in_category], STATUS_CATEGORIES
        )
        for code in spec.question(LEVEL_COLUMN).codes:
            in_level = in_category & level.eq(code).fillna(False).astype(bool)
            metrics[level_id(name, code)] = _distribution(
                status[in_level], STATUS_CATEGORIES
            )
    return MetricSet(metrics)


def _diagnosis_status(features: pd.DataFrame) -> pd.Series:
    """Diagnosis status per respondent as text; ``NA`` where ``DIAGQ0`` is empty."""
    diagnosis = features["diagnosis"]
    treated = features["treatment_any"].fillna(False).astype(bool)
    diagnosed = diagnosis.fillna(False).astype(bool)
    status = pd.Series(pd.NA, index=features.index, dtype=object)
    status[diagnosis.notna()] = NOT_DIAGNOSED
    status[diagnosed] = DIAGNOSED_UNTREATED
    status[diagnosed & treated] = DIAGNOSED_TREATED
    return status


def _distribution(values: pd.Series, categories: tuple[str, ...]) -> Distribution:
    """Counts of the respondents with a value; the ``NA`` ones are ``n_missing``."""
    known = values.notna()
    return Distribution.from_values(
        values[known], categories, n_missing=int((~known).sum())
    )
