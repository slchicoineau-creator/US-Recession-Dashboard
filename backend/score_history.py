"""
High-resolution score history and day-over-day score attribution.

Two features built on scorer.score_from_values (the single scoring core):

  Zoomed history  - /api/score/history?resolution=5y|2y|1y. The monthly
                    history (since 2007) calls compute_recession_score once per
                    month, i.e. ~80 DB queries per point, and caches rows in
                    RecessionScore. The zoomed views need ~260 points each, so
                    they load every KPI series once and evaluate each date in
                    memory instead. Nothing is persisted: RecessionScore also
                    holds the live daily rows, and caching reconstructed rows
                    there would mix the two.

  Score drivers   - /api/score/drivers. Which KPIs moved the score between two
                    days, and by how much.

Why drivers diff *snapshots*, not reconstructions
-------------------------------------------------
A reconstructed "as of yesterday" score is computed from today's KpiData.
Monthly releases are dated to their period start (August payrolls are stored
as 2026-08-01, published in September) and revisions overwrite stored values,
so the reconstruction for yesterday already contains today's news. Measured on
2026-09-25: the live gauge went 39.3 -> 40.3, but reconstruction said
40.4 -> 40.3 — the wrong sign. Live mode therefore diffs the per-KPI
KpiSnapshot rows written by each live refresh (scorer._save_score). Time
Machine mode has no snapshots for the past, so it uses reconstruction, and the
payload says so.
"""

import json
import logging
from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
from dateutil.relativedelta import relativedelta
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from backend.models import KpiData, KpiSnapshot, RecessionScore, get_session
from backend.scorer import _load_config, score_from_values

logger = logging.getLogger(__name__)

# Business days = Mon–Fri excluding US federal holidays (the calendar FRED
# publication schedules follow).
_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())

# Zoom levels: look-back and sampling step.
RESOLUTIONS = {
    "5y": {"years": 5, "kind": "weekly", "step": 1, "label": "weekly"},
    "2y": {"years": 2, "kind": "bday", "step": 2, "label": "every other business day"},
    "1y": {"years": 1, "kind": "bday", "step": 1, "label": "every business day"},
}

# A KPI whose impact on the score is below this (in score points) is reported
# as "updated, no score impact" rather than as a driver.
DRIVER_MIN_IMPACT = 0.05


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def sample_dates(resolution: str, end_date: date) -> list:
    """Evaluation dates for a zoom level, ascending, always ending at end_date.

    Stepping is anchored at end_date and walks backwards, so the newest point
    is exactly end_date (and therefore equals the live gauge in live mode).
    Consequence for the every-other-business-day grid: which days are sampled
    alternates from one day to the next. end_date is included even when it is
    a weekend/holiday, for the same reason.
    """
    spec = RESOLUTIONS[resolution]
    start = end_date - relativedelta(years=spec["years"])
    if spec["kind"] == "weekly":
        out = []
        d = end_date
        while d >= start:
            out.append(d)
            d -= timedelta(days=7)
        return out[::-1]

    days = [ts.date() for ts in pd.date_range(start, end_date, freq=_BDAY)]
    newest_first = days[::-1]
    if not newest_first or newest_first[0] != end_date:
        newest_first.insert(0, end_date)
    return newest_first[::spec["step"]][::-1]


def previous_business_day(d: date) -> date:
    return (pd.Timestamp(d) - _BDAY).date()


# ---------------------------------------------------------------------------
# In-memory series index — exact equivalent of scorer._value_as_of
# ---------------------------------------------------------------------------

class _SeriesIndex:
    """All KpiData rows for a set of KPIs, searchable by date.

    Deliberately NOT leading._value_on_or_before: that caps carry-forward at
    370 days, while the scorer's _value_as_of has no cap. The history must
    match compute_recession_score(as_of_date=d) exactly (pytest-enforced).
    """

    def __init__(self, kpi_ids: list):
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
        self._dates: dict = {}
        self._values: dict = {}
        for kpi_id, dt, val in rows:
            self._dates.setdefault(kpi_id, []).append(dt)
            self._values.setdefault(kpi_id, []).append(val)

    def value_as_of(self, kpi_id: str, as_of: Optional[date]) -> Optional[float]:
        """Latest value on/before as_of; as_of=None means latest overall."""
        dates = self._dates.get(kpi_id)
        if not dates:
            return None
        if as_of is None:
            return self._values[kpi_id][-1]
        i = bisect_right(dates, as_of)
        return self._values[kpi_id][i - 1] if i else None


def _scored_kpi_ids(config: dict) -> list:
    weights = config["category_weights"]
    return [k["id"] for k in config["kpis"] if k.get("category") in weights]


# ---------------------------------------------------------------------------
# Zoomed history
# ---------------------------------------------------------------------------

