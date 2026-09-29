"""
Independent benchmark recession signals (not part of the composite score).

  yield_curve   - NY Fed / Estrella-Mishkin style probit:
                  P(recession within 12 months) = Phi(a + b * spread),
                  spread = 10y Treasury (GS10) - 3m bill (TB3MS converted to
                  bond-equivalent yield), monthly averages, fitted on 1959+
                  (9 NBER recessions vs. the dashboard ML models' 2).
                  Every fit only uses labels public at the evaluation month
                  (ml_scorer.label_known), and every prediction only uses the
                  spread of the last COMPLETED month.
  chauvet_piger - FRED RECPROUSM156N smoothed recession probability.
                  RETROSPECTIVE: re-estimated over the full sample on every
                  release, so its history is a cross-check, not a forecast.

Inputs come from the `reference_series` table (kpi_config.yaml
`reference_series:`), never from KpiData — see the config comment for why.

Note the target differs from the NY Fed's published model (which predicts a
recession in month t+12 exactly): here it is "any recession month within the
next 12 months", the same label the dashboard's ml_12m model uses, so the two
are directly comparable.
"""

import logging
from datetime import date
from typing import Optional

import pandas as pd
import statsmodels.api as sm

from backend.ml_scorer import _add_months, _iter_months, forward_label, label_known, safe_fit

logger = logging.getLogger(__name__)

HORIZON = 12
MIN_TRAIN_ROWS = 60
# A fit on fewer recessions is not a yield-curve model: with 1 episode (e.g.
# as_of 1967) the spread coefficient can even come out positive, i.e. an
# inverted curve LOWERING the risk. Such fits are refused (reported as n/a).
MIN_TRAIN_RECESSIONS = 3


def _ref_config() -> dict:
    from backend.fetcher import load_config
    return {r["key"]: r for r in (load_config().get("reference_series", []) or [])}


def _pub_lag(key: str, default: int = 1) -> int:
    return int(_ref_config().get(key, {}).get("publication_lag_months", default))


def load_reference(key: str) -> dict:
    """{first-of-month date: value} for one reference series."""
    from backend.models import ReferenceSeries, get_session
    session = get_session()
    try:
        return {
            row.date.replace(day=1): row.value
            for row in session.query(ReferenceSeries.date, ReferenceSeries.value)
            .filter(ReferenceSeries.series_key == key)
            .all()
        }
    finally:
        session.close()


def discount_to_bey(discount_pct: float, days: int = 91) -> float:
    """T-bill discount-basis yield (%) -> bond-equivalent yield (%), as the NY Fed does."""
    d = discount_pct / 100.0
    return 100.0 * 365.0 * d / (360.0 - days * d)


def spread_series() -> dict:
    """{month: GS10 - BEY(TB3MS)} in percentage points."""
    gs10, tb3 = load_reference("gs10"), load_reference("tb3ms")
    return {m: round(gs10[m] - discount_to_bey(tb3[m]), 4) for m in gs10 if m in tb3}


def _nber_long() -> dict:
    return {m: int(v) for m, v in load_reference("usrecm_long").items()}


def _feature_month(t: date, spread_lag: int) -> date:
    """The latest spread month public at evaluation month t."""
    return _add_months(t.replace(day=1), -spread_lag)


def _training_frame(spread: dict, nber: dict, at: date, spread_lag: int) -> pd.DataFrame:
    """Rows (feature = spread public at month m, label = recession in (m, m+12]),
    restricted to labels public at `at`."""
    rows = []
    for m in sorted(nber):
        if not label_known(m, HORIZON, at):
            continue
        fm = _feature_month(m, spread_lag)
        if fm not in spread:
            continue
        lbl = forward_label(nber, m, HORIZON)
        if lbl is None:
            continue
        rows.append({"month": m, "spread": spread[fm], "label": lbl})
    return pd.DataFrame(rows)


def _n_recessions(frame: pd.DataFrame, nber: dict) -> int:
    """NBER recession episodes whose onset falls inside the training months."""
    if frame.empty:
        return 0
    lo, hi = frame["month"].min(), frame["month"].max()
    return sum(
        1 for m in sorted(nber)
        if lo <= m <= hi and nber[m] == 1 and nber.get(_add_months(m, -1), 0) == 0
    )


