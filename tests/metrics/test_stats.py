"""Box plot whiskers (R19): hand-made cases of the chart helper."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spot_report.metrics.stats import box_whiskers


def test_whiskers_reach_the_extremes_without_outliers() -> None:
    # q1 = 2.75, q3 = 6.25, limits -2.5 and 11.5.
    assert box_whiskers([1, 2, 3, 4, 5, 6, 7, 9]) == (1.0, 9.0)


def test_high_outlier_is_beyond_the_upper_whisker() -> None:
    # q1 = 2, q3 = 3, iqr = 1: limits 0.5 and 4.5, so 20 is an outlier.
    assert box_whiskers([1, 2, 2, 2, 3, 3, 3, 4, 20]) == (1.0, 4.0)


def test_low_outlier_is_beyond_the_lower_whisker() -> None:
    # q1 = 5, q3 = 6, limits 3.5 and 7.5, so -10 is an outlier.
    assert box_whiskers([-10, 5, 5, 5, 6, 6, 6, 7, 7]) == (5.0, 7.0)


def test_value_exactly_on_the_limit_is_inside() -> None:
    # q1 = 1, q3 = 3, iqr = 2: the upper limit is 6, and 6 is still inside.
    assert box_whiskers([1, 1, 1, 3, 3, 3, 3, 6, 9]) == (1.0, 6.0)


def test_single_and_constant_values() -> None:
    assert box_whiskers([3]) == (3.0, 3.0)
    assert box_whiskers([4, 4, 4, 4]) == (4.0, 4.0)


def test_accepts_series_and_arrays() -> None:
    values = [2, 4, 4, 5, 9]
    expected = box_whiskers(values)
    assert box_whiskers(np.array(values)) == expected
    assert box_whiskers(pd.Series(values, dtype="Int64")) == expected


def test_whiskers_enclose_the_box() -> None:
    rng = np.random.default_rng(0)
    for _ in range(200):
        values = rng.integers(0, 10, size=rng.integers(1, 30))
        low, high = box_whiskers(values)
        q1, q3 = np.quantile(values, [0.25, 0.75])
        assert values.min() <= low <= q1 <= q3 <= high <= values.max()


def test_empty_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        box_whiskers([])


def test_missing_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        box_whiskers([1.0, float("nan")])
