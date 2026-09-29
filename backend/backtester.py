"""
Backtest & calibration metrics for the dashboard's recession signals.

Evaluates each signal's monthly history against NBER recessions:

  composite     - rules-based Recession Risk Score (alarm threshold: 50 = HIGH)
  leading_index - leading-KPI composite               (alarm threshold: 50)
  ml_12m        - Logit P(recession within 12 months), IN-SAMPLE (the live
                  model, trained on the same months it is scored on)
  ml_6m         - Logit P(recession within 6 months), IN-SAMPLE
  ml_12m_wf     - the same Logit, WALK-FORWARD: refit each month on labels
                  public at the time (ml_scorer.walk_forward_ml)
  ml_6m_wf      - 6-month walk-forward
  yield_curve   - NY Fed-style yield-curve probit, walk-forward, fit on 1959+
                  (backend/benchmarks.py)
  chauvet_piger - FRED smoothed recession probability. RETROSPECTIVE and
                  coincident: shown for reference, excluded from the
                  common-window comparison.

Per signal:
  lead_months        - for each NBER recession onset in the window, months
                       between the first alarm inside the preceding
                       (horizon + 6) months — 18 for 12-month signals/scores
                       and the onset (status: led | missed | no_data |
                       not_applicable for coincident signals)
  false_alarm_episodes - runs of consecutive alarm months that neither overlap
                       a recession nor precede an onset within that window
  auroc              - area under the ROC curve of monthly signal values vs
                       the "recession within 12 months" label (higher = the
                       signal separates pre-recession months from calm ones)

Probability signals also get a Brier score (against their own horizon's
label), a Brier skill score vs. a constant base rate, and a 10-bin
calibration table. A common-window block re-scores every forecast signal on
only the months where ALL of them have a value, so rows are comparable
(walk-forward ML has no prediction until years into the window).

Honesty caveat surfaced in the API payload: histories are computed from
today's revised data, not real-time vintages, so lead times are optimistic
relative to what the dashboard would have shown live.
"""

import json
import logging
import threading
import time
from datetime import date, datetime
from typing import Optional

import numpy as np

from backend.models import NberRecession, RecessionScore, get_session

logger = logging.getLogger(__name__)

ALARM_THRESHOLDS = {
    "composite": 50.0,      # HIGH band
    "leading_index": 50.0,
    "ml_12m": 50.0,
    "ml_6m": 50.0,
    "ml_12m_wf": 50.0,
    "ml_6m_wf": 50.0,
    "yield_curve": 50.0,
    "chauvet_piger": 50.0,
}

SIGNAL_NAMES = {
    "composite": "Recession Risk Score (rules-based)",
    "leading_index": "Leading Indicator Index",
    "ml_12m": "P(recession within 12 mo) — Logit (in-sample)",
    "ml_6m": "P(recession within 6 mo) — Logit (in-sample)",
    "ml_12m_wf": "P(recession within 12 mo) — Logit (walk-forward)",
    "ml_6m_wf": "P(recession within 6 mo) — Logit (walk-forward)",
    "yield_curve": "Yield-curve probit, NY Fed method (walk-forward)",
    "chauvet_piger": "Chauvet–Piger smoothed probability (retrospective)",
}

# kind:       "score" (0-100 index, no probability metrics) | "probability" (%)
# validation: rules | in-sample | walk-forward | retrospective
# horizon:    label the probability is scored against (months; 0 = coincident)
SIGNAL_META = {
    "composite":     {"kind": "score",       "validation": "rules",         "horizon": 12},
    "leading_index": {"kind": "score",       "validation": "rules",         "horizon": 12},
    "ml_12m":        {"kind": "probability", "validation": "in-sample",     "horizon": 12},
    "ml_6m":         {"kind": "probability", "validation": "in-sample",     "horizon": 6},
    "ml_12m_wf":     {"kind": "probability", "validation": "walk-forward",  "horizon": 12},
    "ml_6m_wf":      {"kind": "probability", "validation": "walk-forward",  "horizon": 6},
    "yield_curve":   {"kind": "probability", "validation": "walk-forward",  "horizon": 12},
    "chauvet_piger": {"kind": "probability", "validation": "retrospective", "horizon": 0},
}

