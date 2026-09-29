"""
Recession Risk Score computation.

Each KPI is normalized to a 0.0–1.0 sub-score based on its current value
relative to warning/danger thresholds. Category scores are averaged across
KPIs in that category, then multiplied by the category weight and summed
to produce the final 0–100 score.
"""

import json
import logging
import os
from datetime import date, datetime
from typing import Optional

import yaml

from backend.models import KpiData, KpiSnapshot, RecessionScore, get_session

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "kpi_config.yaml")


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# KPI normalization
# ---------------------------------------------------------------------------

def normalize_kpi(kpi: dict, value: float) -> float:
    """
    Return a 0.0–1.0 recession risk sub-score for the given KPI value.

    0.0 = healthy / no risk signal
    1.0 = maximum risk / threshold fully breached

    Logic:
      - If invert=True: LOWER value = MORE risk (e.g. GDP growth, confidence)
      - If invert=False: HIGHER value = MORE risk (e.g. unemployment, VIX)
      - warning_threshold → 0.4 sub-score
      - danger_threshold  → 1.0 sub-score
      - Values between thresholds are interpolated linearly.
    """
    warn = kpi.get("warning_threshold")
    danger = kpi.get("danger_threshold")
    invert = kpi.get("invert", False)

    if warn is None and danger is None:
        return 0.0   # No thresholds defined — cannot score

    # Special case: Sahm Rule gets a hard boost when triggered
    if kpi.get("id") == "sahm_rule" and value >= 0.5:
        return 1.0

    if warn is None:
        warn = danger  # treat as single threshold

    if danger is None:
        danger = warn

    if invert:
        # Lower value = more risk: flip the comparison axis.
        # warn > danger for inverted KPIs (e.g. warn=14.0, danger=12.0 SAAR).
        if value <= danger:
            return 1.0
        if value > warn:           # exclusive so value==warn → 0.4 (onset of risk)
            return 0.0
        # Linear scale: warn → 0.4, danger → 1.0
        span = warn - danger
        if span == 0:
            return 1.0
        return 0.4 + 0.6 * (warn - value) / span
    else:
        # Higher value = more risk.
        # warn < danger for standard KPIs (e.g. warn=90, danger=110 WTI).
        if value >= danger:
            return 1.0
        if value < warn:           # exclusive so value==warn → 0.4 (onset of risk)
            return 0.0
        # Linear scale: warn → 0.4, danger → 1.0
        span = danger - warn
        if span == 0:
            return 1.0
        return 0.4 + 0.6 * (value - warn) / span


# ---------------------------------------------------------------------------
# Fetch latest value for a KPI from DB
# ---------------------------------------------------------------------------

def _latest_value(kpi_id: str) -> Optional[float]:
    session = get_session()
    try:
        row = (
            session.query(KpiData.value)
            .filter_by(kpi_id=kpi_id)
            .order_by(KpiData.date.desc())
            .first()
        )
        return row[0] if row else None
    finally:
        session.close()


def _value_as_of(kpi_id: str, as_of_date: date) -> Optional[float]:
    """Return the most recent value for kpi_id on or before as_of_date."""
    session = get_session()
    try:
        row = (
            session.query(KpiData.value)
            .filter(KpiData.kpi_id == kpi_id, KpiData.date <= as_of_date)
            .order_by(KpiData.date.desc())
            .first()
        )
        return row[0] if row else None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Compute composite score
# ---------------------------------------------------------------------------