def _published_scores(start: date, end: date) -> dict:
    """{date: score} for rows the live refresh actually wrote on that day.

    RecessionScore mixes live rows with monthly history-cache rows (computed
    later, as reconstructions). A live row is computed on its own date — or
    the next UTC day, since computed_at is UTC and a late-evening local
    refresh lands after midnight UTC.
    """
    session = get_session()
    try:
        rows = (
            session.query(RecessionScore.date, RecessionScore.score, RecessionScore.computed_at)
            .filter(RecessionScore.date >= start, RecessionScore.date <= end)
            .all()
        )
    finally:
        session.close()
    out = {}
    for d, score, computed_at in rows:
        if computed_at is not None and 0 <= (computed_at.date() - d).days <= 1:
            out[d] = score
    return out


def compute_zoomed_history(resolution: str, end_date: date, include_ml: bool = False) -> list:
    """Reconstructed score at every sample date of a zoom level.

    Each point = compute_recession_score(as_of_date=d), computed from one bulk
    load. Points also carry `published` (the score the live dashboard actually
    showed that day) where a live row exists — reconstruction uses today's
    revised data and back-dated releases, so the two can legitimately differ.
    """
    if resolution not in RESOLUTIONS:
        raise ValueError(f"unknown resolution {resolution!r}")
    config = _load_config()
    kpi_ids = _scored_kpi_ids(config)
    index = _SeriesIndex(kpi_ids)
    dates = sample_dates(resolution, end_date)
    published = _published_scores(dates[0], dates[-1]) if dates else {}

    results = []
    ml_inputs = []
    for d in dates:
        values = {kid: index.value_as_of(kid, d) for kid in kpi_ids}
        r = score_from_values(config, values)
        item = {"date": d.isoformat(), "score": r["score"], "band": r["band"]}
        if d in published:
            item["published"] = published[d]
        # ML models take the 0–100 category scale, unrounded — the same input
        # /api/score feeds them, so the last point matches the card exactly.
        ml_inputs.append({k: v * 100 for k, v in r["category_scores"].items()})
        results.append(item)

    if include_ml:
        # ml_score = "now" (coincident) probability; ml_12m = the headline
        # "within 12 months" probability shown in the Recession Probability card.
        from backend.ml_scorer import compute_ml_scores_batch
        for key, horizon in (("ml_score", "now"), ("ml_6m", "6m"), ("ml_12m", "12m")):
            for item, p in zip(results, compute_ml_scores_batch(ml_inputs, horizon)):
                item[key] = p
    return results


# ---------------------------------------------------------------------------
# Score drivers (day-over-day attribution)
# ---------------------------------------------------------------------------

def _category_contributions(category_scores: dict, cat_weights: dict) -> dict:
    """Each category's share of the 0–100 score (sums to the unclamped score)."""
    active = sum(cat_weights.get(c, 0) for c in category_scores)
    if not active:
        return {}
    return {c: s * cat_weights.get(c, 0) / active * 100 for c, s in category_scores.items()}


def attribute_change(config: dict, from_values: dict, to_values: dict) -> dict:
    """Explain score(to) - score(from) per KPI and per category.

    KPI impact = score(to) - score(to with only this KPI reverted to its
    `from` value, or removed if it had none). This answers "how much lower
    would today's score be if this KPI had not moved". Because the category
    score blends a top-third average with the mean and weights renormalise over
    categories with data, the impacts need not sum to the total; the
    remainder is reported as `interaction`. The per-category split is exact
    whenever the set of categories with data is unchanged.
    """
    cat_weights = config["category_weights"]
    to_r = score_from_values(config, to_values)
    from_r = score_from_values(config, from_values)
    delta = to_r["score_raw"] - from_r["score_raw"]

    subs_to = {c["kpi_id"]: c["sub_score"] for c in to_r["contributions"]}
    subs_from = {c["kpi_id"]: c["sub_score"] for c in from_r["contributions"]}
    meta = {k["id"]: k for k in config["kpis"]}

    kpis = []
    for kid in _scored_kpi_ids(config):
        v0, v1 = from_values.get(kid), to_values.get(kid)
        if v0 is None and v1 is None:
            continue
        if v0 is not None and v1 is not None and abs(v1 - v0) <= 1e-12:
            continue
        reverted = dict(to_values)
        reverted[kid] = v0
        impact = to_r["score_raw"] - score_from_values(config, reverted)["score_raw"]
        kpi = meta[kid]
        kpis.append({
            "kpi_id": kid,
            "name": kpi["name"],
            "category": kpi["category"],
            "unit": kpi.get("unit"),
            "value_from": v0,
            "value_to": v1,
            "sub_score_from": subs_from.get(kid),
            "sub_score_to": subs_to.get(kid),
            "impact": impact,
        })
    kpis.sort(key=lambda k: k["impact"], reverse=True)

    contrib_to = _category_contributions(to_r["category_scores"], cat_weights)
    contrib_from = _category_contributions(from_r["category_scores"], cat_weights)
    categories = [
        {
            "id": c,
            "score_from": round(from_r["category_scores"][c] * 100, 1) if c in from_r["category_scores"] else None,
            "score_to": round(to_r["category_scores"][c] * 100, 1) if c in to_r["category_scores"] else None,
            "impact": contrib_to.get(c, 0.0) - contrib_from.get(c, 0.0),
        }
        for c in cat_weights
        if c in contrib_to or c in contrib_from
    ]
    categories.sort(key=lambda c: c["impact"], reverse=True)

    return {
        "score_from": from_r["score"],
        "score_to": to_r["score"],
        "delta": round(delta, 2),
        "kpis": kpis,
        "categories": categories,
        "interaction": round(delta - sum(k["impact"] for k in kpis), 3),
    }