CALIBRATION_BINS = 10

_MAX_LEAD_MONTHS = 24        # how far before an onset an alarm counts as a lead
_FALSE_ALARM_GRACE = 18      # alarm ≤ this many months before onset is not "false"
# Per-signal windows scale with the forecast horizon h: an alarm counts as a
# lead (and is exempt from "false") only within h + 6 months of the onset.
# A model claiming "recession within 6 months" gets no credit for an alarm
# 18 months early that had switched off long before the onset. For 12-month
# signals and the 0-100 scores this is 18 months; every lead at ship time was
# <= 11 months, so their results are unchanged.
_LEAD_SLACK, _GRACE_SLACK = 6, 6

_cache_lock = threading.Lock()
_cache: dict = {}            # {from_date_iso: (timestamp, payload)}
_CACHE_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Series assembly
# ---------------------------------------------------------------------------

def _iter_months(start: date, end: date):
    cur = start.replace(day=1)
    while cur <= end:
        yield cur
        cur = date(cur.year + (1 if cur.month == 12 else 0),
                   1 if cur.month == 12 else cur.month + 1, 1)


def _monthly_composite(from_date: date, end_date: date) -> dict:
    """Monthly first-of-month composite scores; computes+persists missing months
    (same caching contract as /api/score/history)."""
    from backend.scorer import compute_recession_score

    session = get_session()
    try:
        cached = {
            row.date: row.score
            for row in session.query(RecessionScore.date, RecessionScore.score)
            .filter(RecessionScore.date >= from_date, RecessionScore.date <= end_date)
            .all()
        }
    finally:
        session.close()

    series = {}
    for month in _iter_months(from_date, end_date):
        if month in cached:
            series[month] = cached[month]
            continue
        try:
            result = compute_recession_score(as_of_date=month)
        except Exception as exc:
            logger.warning("Backtest: could not compute score for %s: %s", month, exc)
            continue
        series[month] = result["score"]
        cat_01 = {k: v / 100.0 for k, v in result.get("category_scores", {}).items()}
        session = get_session()
        try:
            if session.query(RecessionScore).filter_by(date=month).first() is None:
                session.add(RecessionScore(
                    date=month, score=result["score"], band=result["band"],
                    computed_at=datetime.utcnow(),
                    category_breakdown=json.dumps(cat_01) if cat_01 else None,
                ))
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
    return series


def _load_nber() -> dict:
    session = get_session()
    try:
        return {
            row.date: int(row.in_recession)
            for row in session.query(NberRecession.date, NberRecession.in_recession).all()
        }
    finally:
        session.close()


def _recession_onsets(nber: dict) -> list:
    """First month of each NBER recession episode, sorted."""
    onsets = []
    for month in sorted(nber):
        prev = date(month.year + (-1 if month.month == 1 else 0),
                    12 if month.month == 1 else month.month - 1, 1)
        if nber[month] == 1 and nber.get(prev, 0) == 0:
            onsets.append(month)
    return onsets


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _lead_times(series: dict, onsets: list, threshold: float,
                max_lead: int = _MAX_LEAD_MONTHS) -> list:
    """For each onset: first alarm month within the preceding _MAX_LEAD_MONTHS.

    status: "led" (alarm fired), "missed" (signal had values but never
    alarmed), "no_data" (signal had no value at all in the lead window — e.g.
    walk-forward ML before enough labels were public).
    """
    out = []
    months = sorted(series)
    for onset in onsets:
        window = [m for m in months
                  if 0 < _months_between(m, onset) <= max_lead]
        first_alarm = next((m for m in window if series[m] >= threshold), None)
        if first_alarm:
            status = "led"
        elif not window:
            status = "no_data"
        else:
            status = "missed"
        out.append({
            "onset": onset.isoformat(),
            "first_alarm": first_alarm.isoformat() if first_alarm else None,
            "lead_months": _months_between(first_alarm, onset) if first_alarm else None,
            # The alarm was already on in the series' first month: the true
            # lead is at least this long (the data starts too late to tell).
            "lead_censored": bool(first_alarm and months and first_alarm == months[0]),
            "status": status,
        })
    return out


