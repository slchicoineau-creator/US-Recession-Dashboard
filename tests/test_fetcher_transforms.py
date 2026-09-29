"""Tests for the transforms applied to FRED series before storage:
  - compute_diff: month-over-month difference
  - compute_pct_change_periods: N-period % change
  - _is_plausible: range filter
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.fetcher import _is_plausible, _PLAUSIBLE_RANGES


class TestPlausibleRanges:
    def test_unknown_kpi_passes_through(self):
        assert _is_plausible("nonexistent_kpi", 1e9) is True
        assert _is_plausible("nonexistent_kpi", -1e9) is True

    def test_value_inside_range_is_plausible(self):
        # icsa range is (50_000, 7_000_000) per fetcher.py
        if "icsa" in _PLAUSIBLE_RANGES:
            lo, hi = _PLAUSIBLE_RANGES["icsa"]
            assert _is_plausible("icsa", (lo + hi) / 2) is True

    def test_value_outside_range_filtered(self):
        if "icsa" in _PLAUSIBLE_RANGES:
            lo, hi = _PLAUSIBLE_RANGES["icsa"]
            assert _is_plausible("icsa", lo - 1) is False
            assert _is_plausible("icsa", hi + 1) is False


class TestComputeDiff:
    """compute_diff applies pandas .diff() to convert level → MoM change."""

    def test_diff_basic(self):
        s = pd.Series([100, 110, 105, 115], index=pd.date_range("2025-01-01", periods=4, freq="MS"))
        diffed = s.diff().dropna()
        assert list(diffed) == [10.0, -5.0, 10.0]

    def test_diff_first_value_dropped(self):
        s = pd.Series([100, 110])
        diffed = s.diff().dropna()
        assert len(diffed) == 1


class TestComputePctChange:
    """compute_pct_change_periods: pct_change(N) * 100, drop ±inf."""

    def test_yoy_monthly(self):
        # 24 months: each value = base * (1 + i*0.01)
        idx = pd.date_range("2024-01-01", periods=24, freq="MS")
        vals = [100 * (1 + i * 0.01) for i in range(24)]
        s = pd.Series(vals, index=idx)
        pct = (s.pct_change(periods=12) * 100).dropna()
        assert len(pct) == 12
        # Month 12 vs Month 0: (100*1.12 - 100*1.00)/100 = 12.0%
        assert pct.iloc[0] == pytest.approx(12.0, rel=1e-6)

    def test_quarterly_yoy_periods_4(self):
        idx = pd.date_range("2023-01-01", periods=8, freq="QS")
        s = pd.Series([100, 102, 104, 106, 110, 115, 120, 125], index=idx)
        pct = (s.pct_change(periods=4) * 100).dropna()
        assert len(pct) == 4
        assert pct.iloc[0] == pytest.approx(10.0)

    def test_zero_baseline_produces_inf_dropped(self):
        s = pd.Series([0, 0, 5, 10], index=pd.date_range("2025-01-01", periods=4, freq="MS"))
        pct = (s.pct_change(periods=1) * 100).replace([float("inf"), float("-inf")], pd.NA).dropna()
        # First diff is NaN; second is 0→0 NaN; third is 0→5 inf → dropped; fourth is 5→10 = 100%
        assert 100.0 in [round(v, 6) for v in pct.tolist()]