def score_from_values(config: dict, values: dict) -> dict:
    """
    Pure scoring core: map {kpi_id: value} onto the composite 0–100 score.

    Single source of truth for the scoring methodology — used by
    compute_recession_score (DB lookups) and by backend.score_history (fast
    in-memory history and day-over-day driver attribution). KPIs missing from
    `values` (or None) are skipped, exactly as a missing DB row is.

    Returns a dict with:
      score           : float 0–100 (rounded to 0.1)
      score_raw       : float 0–100 (unrounded)
      band            : str
      category_scores : dict category -> float 0–1 (unrounded)
      active_weight   : sum of weights of categories with data (the
                        renormalisation denominator)
      contributions   : list of per-KPI dicts (kpi_id, name, category, value,
                        sub_score, weighted_contribution), unsorted
    """
    kpis = config["kpis"]
    cat_weights = config["category_weights"]

    # Group KPIs by category
    by_category: dict[str, list] = {cat: [] for cat in cat_weights}
    for kpi in kpis:
        cat = kpi.get("category")
        if cat in by_category:
            by_category[cat].append(kpi)

    category_scores = {}
    categories_with_data = set()
    contributions = []

    for cat, cat_kpis in by_category.items():
        sub_scores = []
        for kpi in cat_kpis:
            val = values.get(kpi["id"])
            if val is None:
                continue
            sub = normalize_kpi(kpi, val)
            sub_scores.append(sub)
            contributions.append({
                "kpi_id": kpi["id"],
                "name": kpi["name"],
                "category": cat,
                "value": val,
                "sub_score": sub,
            })

        if sub_scores:
            # Peak-weighted scoring: blend mean with top-third average so that
            # a small number of danger signals still move the category score meaningfully.
            sorted_scores = sorted(sub_scores, reverse=True)
            top_n = max(1, len(sorted_scores) // 3)
            top_avg = sum(sorted_scores[:top_n]) / top_n
            mean_avg = sum(sub_scores) / len(sub_scores)
            category_scores[cat] = 0.6 * top_avg + 0.4 * mean_avg
            categories_with_data.add(cat)
        # Categories with no data are excluded entirely (not scored as 0)

    # Weighted sum → 0–100, redistributing weight across categories that have data
    active_weight = sum(w for cat, w in cat_weights.items() if cat in categories_with_data)
    if active_weight == 0:
        total = 0.0
    else:
        total = sum(
            category_scores[cat] * (cat_weights[cat] / active_weight)
            for cat in categories_with_data
        ) * 100

    score_raw = min(max(total, 0.0), 100.0)
    score = round(score_raw, 1)
    band = get_risk_band(score)

    # Add weighted contribution to each KPI record
    for rec in contributions:
        cat = rec["category"]
        cat_weight = cat_weights.get(cat, 0)
        # Count KPIs that actually contributed a sub_score (respects overrides)
        cat_kpi_count = sum(1 for r in contributions if r["category"] == cat)
        if cat_kpi_count > 0:
            rec["weighted_contribution"] = (
                rec["sub_score"] / cat_kpi_count * cat_weight * 100
            )
        else:
            rec["weighted_contribution"] = 0.0

    return {
        "score": score,
        "score_raw": score_raw,          # unrounded — for attribution deltas
        "band": band,
        "category_scores": category_scores,
        "active_weight": active_weight,
        "contributions": contributions,
    }


def compute_recession_score(
    as_of_date: Optional[date] = None,
    kpi_value_overrides: Optional[dict] = None,
) -> dict:
    """
    Compute the Recession Risk Score and persist it to the DB.

    Parameters
    ----------
    as_of_date         : If provided, use DB values on or before this date
                         (Time Machine / historical simulation mode).
    kpi_value_overrides: If provided, a dict {kpi_id: value} that replaces the
                         DB lookup for those KPIs.  Used by the forecast endpoint
                         to substitute projected values.  When overrides are
                         supplied the result is NOT persisted to the DB.

    Returns a dict with:
      score        : float 0–100
      band         : str  LOW | ELEVATED | HIGH | CRITICAL
      category_scores: dict of category -> float 0–100
      kpi_contributions: list of (kpi_id, value, sub_score, weighted_contribution)
    """
    config = _load_config()

    values = {}
    for kpi in config["kpis"]:
        if kpi.get("category") not in config["category_weights"]:
            continue
        if kpi_value_overrides and kpi["id"] in kpi_value_overrides:
            val = kpi_value_overrides[kpi["id"]]
        elif as_of_date is not None:
            val = _value_as_of(kpi["id"], as_of_date)
        else:
            val = _latest_value(kpi["id"])
        values[kpi["id"]] = val

    result = score_from_values(config, values)
    score = result["score"]
    band = result["band"]
    category_scores = result["category_scores"]
    contributions = result["contributions"]

    # Persist to DB only in live (non-simulation) mode and no overrides
    if as_of_date is None and not kpi_value_overrides:
        _save_score(score, band, category_scores=category_scores,  # 0–1 scale
                    contributions=contributions)

    if as_of_date is not None:
        logger.info("Simulated score as of %s: %.1f (%s)", as_of_date, score, band)
    else:
        logger.info("Recession Risk Score: %.1f (%s)", score, band)
    return {
        "score": score,
        "band": band,
        "category_scores": {k: round(v * 100, 1) for k, v in category_scores.items()},
        # Unrounded 0–100 — the ML models' input. The live /api/score path feeds
        # them the unrounded stored breakdown; rounding first shifts the
        # probability by ~0.1 pt, so the Time Machine card and the chart disagreed.
        "category_scores_raw": {k: v * 100 for k, v in category_scores.items()},
        "kpi_contributions": sorted(
            contributions, key=lambda x: x["weighted_contribution"], reverse=True
        ),
    }


def get_risk_band(score: float) -> str:
    if score >= 75:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "ELEVATED"
    return "LOW"


def _save_score(score: float, band: str, category_scores: dict = None,
                contributions: Optional[list] = None) -> None:
    """Upsert today's live score, plus (when given) today's per-KPI snapshot.

    The per-KPI snapshot is what makes "what changed since yesterday" exact:
    a reconstructed as-of-yesterday score already contains today's releases
    (they are back-dated to their period start) and today's revisions, so
    only the values the dashboard actually used each day can be diffed.
    """
    session = get_session()
    today = date.today()
    now = datetime.utcnow()
    breakdown_json = json.dumps(category_scores) if category_scores else None
    try:
        existing = session.query(RecessionScore).filter_by(date=today).first()
        if existing:
            existing.score = score
            existing.band = band
            existing.computed_at = now
            existing.category_breakdown = breakdown_json
        else:
            session.add(RecessionScore(
                date=today, score=score, band=band,
                computed_at=now, category_breakdown=breakdown_json
            ))
        if contributions is not None:
            # Replace today's snapshot wholesale so a KPI that lost its value
            # since the last refresh today does not leave a stale row behind.
            session.query(KpiSnapshot).filter(KpiSnapshot.date == today).delete()
            for rec in contributions:
                session.add(KpiSnapshot(
                    date=today, kpi_id=rec["kpi_id"], value=rec["value"],
                    sub_score=rec["sub_score"], computed_at=now,
                ))
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Failed to save recession score: %s", exc)
    finally:
        session.close()
