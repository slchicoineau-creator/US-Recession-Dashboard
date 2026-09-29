"""Walk-forward validation, benchmark models and probability metrics.

Covers the four pieces added in the "honest validation" upgrade:
  - ml_scorer.label_known: THE leakage rule (boundary month)
  - ml_scorer.walk_forward_ml: a prediction at t is unaffected by labels that
    were not yet public at t (no leakage), and early months yield no prediction
  - backend.benchmarks: T-bill conversion, yield-curve probit sanity against
    the real DB, Time-Machine training cut-off, Chauvet-Piger publication lag
  - backtester Brier / skill / calibration maths and payload contract
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.backtester import _brier, _brier_skill, _calibration, _lead_times
from backend.ml_scorer import (
    CATEGORIES,
    _add_months,
    label_known,
    walk_forward_ml,
)


# ---------------------------------------------------------------------------
# label_known — the single leakage rule
# ---------------------------------------------------------------------------

class TestLabelKnown:
    def test_boundary_month(self):
        # 12m window after Jan 2020 closes Jan 2021; +12m NBER lag -> Jan 2022
        m = date(2020, 1, 1)
        assert not label_known(m, 12, date(2021, 12, 31), lag_months=12)
        assert label_known(m, 12, date(2022, 1, 1), lag_months=12)

    def test_mid_month_as_of_is_floored(self):
        assert label_known(date(2020, 1, 15), 6, date(2020, 7, 20), lag_months=0)
        assert not label_known(date(2020, 1, 1), 6, date(2020, 6, 30), lag_months=0)

    def test_default_lag_comes_from_config(self, kpi_config):
        ref = {r["key"]: r for r in kpi_config["reference_series"]}
        lag = ref["usrecm_long"]["publication_lag_months"]
        m = date(2010, 1, 1)
        assert label_known(m, 0, _add_months(m, lag))
        assert not label_known(m, 0, _add_months(m, lag - 1))


# ---------------------------------------------------------------------------
# walk_forward_ml — no leakage
# ---------------------------------------------------------------------------

def _synthetic_matrix(n_months: int = 150, seed: int = 0) -> pd.DataFrame:
    """Feature matrix with a learnable signal and two recession episodes."""
    rng = np.random.default_rng(seed)
    months = [_add_months(date(2000, 1, 1), i) for i in range(n_months)]
    rec = np.zeros(n_months, dtype=int)
    rec[30:40] = 1
    rec[90:100] = 1
    df = pd.DataFrame(index=months)
    for cat in CATEGORIES:
        df[cat] = rng.uniform(0, 0.4, n_months)
    df["in_recession"] = rec
    for h, col in ((6, "recession_within_6m"), (12, "recession_within_12m")):
        lab = [int(rec[i + 1:i + 1 + h].any()) if i + h < n_months else np.nan
               for i in range(n_months)]
        df[col] = lab
        # make it learnable (noisily): stress rises before recessions
        df.loc[df[col] == 1, "labor_market"] += rng.uniform(0.1, 0.6, int((df[col] == 1).sum()))
    return df


class TestWalkForwardML:
    def test_no_prediction_before_enough_public_labels(self):
        df = _synthetic_matrix()
        out = walk_forward_ml("6m", date(2000, 1, 1), date(2012, 6, 1), df=df)
        first = date.fromisoformat(out["first_prediction"])
        # Needs >= 6 public positive rows: first positives are months ~24-29,
        # public 6 + 12 months later -> nothing before 2003.
        assert first >= date(2003, 1, 1)
        assert all(m >= first for m in out["probs"])

    def test_prediction_ignores_labels_not_yet_public(self):
        df = _synthetic_matrix()
        t = date(2009, 6, 1)
        base = walk_forward_ml("6m", t, t, df=df)["probs"]
        assert t in base, "fixture should allow a prediction at t"

        # Flip every label that was NOT public at t: the prediction must not move.
        poisoned = df.copy()
        col = "recession_within_6m"
        hidden = [m for m in poisoned.index
                  if not pd.isna(poisoned.at[m, col]) and not label_known(m, 6, t)]
        assert hidden, "fixture must contain labels that are not yet public"
        for m in hidden:
            poisoned.at[m, col] = 1 - poisoned.at[m, col]
        again = walk_forward_ml("6m", t, t, df=poisoned)["probs"]
        assert again[t] == base[t]

    def test_reports_fit_counts(self):
        out = walk_forward_ml("12m", date(2000, 1, 1), date(2012, 6, 1), df=_synthetic_matrix())
        assert out["fits"] >= out["failed_fits"] >= 0
        assert set(out) >= {"probs", "fits", "failed_fits", "skipped_months", "first_prediction"}


# ---------------------------------------------------------------------------
# Probability metrics
# ---------------------------------------------------------------------------

class TestProbabilityMetrics:
    def test_brier_perfect_and_worst(self):
        assert _brier([100, 0], [1, 0]) == 0.0
        assert _brier([0, 100], [1, 0]) == 1.0
        assert _brier([], []) is None

    def test_brier_skill_vs_base_rate(self):
        ys = [1, 0, 0, 0]
        base = 25.0                       # always forecasting the base rate
        assert _brier_skill([base] * 4, ys) == 0.0
        assert _brier_skill([100, 0, 0, 0], ys) == 1.0
        assert _brier_skill([0, 100, 100, 100], ys) < 0
        assert _brier_skill([10, 20], [0, 0]) is None   # one class only

    def test_calibration_bins(self):
        probs = [5, 7, 55, 95, 100]
        ys = [0, 1, 1, 1, 1]
        bins = {b["bin_low"]: b for b in _calibration(probs, ys)}
        assert bins[0.0]["n"] == 2 and bins[0.0]["observed_rate"] == 50.0
        assert bins[50.0]["n"] == 1
        assert bins[90.0]["n"] == 2       # 100% lands in the top bin
        assert sum(b["n"] for b in bins.values()) == len(probs)

    def test_lead_status_no_data_vs_missed(self):
        onset = date(2020, 2, 1)
        assert _lead_times({}, [onset], 50)[0]["status"] == "no_data"
        series = {date(2019, 6, 1): 10.0}
        assert _lead_times(series, [onset], 50)[0]["status"] == "missed"
        series = {date(2019, 6, 1): 60.0}
        r = _lead_times(series, [onset], 50)[0]
        assert r["status"] == "led" and r["lead_months"] == 8


# ---------------------------------------------------------------------------
# Benchmarks (yield curve + Chauvet-Piger)
# ---------------------------------------------------------------------------

def test_discount_to_bey():
    from backend.benchmarks import discount_to_bey
    # 5% discount basis, 91 days -> 365*.05/(360-91*.05) = 5.1343%
    assert discount_to_bey(5.0) == pytest.approx(5.1343, abs=1e-3)
    assert discount_to_bey(0.0) == 0.0


def test_reference_series_config(kpi_config):
    refs = kpi_config.get("reference_series")
    assert refs, "kpi_config.yaml must define reference_series"
    keys = [r["key"] for r in refs]
    assert len(keys) == len(set(keys))
    assert {"usrecm_long", "gs10", "tb3ms", "chauvet_piger"} <= set(keys)
    kpi_ids = {k["id"] for k in kpi_config["kpis"]}
    assert not (set(keys) & kpi_ids), "reference series must not collide with KPI ids"
    for r in refs:
        assert r["series_id"] and int(r["publication_lag_months"]) >= 0


@pytest.fixture(scope="module")
def reference_available(real_session):
    from backend.models import ReferenceSeries
    n = real_session.query(ReferenceSeries).count()
    if n == 0:
        pytest.skip("reference_series table empty — run the app once to fetch it")
    return n


class TestYieldCurveBenchmark:
    def test_live_fit_is_sane(self, reference_available):
        from backend.benchmarks import yield_curve_now
        yc = yield_curve_now()
        assert yc is not None
        assert yc["coefficients"]["spread"] < 0, "flatter curve must raise the probability"
        assert 0.0 <= yc["prob_12m"] <= 100.0
        assert yc["n_observations"] > 600          # 1959+ history

    def test_time_machine_uses_only_public_labels(self, reference_available):
        from backend.benchmarks import yield_curve_now
        yc = yield_curve_now(date(2008, 9, 15))
        # 12m horizon + 12m NBER lag -> last usable label month is Sep 2006
        assert date.fromisoformat(yc["train_end"]) <= date(2006, 9, 1)
        # spread must be the last COMPLETED month before the as-of date
        assert yc["spread_month"] == "2008-08-01"

    def test_refuses_fits_on_too_few_recessions(self, reference_available):
        from backend.benchmarks import MIN_TRAIN_RECESSIONS, yield_curve_now
        # 1967: one recession in the public training window -> no model (a fit
        # there even has the wrong sign), rather than a meaningless number
        assert yield_curve_now(date(1967, 1, 1)) is None
        assert yield_curve_now()["n_recessions"] >= MIN_TRAIN_RECESSIONS

    def test_warned_before_2008(self, reference_available):
        from backend.benchmarks import yield_curve_now
        # The curve inverted in 2006-07; out-of-sample the model should be elevated.
        assert yield_curve_now(date(2007, 6, 1))["prob_12m"] > 40

    def test_chauvet_piger_publication_lag(self, reference_available, kpi_config):
        from backend.benchmarks import chauvet_piger_at
        lag = {r["key"]: r for r in kpi_config["reference_series"]}["chauvet_piger"]["publication_lag_months"]
        cp = chauvet_piger_at(date(2008, 9, 15))
        assert cp["retrospective"] is True
        assert date.fromisoformat(cp["month"]) == _add_months(date(2008, 9, 1), -lag)


class TestBacktestPayload:
    @pytest.fixture(scope="class")
    def backtest(self, reference_available):
        from backend.backtester import run_backtest
        return run_backtest()

    def test_signals_and_validation_labels(self, backtest):
        sig = backtest["signals"]
        for sid in ("ml_12m_wf", "ml_6m_wf", "yield_curve", "chauvet_piger"):
            assert sid in sig
        assert sig["ml_12m"]["validation"] == "in-sample"
        assert sig["ml_12m_wf"]["validation"] == "walk-forward"
        assert sig["chauvet_piger"]["validation"] == "retrospective"
        assert "(in-sample)" in sig["ml_12m"]["name"]

    def test_probability_signals_have_brier_and_calibration(self, backtest):
        for sid, s in backtest["signals"].items():
            if s.get("available") and s["kind"] == "probability":
                assert s["brier"] is not None and 0 <= s["brier"] <= 1, sid
                assert s["calibration"], sid

    def test_retrospective_excluded_from_common_window(self, backtest):
        cw = backtest["common_window"]
        assert "chauvet_piger" not in cw["signals"]
        assert cw["months"] > 0 and cw["positive_months"] > 0
        assert all(r["status"] == "not_applicable"
                   for r in backtest["signals"]["chauvet_piger"]["recessions"])

    def test_lead_window_scales_with_horizon(self, backtest):
        sig = backtest["signals"]
        assert sig["composite"]["lead_window_months"] == 18
        assert sig["ml_12m"]["lead_window_months"] == 18
        assert sig["ml_6m"]["lead_window_months"] == 12
        assert sig["chauvet_piger"]["lead_window_months"] is None
        for s in sig.values():
            for r in s.get("recessions", []):
                if r["status"] == "led":
                    assert r["lead_months"] <= s["lead_window_months"]

    def test_caveats_present(self, backtest):
        assert "revised data" in backtest["caveat"]
        assert "hindsight" in backtest["walk_forward_note"]
