"""Tests for the leading-indicator module and the timing tags in kpi_config."""

from __future__ import annotations

from datetime import date

from backend.leading import (
    _composite_from_subscores,
    _diffusion,
    _value_on_or_before,
)


# `monitor` = shown on the dashboard but excluded from every index (ai_bubble)
VALID_TIMINGS = {"leading", "coincident", "lagging", "monitor"}


# ---------------------------------------------------------------------------
# Config audit
# ---------------------------------------------------------------------------

class TestTimingTags:
    def test_every_kpi_has_valid_timing(self, kpi_config):
        untagged = [k["id"] for k in kpi_config["kpis"]
                    if k.get("timing") not in VALID_TIMINGS]
        assert untagged == [], f"KPIs without a valid timing tag: {untagged}"

    def test_leading_set_is_meaningful(self, kpi_config):
        """A diffusion index over too few KPIs is noise; require breadth."""
        leading = [k for k in kpi_config["kpis"] if k.get("timing") == "leading"]
        assert len(leading) >= 15
        # The classic leaders must be tagged leading
        leading_ids = {k["id"] for k in leading}
        for must in ("t10y2y", "t10y3m", "icsa", "building_permits", "sp500",
                     "temp_help", "heavy_truck_sales", "awhman_hours"):
            assert must in leading_ids, f"{must} should be tagged leading"

    def test_new_kpis_present_with_transforms(self, kpi_config):
        by_id = {k["id"]: k for k in kpi_config["kpis"]}
        for kpi_id, series in (("temp_help", "TEMPHELPS"),
                               ("awhman_hours", "AWHMAN"),
                               ("heavy_truck_sales", "HTRUCKSSA")):
            kpi = by_id[kpi_id]
            assert kpi["series_id"] == series
            assert kpi["compute_pct_change_periods"] == 12
            assert kpi["invert"] is True
            assert kpi["warning_threshold"] > kpi["danger_threshold"]


# ---------------------------------------------------------------------------
# _value_on_or_before
# ---------------------------------------------------------------------------

class TestValueLookup:
    POINTS = [(date(2024, 1, 1), 10.0), (date(2024, 6, 1), 20.0), (date(2025, 1, 1), 30.0)]

    def test_exact_and_between(self):
        assert _value_on_or_before(self.POINTS, date(2024, 6, 1)) == 20.0
        assert _value_on_or_before(self.POINTS, date(2024, 8, 15)) == 20.0

    def test_before_first_returns_none(self):
        assert _value_on_or_before(self.POINTS, date(2023, 12, 31)) is None

    def test_stale_carry_capped(self):
        # > 370 days after the last point → treated as missing
        assert _value_on_or_before(self.POINTS, date(2026, 3, 1)) is None
        assert _value_on_or_before(self.POINTS, date(2025, 12, 1)) == 30.0


# ---------------------------------------------------------------------------
# Composite + diffusion on synthetic KPIs
# ---------------------------------------------------------------------------

KPI_HIGH_BAD = {  # invert=False: higher = worse (e.g. unemployment)
    "id": "syn_high", "name": "High-bad", "category": "labor_market",
    "warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False,
}
KPI_LOW_BAD = {   # invert=True: lower = worse (e.g. confidence)
    "id": "syn_low", "name": "Low-bad", "category": "housing",
    "warning_threshold": 0.0, "danger_threshold": -5.0, "invert": True,
}
WEIGHTS = {"labor_market": 0.5, "housing": 0.5}


class TestCompositeFromSubscores:
    def test_all_healthy_scores_zero(self):
        vals = {"syn_high": 1.0, "syn_low": 3.0}
        assert _composite_from_subscores([KPI_HIGH_BAD, KPI_LOW_BAD], vals, WEIGHTS) == 0.0

    def test_all_breached_scores_100(self):
        vals = {"syn_high": 15.0, "syn_low": -9.0}
        assert _composite_from_subscores([KPI_HIGH_BAD, KPI_LOW_BAD], vals, WEIGHTS) == 100.0

    def test_missing_values_excluded(self):
        vals = {"syn_high": 15.0, "syn_low": None}
        score = _composite_from_subscores([KPI_HIGH_BAD, KPI_LOW_BAD], vals, WEIGHTS)
        assert score == 100.0  # housing has no data; weight renormalizes to labor

    def test_no_data_returns_none(self):
        assert _composite_from_subscores([KPI_HIGH_BAD], {}, WEIGHTS) is None


class TestDiffusion:
    def _series_map(self):
        return {
            # rose 4 → 8: worse for invert=False
            "syn_high": [(date(2026, 1, 1), 4.0), (date(2026, 6, 1), 8.0)],
            # rose -2 → 1: better for invert=True (higher = healthier)
            "syn_low": [(date(2026, 1, 1), -2.0), (date(2026, 6, 1), 1.0)],
        }

    def test_direction_respects_invert(self):
        result = _diffusion([KPI_HIGH_BAD, KPI_LOW_BAD], self._series_map(), date(2026, 6, 15))
        assert result["n_kpis"] == 2
        assert result["n_deteriorating"] == 1
        assert result["diffusion_index"] == 50.0
        by_id = {d["kpi_id"]: d for d in result["details"]}
        assert by_id["syn_high"]["deteriorating"] is True
        assert by_id["syn_low"]["deteriorating"] is False

    def test_no_data_returns_none(self):
        assert _diffusion([KPI_HIGH_BAD], {}, date(2026, 6, 15)) is None
