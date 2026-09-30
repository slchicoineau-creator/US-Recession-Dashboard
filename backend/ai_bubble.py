"""
AI Bubble Monitor.

The composite Recession Risk Score measures how LIKELY a recession is. This
module answers a narrower market question: how large is the AI-led equity
bubble, and is it breaking? It reports two separate 0-100 readings instead of
one blend, because the useful answer is the combination:

  exposure  - how big and stretched the bubble is: tech capex share of GDP,
              market concentration, CAPE, market cap / GDP. Levels that can
              stay high for years.
  puncture  - whether it is deflating: semiconductors, the S&P 500 and listed
              private-credit lenders breaking below their 200-day averages,
              junk-bond spreads widening.

High exposure + low puncture = inflated but intact (1999, 2021, Sep 2026).
High exposure + rising puncture = bursting (2000-02, 2022).

Exposure falls as prices fall (CAPE and market cap / GDP shrink in a crash),
so the verdict judges "was there a bubble" by the PEAK exposure of the
trailing 12 months, not today's reading. Without that, 2022 read as generic
"market stress" by June, although exposure had been HIGH in Dec 2021.

Component definitions live in kpi_config.yaml under `ai_bubble:` (FRD
Appendix C rule 1). Scoring reuses the Depression Severity interpolation:
each component maps a stored KPI value onto 0-1 between `healthy` and
`extreme`, and missing components are renormalised away.

Nothing here feeds the composite, the ML models or the alerts.

Bands:
  exposure  0-24 LOW      25-49 MODERATE  50-74 HIGH      75+ EXTREME
  puncture  0-24 INTACT   25-49 CRACKING  50-74 BREAKING  75+ BURSTING
"""

import logging
from datetime import date
from typing import Optional

from backend.leading import _load_series_map, _value_on_or_before
from backend.scorer import _load_config
from backend.severity import component_subscore

logger = logging.getLogger(__name__)

GAUGES = ("exposure", "puncture")
_PEAK_LOOKBACK_MONTHS = 12

_BANDS = {
    "exposure": ("LOW", "MODERATE", "HIGH", "EXTREME"),
    "puncture": ("INTACT", "CRACKING", "BREAKING", "BURSTING"),
}


def get_band(gauge: str, score: float) -> str:
    low, mid, high, top = _BANDS[gauge]
    if score >= 75:
        return top
    if score >= 50:
        return high
    if score >= 25:
        return mid
    return low


def _verdict(exposure: Optional[float], puncture: Optional[float]) -> Optional[str]:
    """`exposure` should be the trailing-12-month peak (see module docstring)."""
    if exposure is None or puncture is None:
        return None
    if puncture >= 50:
        return "Bursting" if exposure >= 50 else "Market stress"
    if puncture >= 25:
        return "Cracks forming" if exposure >= 50 else "Minor stress"
    if exposure >= 50:
        return "Inflated but intact"
    return "No bubble signal"


def _all_kpi_ids(cfg: dict) -> list:
    return sorted({c["kpi_id"] for g in GAUGES for c in cfg.get(g, [])})


def _score_gauge(gauge: str, components_cfg: list, series_map: dict,
                 as_of: date, kpi_names: dict, with_components: bool = True) -> dict:
    total = 0.0
    active_weight = 0.0
    components = []
    for cfg in components_cfg:
        value = _value_on_or_before(series_map.get(cfg["kpi_id"], []), as_of)
        sub = None
        if value is not None:
            sub = component_subscore(value, float(cfg["healthy"]), float(cfg["extreme"]))
            total += sub * float(cfg["weight"])
            active_weight += float(cfg["weight"])
        if with_components:
            components.append({
                "kpi_id": cfg["kpi_id"],
                "name": kpi_names.get(cfg["kpi_id"], cfg["kpi_id"]),
                "label": cfg["label"],
                "value": value,
                "sub_score": round(sub, 3) if sub is not None else None,
                "weight": cfg["weight"],
            })
    score = round(total / active_weight * 100.0, 1) if active_weight > 0 else None
    out = {
        "score": score,
        "band": get_band(gauge, score) if score is not None else None,
        "coverage": round(active_weight, 3),
    }
    if with_components:
        out["components"] = components
    return out


def compute_ai_bubble(as_of: Optional[date] = None) -> dict:
    """Exposure + puncture readings for one date (Time-Machine aware)."""
    if as_of is None:
        as_of = date.today()
    config = _load_config()
    cfg = config.get("ai_bubble", {})
    kpi_names = {k["id"]: k["name"] for k in config.get("kpis", [])}
    series_map = _load_series_map(_all_kpi_ids(cfg))

    result = {"date": as_of.isoformat()}
    for gauge in GAUGES:
        result[gauge] = _score_gauge(gauge, cfg.get(gauge, []), series_map, as_of, kpi_names)
    peak = _exposure_peak(cfg, series_map, as_of, result["exposure"]["score"])
    result["exposure_peak_12m"] = peak
    result["verdict"] = _verdict(peak, result["puncture"]["score"])
    return result


def _exposure_peak(cfg: dict, series_map: dict, as_of: date,
                   current: Optional[float]) -> Optional[float]:
    """Max exposure over as_of and the 12 prior month-starts."""
    scores = [current] if current is not None else []
    for back in range(1, _PEAK_LOOKBACK_MONTHS + 1):
        y, m = as_of.year, as_of.month - back
        while m < 1:
            y, m = y - 1, m + 12
        s = _score_gauge("exposure", cfg.get("exposure", []), series_map,
                         date(y, m, 1), {}, with_components=False)["score"]
        if s is not None:
            scores.append(s)
    return max(scores) if scores else None


def compute_ai_bubble_history(from_date: date, end_date: Optional[date] = None) -> list:
    """Month-start series of both readings (each KPI series loaded once)."""
    if end_date is None:
        end_date = date.today()
    config = _load_config()
    cfg = config.get("ai_bubble", {})
    series_map = _load_series_map(_all_kpi_ids(cfg))

    rows = []
    month = from_date.replace(day=1)
    while month <= end_date:
        row = {"date": month.isoformat()}
        for gauge in GAUGES:
            g = _score_gauge(gauge, cfg.get(gauge, []), series_map, month, {},
                             with_components=False)
            row[gauge] = g["score"]
        rows.append(row)
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return rows
