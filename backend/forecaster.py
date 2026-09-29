"""
3-Month KPI Forecaster.

Uses linear regression (OLS via numpy.polyfit) on the last 24 stored data
points for each KPI and projects forward the number of data periods that
corresponds to 3 calendar months:

  monthly   → 3 periods
  quarterly → 1 period
  weekly    → 13 periods
  daily     → 90 periods

The forecast operates on post-transform values already stored in the DB
(e.g. YoY % for sp500, raw % for unrate), so existing normalize_kpi()
thresholds apply directly to the forecasted values.
"""

import logging
from datetime import date
from typing import Optional

import numpy as np
from dateutil.relativedelta import relativedelta

from backend.models import KpiData

logger = logging.getLogger(__name__)

# How many data periods ahead equals ~3 calendar months
_PERIODS_AHEAD = {
    "daily":     90,
    "weekly":    13,
    "monthly":   3,
    "quarterly": 1,
}

# How many recent data points to use for the regression
_LOOKBACK = 24


def _forecast_date(as_of: date) -> date:
    """Return the target forecast date: exactly 3 months after as_of."""
    return as_of + relativedelta(months=3)


def forecast_kpi(kpi_id: str, kpi_config: dict, as_of: date, session) -> dict:
    """
    Forecast a single KPI value 3 months into the future.

    Returns a dict with keys:
      forecast_value    : float | None
      forecast_date     : str  (ISO "YYYY-MM-DD")
      method            : "linear_regression" | "carry_forward" | None
      data_points       : int
      r2                : float | None  (coefficient of determination)
      trend_direction   : "up" | "down" | "flat" | None
    """
    freq = kpi_config.get("frequency", "monthly")
    periods_ahead = _PERIODS_AHEAD.get(freq, 3)
    target_date = _forecast_date(as_of)

    # Fetch last _LOOKBACK rows on or before as_of
    rows = (
        session.query(KpiData)
        .filter(KpiData.kpi_id == kpi_id, KpiData.date <= as_of)
        .order_by(KpiData.date.desc())
        .limit(_LOOKBACK)
        .all()
    )

    if not rows:
        return {
            "forecast_value": None,
            "forecast_date": target_date.isoformat(),
            "method": None,
            "data_points": 0,
            "r2": None,
            "trend_direction": None,
        }

    # Reverse to chronological order
    rows = list(reversed(rows))
    values = np.array([r.value for r in rows], dtype=float)

    # Drop NaN entries
    valid_mask = ~np.isnan(values)
    n_valid = int(valid_mask.sum())

    if n_valid < 2:
        # Not enough points — carry forward the last known value
        last_val = float(values[valid_mask][-1]) if n_valid == 1 else None
        return {
            "forecast_value": last_val,
            "forecast_date": target_date.isoformat(),
            "method": "carry_forward",
            "data_points": n_valid,
            "r2": None,
            "trend_direction": "flat",
        }

    x = np.arange(len(values), dtype=float)[valid_mask]
    y = values[valid_mask]

    # Linear regression: y = slope * x + intercept
    coeffs = np.polyfit(x, y, 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])

    # Predict at the next position beyond the last data point
    x_future = float(len(rows) - 1 + periods_ahead)
    forecast_val = slope * x_future + intercept

    # R² — measures how well the line fits recent data
    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
    r2 = max(0.0, min(1.0, r2))

    # Trend direction: slope relative to the mean magnitude of the series
    mean_mag = float(np.mean(np.abs(y))) or 1.0
    slope_rel = abs(slope) / mean_mag
    if slope_rel < 0.005:
        direction = "flat"
    elif slope > 0:
        direction = "up"
    else:
        direction = "down"

    return {
        "forecast_value": float(forecast_val),
        "forecast_date": target_date.isoformat(),
        "method": "linear_regression",
        "data_points": n_valid,
        "r2": round(r2, 3),
        "trend_direction": direction,
    }