def _snapshot_dates(session, before: Optional[date] = None, limit: int = 2) -> list:
    q = session.query(KpiSnapshot.date).distinct()
    if before is not None:
        q = q.filter(KpiSnapshot.date < before)
    return [r[0] for r in q.order_by(KpiSnapshot.date.desc()).limit(limit).all()]


def _load_snapshot(session, d: date) -> dict:
    return {
        r.kpi_id: r.value
        for r in session.query(KpiSnapshot.kpi_id, KpiSnapshot.value)
        .filter(KpiSnapshot.date == d).all()
    }


def _category_only_fallback(config: dict, session) -> Optional[dict]:
    """Exact category-level attribution from the two newest live score rows.

    Used before two per-KPI snapshots exist (the snapshot table is new). The
    live RecessionScore rows have stored each day's category breakdown since
    the scheduler started writing them, so the category split is still exact.
    """
    cat_weights = config["category_weights"]
    rows = (
        session.query(RecessionScore)
        .filter(RecessionScore.date <= date.today(),
                RecessionScore.category_breakdown.isnot(None))
        .order_by(RecessionScore.date.desc())
        .limit(40)
        .all()
    )
    live = [r for r in rows
            if r.computed_at is not None and 0 <= (r.computed_at.date() - r.date).days <= 1]
    if len(live) < 2:
        return None
    to_row, from_row = live[0], live[1]
    cs_to = json.loads(to_row.category_breakdown)
    cs_from = json.loads(from_row.category_breakdown)
    contrib_to = _category_contributions(cs_to, cat_weights)
    contrib_from = _category_contributions(cs_from, cat_weights)
    categories = [
        {
            "id": c,
            "score_from": round(cs_from[c] * 100, 1) if c in cs_from else None,
            "score_to": round(cs_to[c] * 100, 1) if c in cs_to else None,
            "impact": contrib_to.get(c, 0.0) - contrib_from.get(c, 0.0),
        }
        for c in cat_weights
        if c in contrib_to or c in contrib_from
    ]
    categories.sort(key=lambda c: c["impact"], reverse=True)
    first_snap = session.query(KpiSnapshot.date).order_by(KpiSnapshot.date).first()
    return {
        "basis": "category_only",
        "first_snapshot_date": first_snap[0].isoformat() if first_snap else None,
        "from_date": from_row.date.isoformat(),
        "to_date": to_row.date.isoformat(),
        "score_from": from_row.score,
        "score_to": to_row.score,
        "delta": round(to_row.score - from_row.score, 2),
        "kpis": [],
        "categories": categories,
        "interaction": None,
    }


def compute_drivers(as_of: Optional[date] = None) -> dict:
    """What moved the score between the two most recent days.

    Live mode (as_of None): newest KpiSnapshot vs the one before it (basis
    "snapshot"); if fewer than two snapshots exist, category-level only from
    the live score rows (basis "category_only").
    Time Machine: reconstruction at as_of vs the previous business day
    (basis "reconstructed").
    """
    config = _load_config()

    if as_of is not None:
        index = _SeriesIndex(_scored_kpi_ids(config))
        prev = previous_business_day(as_of)
        ids = _scored_kpi_ids(config)
        result = attribute_change(
            config,
            {k: index.value_as_of(k, prev) for k in ids},
            {k: index.value_as_of(k, as_of) for k in ids},
        )
        result.update(basis="reconstructed", from_date=prev.isoformat(), to_date=as_of.isoformat())
        return result

    session = get_session()
    try:
        dates = _snapshot_dates(session, before=date.today() + timedelta(days=1))
        if len(dates) >= 2:
            to_d, from_d = dates[0], dates[1]
            result = attribute_change(config, _load_snapshot(session, from_d),
                                      _load_snapshot(session, to_d))
            result.update(basis="snapshot", from_date=from_d.isoformat(), to_date=to_d.isoformat())
            return result
        fallback = _category_only_fallback(config, session)
    finally:
        session.close()
    if fallback is not None:
        return fallback
    return {"basis": "none", "from_date": None, "to_date": None, "score_from": None,
            "score_to": None, "delta": None, "kpis": [], "categories": [], "interaction": None}