def _false_alarm_episodes(series: dict, nber: dict, onsets: list, threshold: float,
                          grace: int = _FALSE_ALARM_GRACE) -> int:
    """Count alarm runs that neither overlap a recession nor lead one."""
    months = sorted(series)
    episodes = 0
    in_episode = False
    episode_is_false = False
    for m in months:
        alarmed = series[m] >= threshold
        if alarmed and not in_episode:
            in_episode = True
            episode_is_false = True
        if alarmed:
            in_recession = nber.get(m, 0) == 1
            leads_onset = any(0 <= _months_between(m, o) <= grace for o in onsets)
            if in_recession or leads_onset:
                episode_is_false = False
        if not alarmed and in_episode:
            if episode_is_false:
                episodes += 1
            in_episode = False
    if in_episode and episode_is_false:
        # Open-ended trailing episode: the future is unknown, so we cannot yet
        # call it false — exclude it.
        pass
    return episodes


def _auroc(values: list, labels: list) -> Optional[float]:
    """Rank-based AUROC (Mann-Whitney U). Returns None if one class is empty."""
    v = np.asarray(values, dtype=float)
    y = np.asarray(labels, dtype=int)
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    order = v.argsort()
    ranks = np.empty(len(v), dtype=float)
    # average ranks for ties
    sorted_v = v[order]
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    rank_sum_pos = ranks[y == 1].sum()
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return round(float(u / (n_pos * n_neg)), 3)


def _brier(probs_pct: list, labels: list) -> Optional[float]:
    """Mean squared error of probabilities (0-100 %) vs 0/1 outcomes. Lower is better."""
    if not probs_pct:
        return None
    p = np.asarray(probs_pct, dtype=float) / 100.0
    y = np.asarray(labels, dtype=float)
    return round(float(np.mean((p - y) ** 2)), 4)


def _brier_skill(probs_pct: list, labels: list) -> Optional[float]:
    """1 - BS / BS_ref, where the reference always forecasts the sample base
    rate (climatology). > 0 beats the base rate, < 0 is worse than it.
    None when the sample holds only one class (no skill is measurable)."""
    if not probs_pct:
        return None
    y = np.asarray(labels, dtype=float)
    base = y.mean()
    ref = float(np.mean((base - y) ** 2))
    if ref == 0:
        return None
    bs = float(np.mean((np.asarray(probs_pct, dtype=float) / 100.0 - y) ** 2))
    return round(1.0 - bs / ref, 3)


def _calibration(probs_pct: list, labels: list, bins: int = CALIBRATION_BINS) -> list:
    """Equal-width reliability bins: mean predicted % vs observed frequency %."""
    out = []
    width = 100.0 / bins
    for i in range(bins):
        lo, hi = i * width, (i + 1) * width
        idx = [j for j, p in enumerate(probs_pct)
               if lo <= p < hi or (i == bins - 1 and p >= 100.0)]
        if not idx:
            continue
        out.append({
            "bin_low": round(lo, 1),
            "bin_high": round(hi, 1),
            "n": len(idx),
            "mean_predicted": round(float(np.mean([probs_pct[j] for j in idx])), 1),
            "observed_rate": round(100.0 * float(np.mean([labels[j] for j in idx])), 1),
        })
    return out