def forecast_all_kpis(kpis: list, as_of: date, session) -> dict:
    """
    Forecast all KPIs 3 months ahead.

    Parameters
    ----------
    kpis    : list of KPI config dicts (from kpi_config.yaml)
    as_of   : reference date (today in live mode; historical date in Time Machine)
    session : SQLAlchemy session

    Returns
    -------
    dict mapping kpi_id -> forecast dict (see forecast_kpi return shape)
    """
    results = {}
    for kpi in kpis:
        kpi_id = kpi.get("id")
        if not kpi_id:
            continue
        try:
            results[kpi_id] = forecast_kpi(kpi_id, kpi, as_of, session)
        except Exception as exc:
            logger.warning("Forecast failed for %s: %s", kpi_id, exc)
            results[kpi_id] = {
                "forecast_value": None,
                "forecast_date": _forecast_date(as_of).isoformat(),
                "method": None,
                "data_points": 0,
                "r2": None,
                "trend_direction": None,
            }
    return results


def compute_forecast_accuracy(kpi_id: str, kpi_config: dict, as_of: date, session) -> dict:
    """
    Backtest the 3-month forecast for a single KPI over the past 3 months.

    For each actual data point D in [as_of − 3 months, as_of], re-runs the
    forecast as of D − 3 months and compares the predicted value to the actual
    value at D.  Errors are scaled by the KPI's danger/warning threshold magnitude
    so that near-zero series (e.g. yield spreads) don't produce infinite MAPE.

    Returns
    -------
    dict with:
      accuracy : float | None  — 0–100 %; None when < 2 validation samples
      samples  : int           — number of validation points used
    """
    from dateutil.relativedelta import relativedelta

    freq = kpi_config.get("frequency", "monthly")
    three_months_ago = as_of - relativedelta(months=3)

    # Actual data points in [as_of − 3 months, as_of]
    actuals = (
        session.query(KpiData)
        .filter(
            KpiData.kpi_id == kpi_id,
            KpiData.date >= three_months_ago,
            KpiData.date <= as_of,
        )
        .order_by(KpiData.date.asc())
        .all()
    )

    # Daily KPIs: sample every ~5 rows to cap at ≤ 13 validation points
    if freq == "daily" and len(actuals) > 15:
        step = max(1, len(actuals) // 13)
        actuals = actuals[::step]

    if len(actuals) < 2:
        return {"accuracy": None, "samples": len(actuals)}

    # Scale errors by the KPI's meaningful range (avoids div-by-zero for near-zero values)
    warn = abs(kpi_config.get("warning_threshold") or 0)
    danger = abs(kpi_config.get("danger_threshold") or 0)
    scale = max(warn, danger, 0.001)

    errors = []
    for row in actuals:
        as_of_for_fc = row.date - relativedelta(months=3)
        try:
            fc = forecast_kpi(kpi_id, kpi_config, as_of_for_fc, session)
            if fc["forecast_value"] is None:
                continue
            err = abs(row.value - fc["forecast_value"]) / scale * 100
            errors.append(min(err, 100.0))  # cap per-sample to prevent outliers dominating
        except Exception:
            continue

    if not errors:
        return {"accuracy": None, "samples": 0}

    accuracy = max(0.0, round(100.0 - sum(errors) / len(errors), 1))
    return {"accuracy": accuracy, "samples": len(errors)}


def compute_forecast_status(kpi_config: dict, forecast_value: Optional[float]) -> str:
    """
    Compute OK/WARNING/DANGER/NO_DATA for a forecasted value using the same
    threshold logic as the live /api/kpis status computation.
    """
    if forecast_value is None:
        return "NO_DATA"

    warn = kpi_config.get("warning_threshold")
    danger = kpi_config.get("danger_threshold")
    invert = kpi_config.get("invert", False)

    if warn is None and danger is None:
        return "OK"

    v = forecast_value

    if invert:
        if danger is not None and v <= danger:
            return "DANGER"
        if warn is not None and v <= warn:
            return "WARNING"
    else:
        if danger is not None and v >= danger:
            return "DANGER"
        if warn is not None and v >= warn:
            return "WARNING"

    return "OK"