def _fit(frame: pd.DataFrame, nber: dict):
    if len(frame) < MIN_TRAIN_ROWS or frame["label"].nunique() < 2:
        return None
    if _n_recessions(frame, nber) < MIN_TRAIN_RECESSIONS:
        return None
    X = sm.add_constant(frame[["spread"]], has_constant="add")
    result = safe_fit(sm.Probit, frame["label"].astype(int), X)
    if result is None or result.params["spread"] >= 0:
        return None
    return result


def _predict(result, spread_value: float) -> float:
    X = pd.DataFrame({"const": [1.0], "spread": [spread_value]})
    return round(float(result.predict(X).iloc[0]) * 100.0, 1)


def yield_curve_walkforward(from_date: date, end_date: date) -> dict:
    """Out-of-sample monthly P(recession within 12m) from the yield-curve probit.

    Returns {"probs": {month: pct}, "fits": int, "failed_fits": int}.
    """
    spread, nber = spread_series(), _nber_long()
    lag = _pub_lag("gs10")
    probs, fits, failed = {}, 0, 0
    last_n, result = None, None
    for t in _iter_months(from_date, end_date):
        fm = _feature_month(t, lag)
        if fm not in spread:
            continue
        frame = _training_frame(spread, nber, t, lag)
        if len(frame) != last_n:
            last_n = len(frame)
            fits += 1
            result = _fit(frame, nber)
            if result is None:
                failed += 1
        if result is None:
            continue
        probs[t] = _predict(result, spread[fm])
    return {"probs": probs, "fits": fits, "failed_fits": failed}


def yield_curve_now(as_of: Optional[date] = None) -> Optional[dict]:
    """Yield-curve probit reading for `as_of` (default today), using only the
    labels and spread observations that were public then."""
    at = (as_of or date.today()).replace(day=1)
    spread, nber = spread_series(), _nber_long()
    if not spread or not nber:
        return None
    lag = _pub_lag("gs10")
    public = [m for m in spread if _add_months(m, lag) <= at]
    if not public:
        return None
    fm = max(public)
    frame = _training_frame(spread, nber, at, lag)
    result = _fit(frame, nber)
    if result is None:
        return None
    return {
        "prob_12m": _predict(result, spread[fm]),
        "spread": round(spread[fm], 2),
        "spread_month": fm.isoformat(),
        "train_start": frame["month"].min().isoformat(),
        "train_end": frame["month"].max().isoformat(),
        "n_observations": int(len(frame)),
        "n_recessions": _n_recessions(frame, nber),
        "coefficients": {k: round(float(v), 4) for k, v in result.params.items()},
    }


def chauvet_piger_series() -> dict:
    """{month: probability %} — the full retrospective history."""
    return load_reference("chauvet_piger")


def chauvet_piger_at(as_of: Optional[date] = None) -> Optional[dict]:
    """Latest Chauvet-Piger value public at `as_of` (publication lag applied).
    Live mode: simply the newest value."""
    series = chauvet_piger_series()
    if not series:
        return None
    if as_of is None:
        m = max(series)
    else:
        lag = _pub_lag("chauvet_piger", 2)
        public = [k for k in series if _add_months(k, lag) <= as_of.replace(day=1)]
        if not public:
            return None
        m = max(public)
    return {"prob": round(series[m], 1), "month": m.isoformat(), "retrospective": True}


def current_benchmarks(as_of: Optional[date] = None) -> dict:
    """Payload for GET /api/benchmarks."""
    yc = cp = None
    try:
        yc = yield_curve_now(as_of)
    except Exception as exc:
        logger.warning("Yield-curve benchmark failed: %s", exc)
    try:
        cp = chauvet_piger_at(as_of)
    except Exception as exc:
        logger.warning("Chauvet-Piger benchmark failed: %s", exc)
    return {
        "as_of": (as_of or date.today()).isoformat(),
        "simulated": as_of is not None,
        "yield_curve": yc,
        "chauvet_piger": cp,
    }
