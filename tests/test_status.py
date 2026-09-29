"""Test _compute_kpi_status from app.py.

Regression test for the 'Status Display Bug Fix' documented in CLAUDE.md:
status must be computed from a direct threshold comparison, NOT from
sub_score >= 0.4 (which was the old buggy path).
"""

from __future__ import annotations

import pytest

from app import _compute_kpi_status


class TestStandardKpi:
    """invert=False (higher value = worse: unemployment, VIX, spreads)."""

    KPI = {"warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False}

    def test_below_warn_is_ok(self):
        assert _compute_kpi_status(self.KPI, 4.99) == "OK"

    def test_at_warn_is_warning(self):
        assert _compute_kpi_status(self.KPI, 5.0) == "WARNING"

    def test_between_is_warning(self):
        assert _compute_kpi_status(self.KPI, 7.5) == "WARNING"

    def test_at_danger_is_danger(self):
        assert _compute_kpi_status(self.KPI, 10.0) == "DANGER"

    def test_above_danger_is_danger(self):
        assert _compute_kpi_status(self.KPI, 99.0) == "DANGER"


class TestInvertedKpi:
    """invert=True (lower value = worse: GDP growth, sentiment, savings rate)."""

    KPI = {"warning_threshold": 14.0, "danger_threshold": 12.0, "invert": True}

    def test_above_warn_is_ok(self):
        assert _compute_kpi_status(self.KPI, 14.5) == "OK"

    def test_at_warn_is_warning(self):
        assert _compute_kpi_status(self.KPI, 14.0) == "WARNING"

    def test_between_is_warning(self):
        assert _compute_kpi_status(self.KPI, 13.0) == "WARNING"

    def test_at_danger_is_danger(self):
        assert _compute_kpi_status(self.KPI, 12.0) == "DANGER"

    def test_below_danger_is_danger(self):
        assert _compute_kpi_status(self.KPI, 5.0) == "DANGER"


class TestEdgeCases:
    def test_no_data_value_none(self):
        kpi = {"warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False}
        assert _compute_kpi_status(kpi, None) == "NO_DATA"

    def test_no_thresholds_is_ok(self):
        kpi = {"warning_threshold": None, "danger_threshold": None, "invert": False}
        assert _compute_kpi_status(kpi, 100.0) == "OK"

    def test_only_warning_threshold_is_ok(self):
        # If either threshold is None → OK (per implementation)
        kpi = {"warning_threshold": 5.0, "danger_threshold": None, "invert": False}
        assert _compute_kpi_status(kpi, 100.0) == "OK"


class TestBugRegressionWarningTrigger:
    """The historical bug: WARNING was only shown when value was >40% of the
    way from warn to danger (because old code used sub_score >= 0.4).
    Direct threshold comparison should fire WARNING immediately at warn."""

    def test_just_at_warning_must_be_warning_not_ok(self):
        kpi = {"warning_threshold": 50.0, "danger_threshold": 100.0, "invert": False}
        assert _compute_kpi_status(kpi, 50.0) == "WARNING"
        assert _compute_kpi_status(kpi, 50.1) == "WARNING"
        # Old bug would have returned OK until value reached ~70 (40% from 50→100)
