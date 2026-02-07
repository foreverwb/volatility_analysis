import pytest

from core.trend import compute_linear_slope, map_slope_trend


def test_compute_linear_slope_empty_or_single_point_returns_zero():
    assert compute_linear_slope([], 5) == 0.0
    assert compute_linear_slope([1.2], 5) == 0.0


def test_compute_linear_slope_monotonic_sequences_sign_correct():
    assert compute_linear_slope([1, 2, 3, 4, 5], 5) > 0
    assert compute_linear_slope([5, 4, 3, 2, 1], 5) < 0


def test_compute_linear_slope_skip_invalid_values_safely():
    slope = compute_linear_slope([None, "bad", 1.0, 2.0, 3.0], 5)
    assert slope > 0


def test_map_slope_trend_threshold_mapping():
    cfg = {"trend_slope_up": 0.1, "trend_slope_down": 0.1}
    assert map_slope_trend(0.2, cfg) == "上行"
    assert map_slope_trend(-0.2, cfg) == "下行"
    assert map_slope_trend(0.05, cfg) == "横盘"