def _eval_labels(nber: dict, from_date: date, end_date: date, horizon: int) -> dict:
    """{month: 0/1} evaluation labels. Forward horizons exclude months already
    inside a recession so the metric measures ADVANCE warning; the coincident
    horizon (0) keeps every month."""
    from backend.ml_scorer import forward_label
    labels = {}
    for month in _iter_months(from_date, end_date):
        lbl = forward_label(nber, month, horizon)
        if lbl is None:
            continue
        if horizon > 0 and nber.get(month, 0) == 1:
            continue
        labels[month] = int(lbl)
    return labels


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_backtest(from_date: date = date(2007, 1, 1)) -> dict:
    """Assemble signal histories and evaluate them against NBER. Cached 1h."""
    key = from_date.isoformat()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]

    from backend.benchmarks import chauvet_piger_series, yield_curve_walkforward
    from backend.leading import compute_timing_history
    from backend.ml_scorer import build_feature_matrix, compute_ml_score_history, walk_forward_ml

    end_date = date.today()
    nber = _load_nber()
    onsets = _recession_onsets(nber)

    # --- assemble monthly series per signal ------------------------------
    composite = _monthly_composite(from_date, end_date)

    ml_series = {}
    for horizon in ("6m", "12m"):
        ml_series[f"ml_{horizon}"] = {
            date.fromisoformat(r["date"]): r["logit_score"]
            for r in compute_ml_score_history(from_date, end_date, horizon=horizon)
        }

    # Walk-forward ML. The feature matrix starts at the first cached month:
    # earlier months have no KPI data and would be computed only to be dropped.
    fit_stats = {}
    try:
        wf_start = min(composite) if composite else from_date
        df = build_feature_matrix(start_date=wf_start, end_date=end_date)
        for horizon in ("12m", "6m"):
            wf = walk_forward_ml(horizon, from_date, end_date, df=df)
            ml_series[f"ml_{horizon}_wf"] = wf.pop("probs")
            fit_stats[f"ml_{horizon}_wf"] = wf
    except Exception as exc:
        logger.warning("Backtest: walk-forward ML failed: %s", exc)

    yc_series = {}
    try:
        yc = yield_curve_walkforward(from_date, end_date)
        yc_series = yc.pop("probs")
        fit_stats["yield_curve"] = yc
    except Exception as exc:
        logger.warning("Backtest: yield-curve benchmark failed: %s", exc)

    cp_series = {}
    try:
        cp_series = {m: v for m, v in chauvet_piger_series().items()
                     if from_date <= m <= end_date}
    except Exception as exc:
        logger.warning("Backtest: Chauvet-Piger series unavailable: %s", exc)

    leading = {
        date.fromisoformat(r["date"]): r["leading_index"]
        for r in compute_timing_history(from_date, end_date)
        if r["leading_index"] is not None
    }

    all_series = {
        "composite": composite,
        "leading_index": leading,
        "ml_12m": ml_series.get("ml_12m", {}),
        "ml_6m": ml_series.get("ml_6m", {}),
        "ml_12m_wf": ml_series.get("ml_12m_wf", {}),
        "ml_6m_wf": ml_series.get("ml_6m_wf", {}),
        "yield_curve": yc_series,
        "chauvet_piger": cp_series,
    }

    labels_by_h = {h: _eval_labels(nber, from_date, end_date, h) for h in (0, 6, 12)}
    labels_12m = labels_by_h[12]

    onsets_in_window = [o for o in onsets if o >= from_date]

    signals = {}
    for sig_id, series in all_series.items():
        meta = SIGNAL_META[sig_id]
        base = {"name": SIGNAL_NAMES[sig_id], **meta}
        if not series:
            signals[sig_id] = {**base, "available": False}
            continue
        threshold = ALARM_THRESHOLDS[sig_id]
        max_lead = meta["horizon"] + _LEAD_SLACK
        grace = meta["horizon"] + _GRACE_SLACK
        common = [m for m in sorted(labels_12m) if m in series]
        auroc = _auroc([series[m] for m in common], [labels_12m[m] for m in common])
        sig = {
            **base,
            "available": True,
            "alarm_threshold": threshold,
            "months_evaluated": len(common),
            "first_month": min(series).isoformat(),
            "auroc_12m": auroc,
            # Lead time is meaningless for a coincident measure.
            "recessions": (
                _lead_times(series, onsets_in_window, threshold, max_lead)
                if meta["horizon"] > 0 else
                [{"onset": o.isoformat(), "first_alarm": None, "lead_months": None,
                  "status": "not_applicable"} for o in onsets_in_window]
            ),
            "lead_window_months": max_lead if meta["horizon"] > 0 else None,
            "false_alarm_episodes": _false_alarm_episodes(series, nber, onsets, threshold, grace),
            "series": [
                {"date": m.isoformat(), "value": series[m]} for m in sorted(series)
            ],
        }
        if sig_id in fit_stats:
            sig["fit_stats"] = fit_stats[sig_id]
        if meta["kind"] == "probability":
            own = labels_by_h[meta["horizon"]]
            pm = [m for m in sorted(own) if m in series]
            probs = [series[m] for m in pm]
            ys = [own[m] for m in pm]
            sig["months_scored"] = len(pm)
            sig["brier"] = _brier(probs, ys)
            sig["brier_skill"] = _brier_skill(probs, ys)
            sig["calibration"] = _calibration(probs, ys)
        signals[sig_id] = sig

    # --- common window: months where every FORECAST signal has a value ----
    # A signal whose coverage contains no pre-recession month cannot be scored
    # (AUROC undefined) and would shrink the window to a recession-free
    # stretch, so it is excluded and listed.
    forecast_ids, excluded = [], []
    for k, sg in signals.items():
        if not sg.get("available") or SIGNAL_META[k]["validation"] == "retrospective":
            continue
        if any(labels_12m[m] == 1 for m in labels_12m if m in all_series[k]):
            forecast_ids.append(k)
        else:
            excluded.append(k)
    common_months = [m for m in sorted(labels_12m)
                     if all(m in all_series[k] for k in forecast_ids)]
    common_ys = [labels_12m[m] for m in common_months]
    common_block = {
        "signals": forecast_ids,
        "excluded_no_recession_in_coverage": excluded,
        "from": common_months[0].isoformat() if common_months else None,
        "to": common_months[-1].isoformat() if common_months else None,
        "months": len(common_months),
        "positive_months": int(sum(common_ys)),
        "metrics": {},
    }
    for k in forecast_ids:
        vals = [all_series[k][m] for m in common_months]
        entry = {"auroc_12m": _auroc(vals, common_ys) if common_months else None}
        if SIGNAL_META[k]["kind"] == "probability" and SIGNAL_META[k]["horizon"] == 12:
            entry["brier"] = _brier(vals, common_ys)
        common_block["metrics"][k] = entry

    payload = {
        "from_date": from_date.isoformat(),
        "to_date": end_date.isoformat(),
        "recession_onsets": [o.isoformat() for o in onsets_in_window],
        "signals": signals,
        "common_window": common_block,
        "caveat": (
            "Backtest uses today's revised data, not real-time vintages. "
            "Lead times are therefore optimistic: in real time, data revisions "
            "and publication lags would have delayed some of these warnings."
        ),
        "walk_forward_note": (
            "Walk-forward rows refit the model every month using only NBER labels "
            "that were public at the time: a label is usable once its 6- or "
            "12-month window has passed plus a 12-month NBER dating lag. This "
            "removes model-fit leakage only. The inputs are still today's revised "
            "data, and the KPI thresholds behind the category scores were "
            "calibrated in 2026 with hindsight, so even walk-forward numbers are "
            "optimistic. The dashboard's KPI history starts in 2007, so its ML "
            "model cannot be fit out-of-sample until enough post-2008 labels are "
            "public; months before that have no prediction. Where refits do succeed on "
            "a single recession, the model can extrapolate wildly (confident 90-100% "
            "readings in calm months): that is what overfitting looks like out of "
            "sample, and why the in-sample rows should not be trusted."
        ),
        "retrospective_note": (
            "Chauvet–Piger is re-estimated over its full history with every "
            "release, so its past values use information that was not available "
            "at the time. It is shown for reference and is not ranked."
        ),
    }

    with _cache_lock:
        _cache[key] = (time.time(), payload)
    return payload
