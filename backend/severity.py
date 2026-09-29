"""
Depression Severity score.

The composite Recession Risk Score measures how LIKELY a downturn is; this
module measures how SEVERE the current regime would make one. Ordinary
recessions do not exhibit debt-deflation dynamics — outright deflation,
contracting bank credit, shrinking money supply, depression-scale unemployment
— and when the composite has been pinned at CRITICAL for months, the downturn
is persistent rather than a shock.

Component definitions live in kpi_config.yaml under `severity:` (rule 1 of
FRD Appendix C — no KPI-specific logic in Python). Each component maps a
stored post-transform KPI value onto a 0-1 sub-score by linear interpolation
between `healthy` (0.0) and `extreme` (1.0); direction is inferred from which
bound is larger. The persistence component counts months at CRITICAL composite
in the trailing 12.

Bands:
  0-24   NORMAL           - no depression dynamics present
  25-49  SERIOUS          - some debt-deflation signals emerging
  50-74  SEVERE           - broad severe-downturn dynamics (2009-like)
  75-100 DEPRESSION-SCALE - analogous to the early 1930s
"""

import logging
from datetime import date, timedelta
from typing import Optional

from backend.leading import _load_series_map, _value_on_or_before
from backend.models import RecessionScore, get_session
from backend.scorer import _load_config

logger = logging.getLogger(__name__)

_PERSISTENCE_WINDOW_MONTHS = 12
_CRITICAL_THRESHOLD = 75.0


def component_subscore(value: float, healthy: float, extreme: float) -> float:
    """Linear 0-1 interpolation between healthy (0) and extreme (1).

    Direction is inferred: extreme < healthy means lower values are worse.
    Values beyond the bounds clip to 0 / 1.
    """
    if healthy == extreme:
        return 1.0 if value == extreme else 0.0
    frac = (value - healthy) / (extreme - healthy)
    return min(max(frac, 0.0), 1.0)


def get_severity_band(score: float) -> str:
    if score >= 75:
        return "DEPRESSION-SCALE"
    if score >= 50:
        return "SEVERE"
    if score >= 25:
        return "SERIOUS"
    return "NORMAL"


def _persistence_months(as_of: date) -> int:
    """Distinct calendar months in the trailing 12 with composite >= CRITICAL."""
    window_start = as_of - timedelta(days=365)
    session = get_session()
    try:
        rows = (
            session.query(RecessionScore.date, RecessionScore.score)
            .filter(
                RecessionScore.date > window_start,
                RecessionScore.date <= as_of,
                RecessionScore.score >= _CRITICAL_THRESHOLD,
            )
            .all()
        )
    finally:
        session.close()
    return len({(r.date.year, r.date.month) for r in rows})


def compute_severity(as_of: Optional[date] = None) -> dict:
    """Compute the Depression Severity score for one date."""
    if as_of is None:
        as_of = date.today()
    config = _load_config()
    sev_cfg = config.get("severity", {})
    components_cfg = sev_cfg.get("components", [])
    persistence_weight = float(sev_cfg.get("persistence_weight", 0.0))

    kpi_names = {k["id"]: k["name"] for k in config.get("kpis", [])}
    series_map = _load_series_map([c["kpi_id"] for c in components_cfg])

    components = []
    total = 0.0
    active_weight = 0.0
    for cfg in components_cfg:
        value = _value_on_or_before(series_map.get(cfg["kpi_id"], []), as_of)
        sub = None
        if value is not None:
            sub = component_subscore(value, float(cfg["healthy"]), float(cfg["extreme"]))
            total += sub * float(cfg["weight"])
            active_weight += float(cfg["weight"])
        components.append({
            "kpi_id": cfg["kpi_id"],
            "name": kpi_names.get(cfg["kpi_id"], cfg["kpi_id"]),
            "label": cfg["label"],
            "value": value,
            "sub_score": round(sub, 3) if sub is not None else None,
            "weight": cfg["weight"],
        })

    persistence = _persistence_months(as_of)
    persistence_sub = min(persistence / 6.0, 1.0)   # 6+ months at CRITICAL = max
    total += persistence_sub * persistence_weight
    active_weight += persistence_weight

    # Renormalize over components that actually had data so one missing KPI
    # doesn't deflate the score.
    score = round((total / active_weight) * 100.0, 1) if active_weight > 0 else None

    return {
        "date": as_of.isoformat(),
        "severity_score": score,
        "severity_band": get_severity_band(score) if score is not None else None,
        "components": components,
        "persistence_months_critical": persistence,
        "persistence_sub_score": round(persistence_sub, 3),
        "persistence_weight": persistence_weight,
    }
