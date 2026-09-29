"""
Leading-indicator analytics.

Every KPI in kpi_config.yaml carries a `timing` tag (leading | coincident |
lagging) following the Conference Board LEI/CEI/LAG taxonomy. This module
derives two forward-looking aggregates from the post-transform values already
stored in KpiData:

  Leading Index    - the composite scoring methodology (normalize_kpi
                     sub-scores, peak-weighted category averages, category
                     weights renormalized over categories with data) applied
                     to LEADING KPIs only. 0-100; higher = more risk signaled
                     by indicators that historically turn first.

  Diffusion Index  - % of leading KPIs whose value has moved in the
                     risk-increasing direction over the last 3 months.
                     Recessions announce themselves through breadth: a few
                     noisy KPIs always deteriorate (baseline ~40-60), but
                     readings above ~70 mean the downturn is broad-based.

Values are computed from stored post-transform data (YoY %, spreads, etc.),
so existing thresholds and invert flags apply directly.
"""

import logging
from datetime import date, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta

from backend.models import KpiData, get_session
from backend.scorer import _load_config, normalize_kpi

logger = logging.getLogger(__name__)

# A value older than this (relative to the evaluation date) is treated as
# missing rather than carried forward — prevents dead series from silently
# pinning the index for years in historical computations.
_MAX_CARRY_DAYS = 370

# Diffusion look-back window
_DIFFUSION_MONTHS = 3


def _kpis_by_timing(config: dict, timing: str) -> list:
    return [k for k in config["kpis"] if k.get("timing") == timing]


def _load_series_map(kpi_ids: list) -> dict:
    """Load all rows for the given KPIs in one query.

    Returns {kpi_id: [(date, value), ...]} with each list sorted by date.
    """
    session = get_session()
    try:
        rows = (
            session.query(KpiData.kpi_id, KpiData.date, KpiData.value)
            .filter(KpiData.kpi_id.in_(kpi_ids))
            .order_by(KpiData.kpi_id, KpiData.date)
            .all()
        )
    finally:
        session.close()
    series: dict = {}
    for kpi_id, dt, val in rows:
        if val is not None:
            series.setdefault(kpi_id, []).append((dt, val))
    return series


def _value_on_or_before(points: list, as_of: date) -> Optional[float]:
    """Last value on or before as_of (binary search), None if too stale/missing."""
    lo, hi = 0, len(points)
    while lo < hi:
        mid = (lo + hi) // 2
        if points[mid][0] <= as_of:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    dt, val = points[lo - 1]
    if (as_of - dt).days > _MAX_CARRY_DAYS:
        return None
    return val


def _composite_from_subscores(kpis: list, values: dict, cat_weights: dict) -> Optional[float]:
    """Apply the scorer's peak-weighted category methodology to a KPI subset.

    values: {kpi_id: value}. Returns 0-100 index or None if no data.
    """
    by_category: dict = {}
    for kpi in kpis:
        val = values.get(kpi["id"])
        if val is None:
            continue
        by_category.setdefault(kpi["category"], []).append(normalize_kpi(kpi, val))

    category_scores = {}
    for cat, subs in by_category.items():
        sorted_subs = sorted(subs, reverse=True)
        top_n = max(1, len(sorted_subs) // 3)
        top_avg = sum(sorted_subs[:top_n]) / top_n
        category_scores[cat] = 0.6 * top_avg + 0.4 * (sum(subs) / len(subs))

    if not category_scores:
        return None
    active_weight = sum(cat_weights.get(c, 0) for c in category_scores)
    if active_weight == 0:
        return None
    total = sum(
        score * (cat_weights.get(cat, 0) / active_weight)
        for cat, score in category_scores.items()
    ) * 100
    return round(min(max(total, 0.0), 100.0), 1)


def _diffusion(kpis: list, series_map: dict, as_of: date) -> Optional[dict]:
    """% of KPIs moving in the risk-increasing direction over 3 months."""
    prior_date = as_of - relativedelta(months=_DIFFUSION_MONTHS)
    deteriorating, improving, details = [], [], []
    for kpi in kpis:
        points = series_map.get(kpi["id"])
        if not points:
            continue
        now = _value_on_or_before(points, as_of)
        prior = _value_on_or_before(points, prior_date)
        if now is None or prior is None:
            continue
        delta = now - prior
        # invert=true → lower value = more risk, so a fall is deterioration
        risk_delta = -delta if kpi.get("invert", False) else delta
        worse = risk_delta > 0
        (deteriorating if worse else improving).append(kpi["id"])
        details.append({
            "kpi_id": kpi["id"],
            "name": kpi["name"],
            "category": kpi["category"],
            "value": now,
            "value_3m_ago": prior,
            "deteriorating": worse,
        })
    n = len(deteriorating) + len(improving)
    if n == 0:
        return None
    return {
        "diffusion_index": round(100.0 * len(deteriorating) / n, 1),
        "n_kpis": n,
        "n_deteriorating": len(deteriorating),
        "details": details,
    }


def compute_timing_snapshot(as_of: Optional[date] = None) -> dict:
    """Current leading/coincident indices + diffusion breadth for one date."""
    if as_of is None:
        as_of = date.today()
    config = _load_config()
    cat_weights = config["category_weights"]
    leading = _kpis_by_timing(config, "leading")
    coincident = _kpis_by_timing(config, "coincident")

    series_map = _load_series_map([k["id"] for k in leading + coincident])

    lead_values = {k["id"]: _value_on_or_before(series_map.get(k["id"], []), as_of)
                   for k in leading}
    coin_values = {k["id"]: _value_on_or_before(series_map.get(k["id"], []), as_of)
                   for k in coincident}

    diff = _diffusion(leading, series_map, as_of)
    return {
        "date": as_of.isoformat(),
        "leading_index": _composite_from_subscores(leading, lead_values, cat_weights),
        "coincident_index": _composite_from_subscores(coincident, coin_values, cat_weights),
        "diffusion_index": diff["diffusion_index"] if diff else None,
        "n_leading_kpis": diff["n_kpis"] if diff else 0,
        "n_deteriorating": diff["n_deteriorating"] if diff else 0,
        "leading_kpis": diff["details"] if diff else [],
    }


def compute_timing_history(from_date: date, end_date: Optional[date] = None) -> list:
    """Monthly leading/coincident/diffusion series.

    Loads each KPI's full series once, then evaluates every month in memory —
    ~230 months x ~70 KPIs stays well under a second.
    """
    if end_date is None:
        end_date = date.today()
    config = _load_config()
    cat_weights = config["category_weights"]
    leading = _kpis_by_timing(config, "leading")
    coincident = _kpis_by_timing(config, "coincident")
    series_map = _load_series_map([k["id"] for k in leading + coincident])

    results = []
    month = from_date.replace(day=1)
    while month <= end_date:
        lead_values = {k["id"]: _value_on_or_before(series_map.get(k["id"], []), month)
                       for k in leading}
        coin_values = {k["id"]: _value_on_or_before(series_map.get(k["id"], []), month)
                       for k in coincident}
        diff = _diffusion(leading, series_map, month)
        results.append({
            "date": month.isoformat(),
            "leading_index": _composite_from_subscores(leading, lead_values, cat_weights),
            "coincident_index": _composite_from_subscores(coincident, coin_values, cat_weights),
            "diffusion_index": diff["diffusion_index"] if diff else None,
        })
        month = month + relativedelta(months=1)
    return results
