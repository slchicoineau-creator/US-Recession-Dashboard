"""Tests for the Depression Severity module and its config section."""

from __future__ import annotations

import pytest

from backend.severity import component_subscore, get_severity_band


# ---------------------------------------------------------------------------
# Config audit
# ---------------------------------------------------------------------------

class TestSeverityConfig:
    def test_section_present_with_weights_summing_to_one(self, kpi_config):
        sev = kpi_config.get("severity")
        assert sev, "kpi_config.yaml must define a severity: section"
        total = sum(c["weight"] for c in sev["components"]) + sev["persistence_weight"]
        assert total == pytest.approx(1.0), f"severity weights sum to {total}, not 1.0"

    def test_components_reference_existing_kpis(self, kpi_config):
        kpi_ids = {k["id"] for k in kpi_config["kpis"]}
        for comp in kpi_config["severity"]["components"]:
            assert comp["kpi_id"] in kpi_ids, f"unknown kpi_id {comp['kpi_id']}"
            assert comp["healthy"] != comp["extreme"]

    def test_bank_credit_kpi_configured(self, kpi_config):
        kpi = next(k for k in kpi_config["kpis"] if k["id"] == "bank_credit")
        assert kpi["series_id"] == "TOTBKCR"
        # Weekly series: YoY needs 52 row-based periods, never 12
        assert kpi["compute_pct_change_periods"] == 52
        assert kpi["invert"] is True


# ---------------------------------------------------------------------------
# component_subscore
# ---------------------------------------------------------------------------

class TestComponentSubscore:
    def test_falling_is_worse_direction(self):
        # healthy 1.5, extreme -1.0 (deflation component shape)
        assert component_subscore(2.0, 1.5, -1.0) == 0.0    # above healthy
        assert component_subscore(1.5, 1.5, -1.0) == 0.0    # at healthy
        assert component_subscore(-1.0, 1.5, -1.0) == 1.0   # at extreme
        assert component_subscore(-3.0, 1.5, -1.0) == 1.0   # beyond extreme clips
        assert component_subscore(0.25, 1.5, -1.0) == pytest.approx(0.5)

    def test_rising_is_worse_direction(self):
        # healthy 6.0, extreme 15.0 (unemployment component shape)
        assert component_subscore(4.0, 6.0, 15.0) == 0.0
        assert component_subscore(15.0, 6.0, 15.0) == 1.0
        assert component_subscore(10.5, 6.0, 15.0) == pytest.approx(0.5)
        assert component_subscore(20.0, 6.0, 15.0) == 1.0

    def test_degenerate_bounds(self):
        assert component_subscore(5.0, 3.0, 3.0) == 0.0
        assert component_subscore(3.0, 3.0, 3.0) == 1.0


# ---------------------------------------------------------------------------
# Severity bands
# ---------------------------------------------------------------------------

class TestSeverityBands:
    @pytest.mark.parametrize("score,band", [
        (0.0, "NORMAL"), (24.9, "NORMAL"),
        (25.0, "SERIOUS"), (49.9, "SERIOUS"),
        (50.0, "SEVERE"), (74.9, "SEVERE"),
        (75.0, "DEPRESSION-SCALE"), (100.0, "DEPRESSION-SCALE"),
    ])
    def test_band_edges(self, score, band):
        assert get_severity_band(score) == band


# ---------------------------------------------------------------------------
# Historical regression against the live DB (read-only)
# ---------------------------------------------------------------------------

class TestHistoricalSeverity:
    """The module's reason to exist: 2009 must read far more severe than COVID
    or today. Uses the live DB; skips when unavailable."""

    def test_2009_reads_severe(self, real_session):
        from datetime import date
        from backend.severity import compute_severity
        result = compute_severity(as_of=date(2009, 10, 1))
        assert result["severity_score"] is not None
        assert result["severity_score"] >= 50, (
            f"Oct 2009 should be SEVERE, got {result['severity_score']}"
        )

    def test_today_reads_below_2009(self, real_session):
        from datetime import date
        from backend.severity import compute_severity
        now = compute_severity()
        then = compute_severity(as_of=date(2009, 10, 1))
        assert now["severity_score"] < then["severity_score"]
