"""Unit tests for backend.scorer.normalize_kpi and compute_recession_score."""

from __future__ import annotations

from datetime import date

import pytest

from backend.scorer import normalize_kpi, get_risk_band, compute_recession_score
from backend.models import KpiData


# ---------------------------------------------------------------------------
# normalize_kpi (pure function — no DB)
# ---------------------------------------------------------------------------

class TestNormalizeKpi:
    def test_no_thresholds_returns_zero(self):
        kpi = {"id": "x", "warning_threshold": None, "danger_threshold": None}
        assert normalize_kpi(kpi, 100.0) == 0.0

    def test_standard_below_warn_returns_zero(self):
        kpi = {"id": "x", "warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False}
        assert normalize_kpi(kpi, 4.99) == 0.0

    def test_standard_at_warn_returns_zero(self):
        # warn is exclusive lower bound (value < warn → 0); value == warn → 0.4 baseline
        kpi = {"id": "x", "warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False}
        assert normalize_kpi(kpi, 5.0) == pytest.approx(0.4)

    def test_standard_at_danger_returns_one(self):
        kpi = {"id": "x", "warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False}
        assert normalize_kpi(kpi, 10.0) == 1.0

    def test_standard_above_danger_returns_one(self):
        kpi = {"id": "x", "warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False}
        assert normalize_kpi(kpi, 99.0) == 1.0

    def test_standard_midpoint(self):
        kpi = {"id": "x", "warning_threshold": 5.0, "danger_threshold": 10.0, "invert": False}
        # midpoint between warn (0.4) and danger (1.0) → 0.7
        assert normalize_kpi(kpi, 7.5) == pytest.approx(0.7)

    def test_inverted_above_warn_returns_zero(self):
        # invert: lower=worse, warn > danger
        kpi = {"id": "x", "warning_threshold": 14.0, "danger_threshold": 12.0, "invert": True}
        assert normalize_kpi(kpi, 14.5) == 0.0

    def test_inverted_at_warn_returns_baseline(self):
        kpi = {"id": "x", "warning_threshold": 14.0, "danger_threshold": 12.0, "invert": True}
        assert normalize_kpi(kpi, 14.0) == pytest.approx(0.4)

    def test_inverted_at_danger_returns_one(self):
        kpi = {"id": "x", "warning_threshold": 14.0, "danger_threshold": 12.0, "invert": True}
        assert normalize_kpi(kpi, 12.0) == 1.0

    def test_inverted_below_danger_returns_one(self):
        kpi = {"id": "x", "warning_threshold": 14.0, "danger_threshold": 12.0, "invert": True}
        assert normalize_kpi(kpi, 5.0) == 1.0

    def test_sahm_rule_hard_trigger(self):
        # Sahm Rule special case: value ≥ 0.5 → 1.0 regardless of thresholds
        kpi = {"id": "sahm_rule", "warning_threshold": 0.3, "danger_threshold": 0.5, "invert": False}
        assert normalize_kpi(kpi, 0.5) == 1.0
        assert normalize_kpi(kpi, 0.51) == 1.0
        # Below 0.5 falls back to interpolation (still hits danger_threshold path)
        assert 0.0 <= normalize_kpi(kpi, 0.3) <= 1.0

    def test_inverted_with_only_danger_threshold(self):
        kpi = {"id": "x", "warning_threshold": None, "danger_threshold": 0.0, "invert": True}
        assert normalize_kpi(kpi, -1.0) == 1.0
        assert normalize_kpi(kpi, 1.0) == 0.0


# ---------------------------------------------------------------------------
# get_risk_band
# ---------------------------------------------------------------------------

class TestRiskBand:
    @pytest.mark.parametrize("score,band", [
        (0.0, "LOW"),
        (24.9, "LOW"),
        (25.0, "ELEVATED"),
        (49.9, "ELEVATED"),
        (50.0, "HIGH"),
        (74.9, "HIGH"),
        (75.0, "CRITICAL"),
        (100.0, "CRITICAL"),
    ])
    def test_band_boundaries(self, score, band):
        assert get_risk_band(score) == band


# ---------------------------------------------------------------------------
# compute_recession_score (uses DB via get_session)
# ---------------------------------------------------------------------------

def _seed_kpi(session, kpi_id: str, value: float, day: date):
    session.add(KpiData(kpi_id=kpi_id, date=day, value=value))
    session.commit()


class TestComputeScore:
    def test_empty_db_returns_zero_band_low(self, tmp_session):
        result = compute_recession_score()
        assert result["score"] == 0.0
        assert result["band"] == "LOW"

    def test_all_kpis_at_danger_caps_at_100(self, tmp_session, kpi_config):
        today = date.today()
        for kpi in kpi_config["kpis"]:
            danger = kpi.get("danger_threshold")
            warn = kpi.get("warning_threshold")
            if danger is None and warn is None:
                continue
            invert = kpi.get("invert", False)
            # Pick a value that will normalize to 1.0
            if invert:
                val = (danger if danger is not None else warn) - 5.0
            else:
                val = (danger if danger is not None else warn) + 5.0
            _seed_kpi(tmp_session, kpi["id"], val, today)
        result = compute_recession_score()
        assert result["score"] >= 95.0, f"all-danger should cap near 100, got {result['score']}"
        assert result["band"] == "CRITICAL"

    def test_all_kpis_below_warn_returns_low(self, tmp_session, kpi_config):
        today = date.today()
        for kpi in kpi_config["kpis"]:
            danger = kpi.get("danger_threshold")
            warn = kpi.get("warning_threshold")
            if danger is None and warn is None:
                continue
            invert = kpi.get("invert", False)
            if invert:
                val = (warn if warn is not None else danger) + 10.0
            else:
                val = (warn if warn is not None else danger) - 10.0
            _seed_kpi(tmp_session, kpi["id"], val, today)
        result = compute_recession_score()
        assert result["score"] < 25.0, f"all-healthy should be LOW, got {result['score']}"
        assert result["band"] == "LOW"

    def test_no_persist_when_as_of_set(self, tmp_session, kpi_config):
        from backend.models import RecessionScore
        compute_recession_score(as_of_date=date(2008, 9, 15))
        rows = tmp_session.query(RecessionScore).count()
        assert rows == 0, "Time Machine mode must NOT persist score to DB"

    def test_does_persist_when_live(self, tmp_session, kpi_config):
        from backend.models import RecessionScore
        # Seed at least one KPI so the live path doesn't skip computation
        today = date.today()
        for kpi in kpi_config["kpis"][:5]:
            warn = kpi.get("warning_threshold")
            if warn is not None:
                _seed_kpi(tmp_session, kpi["id"], warn, today)
        compute_recession_score()
        rows = tmp_session.query(RecessionScore).count()
        assert rows == 1
