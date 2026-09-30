"""Tests for the AI Bubble Monitor (backend/ai_bubble.py) and its isolation.

The monitor's KPIs live in a monitor-only category. The load-bearing property
is that they can never move the composite score, the ML features or the
leading index; the TestIsolation cases are the ones that matter.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.ai_bubble import GAUGES, _verdict, get_band

AI_KPIS = ("tech_capex_gdp", "market_breadth_gap", "semis_ma200", "private_credit_ma200")


# ---------------------------------------------------------------------------
# Config audit
# ---------------------------------------------------------------------------

class TestConfig:
    def test_gauge_weights_sum_to_one(self, kpi_config):
        cfg = kpi_config["ai_bubble"]
        for gauge in GAUGES:
            total = sum(c["weight"] for c in cfg[gauge])
            assert total == pytest.approx(1.0), f"{gauge} weights sum to {total}"

    def test_components_reference_existing_kpis(self, kpi_config):
        ids = {k["id"] for k in kpi_config["kpis"]}
        for gauge in GAUGES:
            for c in kpi_config["ai_bubble"][gauge]:
                assert c["kpi_id"] in ids, f"unknown kpi_id {c['kpi_id']}"
                assert c["healthy"] != c["extreme"]

    def test_monitor_category_is_not_scored(self, kpi_config):
        monitor = set(kpi_config["monitor_categories"])
        assert "ai_bubble" in monitor
        assert not monitor & set(kpi_config["category_weights"]), \
            "a monitor category must never carry a composite weight"

    def test_new_kpis_are_monitor_only(self, kpi_config):
        by_id = {k["id"]: k for k in kpi_config["kpis"]}
        for kid in AI_KPIS:
            k = by_id[kid]
            assert k["category"] == "ai_bubble"
            assert k["timing"] == "monitor", f"{kid} must not enter leading/diffusion"

    def test_breadth_gap_uses_row_based_yearly_periods(self, kpi_config):
        k = next(k for k in kpi_config["kpis"] if k["id"] == "market_breadth_gap")
        assert k["frequency"] == "daily" and k["compute_pct_change_periods"] == 252

    def test_plausible_ranges_defined(self):
        from backend.fetcher import _PLAUSIBLE_RANGES
        for kid in AI_KPIS:
            assert kid in _PLAUSIBLE_RANGES, f"{kid} missing from _PLAUSIBLE_RANGES"
        # Jun 2026: SOX ran ~76% above its 200d MA; the range must not drop it
        assert _PLAUSIBLE_RANGES["semis_ma200"][1] >= 120


# ---------------------------------------------------------------------------
# Isolation: the monitor must never move the composite / ML / leading index
# ---------------------------------------------------------------------------

class TestIsolation:
    def test_composite_ignores_monitor_kpis(self, kpi_config):
        from backend.scorer import score_from_values
        base = {k["id"]: k["warning_threshold"] for k in kpi_config["kpis"]
                if k["category"] in kpi_config["category_weights"]
                and k.get("warning_threshold") is not None}
        before = score_from_values(kpi_config, base)
        extreme = dict(base, tech_capex_gdp=99.0, market_breadth_gap=-99.0,
                       semis_ma200=-99.0, private_credit_ma200=-99.0)
        after = score_from_values(kpi_config, extreme)
        assert after["score_raw"] == before["score_raw"]
        assert "ai_bubble" not in after["category_scores"]
        assert all(c["category"] != "ai_bubble" for c in after["contributions"])

    def test_ml_categories_exclude_monitor(self):
        from backend.ml_scorer import CATEGORIES
        assert "ai_bubble" not in CATEGORIES

    def test_timing_sets_exclude_monitor(self, kpi_config):
        from backend.leading import _kpis_by_timing
        for timing in ("leading", "coincident", "lagging"):
            ids = {k["id"] for k in _kpis_by_timing(kpi_config, timing)}
            assert not ids & set(AI_KPIS)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestScoring:
    @pytest.mark.parametrize("gauge,score,band", [
        ("exposure", 10, "LOW"), ("exposure", 30, "MODERATE"),
        ("exposure", 60, "HIGH"), ("exposure", 80, "EXTREME"),
        ("puncture", 0, "INTACT"), ("puncture", 25, "CRACKING"),
        ("puncture", 50, "BREAKING"), ("puncture", 75, "BURSTING"),
    ])
    def test_bands(self, gauge, score, band):
        assert get_band(gauge, score) == band

    @pytest.mark.parametrize("peak,puncture,verdict", [
        (84, 0, "Inflated but intact"),      # Sep 2026
        (53, 82, "Bursting"),                # Jun 2022: peak exposure from Dec 2021
        (18, 100, "Market stress"),          # Dec 2008: crash without an equity bubble
        (60, 30, "Cracks forming"),
        (10, 5, "No bubble signal"),
        (None, 5, None),
    ])
    def test_verdict(self, peak, puncture, verdict):
        assert _verdict(peak, puncture) == verdict

    def test_compute_on_synthetic_db(self, tmp_session):
        from backend import ai_bubble
        from backend.models import KpiData
        d = date(2026, 6, 30)
        vals = {"tech_capex_gdp": 5.0, "market_breadth_gap": -5.0, "shiller_cape": 32.0,
                "buffett_indicator": 160.0, "semis_ma200": -12.5, "sp500_ma200": 0.0,
                "private_credit_ma200": 0.0, "hy_spread": 3.0}
        for kid, v in vals.items():
            tmp_session.add(KpiData(kpi_id=kid, date=d, value=v))
        tmp_session.commit()
        r = ai_bubble.compute_ai_bubble(as_of=date(2026, 7, 15))
        # exposure = .30*1 + .20*.5 + .25*.5 + .25*.5 = .65
        assert r["exposure"]["score"] == pytest.approx(65.0)
        # puncture = .30 * .5 = .15
        assert r["puncture"]["score"] == pytest.approx(15.0)
        assert r["verdict"] == "Inflated but intact"
        hist = ai_bubble.compute_ai_bubble_history(date(2026, 5, 1), date(2026, 8, 1))
        assert [h["date"] for h in hist] == ["2026-05-01", "2026-06-01",
                                             "2026-07-01", "2026-08-01"]
        assert hist[0]["exposure"] is None
        assert hist[2]["exposure"] == pytest.approx(65.0)


# ---------------------------------------------------------------------------
# derived_relative fetcher
# ---------------------------------------------------------------------------

class TestDerivedRelative:
    def test_ratio_drops_unmatched_dates(self, monkeypatch):
        from backend import fetcher
        idx = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
        data = {"RSP": pd.Series([200.0, 202.0, 204.0], index=idx),
                "SPY": pd.Series([100.0, 100.0], index=idx[:2])}
        monkeypatch.setattr(fetcher, "fetch_yfinance",
                            lambda t, s, e, frequency="daily": data[t])
        kpi = {"id": "x", "series_id": "RSP", "benchmark_ticker": "SPY"}
        out = fetcher.fetch_derived_relative(kpi, date(2026, 1, 1), date(2026, 1, 6))
        assert list(out.values) == [2.0, 2.02]

    def test_requires_benchmark(self):
        from backend import fetcher
        with pytest.raises(RuntimeError):
            fetcher.fetch_derived_relative({"id": "x", "series_id": "RSP"},
                                           date(2026, 1, 1), date(2026, 1, 6))


# ---------------------------------------------------------------------------
# API (reads the real DB)
# ---------------------------------------------------------------------------

class TestApi:
    def test_endpoint_shape(self):
        import app as app_module
        r = app_module.app.test_client().get("/api/ai-bubble?as_of=2022-06-30")
        assert r.status_code == 200
        body = r.get_json()
        assert set(GAUGES) <= set(body)
        assert "verdict" in body and "exposure_peak_12m" in body

    def test_monitor_category_card_flagged(self):
        import app as app_module
        assert "ai_bubble" in app_module._CATEGORY_INFO
        cats = app_module.app.test_client().get("/api/categories").get_json()
        by_id = {c["id"]: c for c in cats}
        assert by_id["ai_bubble"]["in_composite"] is False
        assert by_id["labor_market"]["in_composite"] is True


# ---------------------------------------------------------------------------
# AI commentary prompts must not present monitor KPIs as score drivers
# ---------------------------------------------------------------------------

class TestCommentaryPrompts:
    KPIS = [
        {"name": "Tech capex", "category": "ai_bubble", "in_composite": False,
         "latest_value": 5.05, "unit": "% of GDP", "status": "DANGER", "sub_score": 1.0},
        {"name": "Unemployment", "category": "labor_market", "in_composite": True,
         "latest_value": 4.1, "unit": "%", "status": "OK", "sub_score": 0.1},
    ]

    def test_monitor_category_prompt_has_no_score(self):
        from backend.commentator import build_category_prompt
        prompt = build_category_prompt("ai_bubble", self.KPIS, 0.0, {"labor_market": 10.0},
                                       date(2026, 9, 30), monitor_only=True,
                                       label="AI Bubble Monitor")
        assert "AI Bubble Monitor" in prompt
        assert "0/100" not in prompt and "NOT part of the Recession Risk Score" in prompt

    def test_global_prompt_excludes_monitor_kpis(self):
        from backend.commentator import build_global_prompt
        prompt = build_global_prompt(self.KPIS, {"labor_market": 10.0}, 36.3, "ELEVATED",
                                     date(2026, 9, 30))
        assert "Tech capex" not in prompt and "Unemployment" in prompt
