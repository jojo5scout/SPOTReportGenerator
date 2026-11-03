"""Plain statistics helpers shared by metric computation and the charts.

Pure functions of numbers; no I/O, no plotting, no formatting. They sit in ``metrics``
(next to the conventions of :mod:`spot_report.metrics.types`) so that the presentation
stage can import them without a layering problem: ``present`` may read ``metrics``,
never the other way round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["BOX_WHISKER_IQR_FACTOR", "box_whiskers"]

#: Whiskers reach the most extreme value within this many interquartile ranges.
BOX_WHISKER_IQR_FACTOR = 1.5


def box_whiskers(values: Sequence[float] | np.ndarray) -> tuple[float, float]:
    """Lower and upper whisker end of a box plot of ``values``.

    The box plot convention of the previous report (matplotlib, whisker factor 1.5):
    quartiles with the NumPy default (``linear``), ``iqr = q3 - q1``; the lower whisker
    is the smallest value that is at least ``q1 - 1.5 * iqr``, the upper whisker the
    largest value that is at most ``q3 + 1.5 * iqr``. Values beyond are outliers. If no
    value lies within the limits on a side, that whisker ends at the quartile.

    This is chart geometry, not a metric: the chart computes it from person-level
    values, nothing of it is stored. ``values`` must be non-empty and free of missing
    values; a missing value raises :class:`ValueError` (its count is not logged).
    """
    array = np.asarray(values, dtype="float64")
    if array.ndim != 1 or array.size == 0:
        raise ValueError("values must be a non-empty one-dimensional sequence")
    if not np.isfinite(array).all():
        raise ValueError("values must be finite (drop missing values first)")
    q1, q3 = np.quantile(array, [0.25, 0.75])
    spread = BOX_WHISKER_IQR_FACTOR * (q3 - q1)
    inside_high = array[array <= q3 + spread]
    inside_low = array[array >= q1 - spread]
    high = float(inside_high.max()) if inside_high.size else float(q3)
    low = float(inside_low.min()) if inside_low.size else float(q1)
    return min(low, float(q1)), max(high, float(q3))
