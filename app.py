"""
US Economy KPI Dashboard — Flask entry point.

Launch with:  python app.py
"""

import io
import json
import logging
import logging.handlers
import os
import csv
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

load_dotenv()

HISTORY_YEARS = 20

# ---------------------------------------------------------------------------
# Logging setup (rotating file + console)
# ---------------------------------------------------------------------------

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_log_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"), maxBytes=5 * 1024 * 1024, backupCount=3
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[_log_handler, logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder=None)
CORS(app)

# ---------------------------------------------------------------------------
# Load KPI config helper
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "kpi_config.yaml")

def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _compute_kpi_status(kpi: dict, value) -> str:
    """Return OK / WARNING / DANGER / NO_DATA for a single KPI value.

    Single source of truth used by both /api/kpis and /api/categories so their
    per-indicator statuses and category-card counts are always in sync.
    """
    if value is None:
        return "NO_DATA"
    warn = kpi.get("warning_threshold")
    danger_t = kpi.get("danger_threshold")
    invert = kpi.get("invert", False)
    if warn is None or danger_t is None:
        return "OK"
    if invert:
        return "DANGER" if value <= danger_t else ("WARNING" if value <= warn else "OK")
    else:
        return "DANGER" if value >= danger_t else ("WARNING" if value >= warn else "OK")


def _utc_iso(dt) -> Optional[str]:
    """ISO string with an explicit +00:00 for a naive-UTC datetime (all DB
    timestamps are datetime.utcnow()). Without the offset, browsers parse the
    string as LOCAL time and shift it by the viewer's UTC offset."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _parse_as_of() -> Optional[date]:
    """Parse optional ?as_of=YYYY-MM-DD query param. Returns None if absent or invalid."""
    raw = request.args.get("as_of")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# API: Recession score
# ---------------------------------------------------------------------------

@app.route("/api/score")
def api_score():
    from backend.models import RecessionScore, get_session
    from backend.ml_scorer import compute_ml_scores_all
    from backend.scorer import get_risk_band
    as_of = _parse_as_of()

    if as_of is not None:
        from backend.scorer import compute_recession_score
        result = compute_recession_score(as_of_date=as_of)
        probs = compute_ml_scores_all(result["category_scores_raw"])
        ml = probs.get("now")
        return jsonify({
            "score": result["score"],
            "band": result["band"],
            "date": as_of.isoformat(),
            "last_refresh": None,
            "stale": False,
            "simulated": True,
            "ml_score": round(ml, 1) if ml is not None else None,
            "ml_band": get_risk_band(ml) if ml is not None else None,
            "ml_model_available": ml is not None,
            "ml_prob_6m": probs.get("6m"),
            "ml_prob_12m": probs.get("12m"),
        })

    session = get_session()
    try:
        # Defensive filter: ignore any rows dated in the future (should never
        # exist after the AR5-001 fix, but guards against legacy pollution).
        row = (
            session.query(RecessionScore)
            .filter(RecessionScore.date <= date.today())
            .order_by(RecessionScore.date.desc())
            .first()
        )
        if row is None:
            return jsonify({"score": None, "band": None, "date": None,
                            "last_refresh": None, "simulated": False,
                            "ml_score": None, "ml_band": None, "ml_model_available": False,
                            "ml_prob_6m": None, "ml_prob_12m": None})
        import json as _json
        cat_scores = _json.loads(row.category_breakdown) if row.category_breakdown else {}
        # category_breakdown is stored at 0–1 scale; convert to 0–100 for compute_ml_scores_all
        cat_scores_100 = {k: v * 100.0 for k, v in cat_scores.items()}
        probs = compute_ml_scores_all(cat_scores_100) if cat_scores_100 else {}
        ml = probs.get("now")
        return jsonify({
            "score": row.score,
            "band": row.band,
            "date": row.date.isoformat(),
            "last_refresh": _utc_iso(row.computed_at),
            "stale": (datetime.utcnow() - row.computed_at) > timedelta(hours=26),
            "simulated": False,
            "ml_score": round(ml, 1) if ml is not None else None,
            "ml_band": get_risk_band(ml) if ml is not None else None,
            "ml_model_available": ml is not None,
            "ml_prob_6m": probs.get("6m"),
            "ml_prob_12m": probs.get("12m"),
        })
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Recession score history (monthly, 2007–present)
# ---------------------------------------------------------------------------

@app.route("/api/score/history")
def api_score_history():
    import json as _json
    from backend.models import RecessionScore, MLScore, get_session
    from backend.scorer import compute_recession_score

    raw_from = request.args.get("from_date", "2007-01-01")
    as_of = _parse_as_of()
    include_ml = request.args.get("include_ml", "false").lower() == "true"
    resolution = request.args.get("resolution")
    try:
        from_date = date.fromisoformat(raw_from)
    except (ValueError, TypeError):
        from_date = date(2007, 1, 1)

    # Cap end_date at today; future as_of must not generate or persist
    # synthetic future-dated rows (which would corrupt /api/score's
    # MAX(date) lookup — see BUGS.md AR5-001).
    end_date = min(as_of, date.today()) if as_of is not None else date.today()

    # Zoomed views (5y weekly / 2y every other business day / 1y every
    # business day): computed in memory, never cached in RecessionScore (which
    # also holds the live daily rows). from_date is implied by the zoom level.
    if resolution and resolution != "monthly":
        from backend.score_history import RESOLUTIONS, compute_zoomed_history
        if resolution not in RESOLUTIONS:
            return jsonify({"error": f"unknown resolution '{resolution}'",
                            "allowed": ["monthly", *RESOLUTIONS]}), 400
        return jsonify(compute_zoomed_history(resolution, end_date, include_ml=include_ml))

    # Build list of first-of-month dates
    months = []
    d = from_date.replace(day=1)
    while d <= end_date:
        months.append(d)
        m = d.month + 1
        y = d.year + (1 if m > 12 else 0)
        m = m if m <= 12 else 1
        d = date(y, m, 1)

    session = get_session()
    try:
        # Load already-cached scores in one query
        cached = {
            row.date: row
            for row in session.query(RecessionScore)
            .filter(RecessionScore.date >= from_date, RecessionScore.date <= end_date)
            .all()
        }
        # Load ML scores if requested
        ml_cached = {}
        if include_ml:
            ml_cached = {
                row.date: row.logit_score
                for row in session.query(MLScore.date, MLScore.logit_score)
                .filter(MLScore.date >= from_date, MLScore.date <= end_date)
                .all()
            }
    finally:
        session.close()

    results = []
    ml_inputs = []   # per result row: 0–100 category scores for the 6m/12m models
    for month_date in months:
        if month_date in cached:
            row = cached[month_date]
            item = {"date": row.date.isoformat(), "score": row.score, "band": row.band}
            if include_ml:
                ml_val = ml_cached.get(month_date)
                if ml_val is None and row.category_breakdown:
                    # Compute on-demand from cached breakdown
                    from backend.ml_scorer import compute_ml_score, _save_ml_score
                    cat_scores = _json.loads(row.category_breakdown)
                    cat_scores_100 = {k: v * 100.0 for k, v in cat_scores.items()}
                    ml_val = compute_ml_score(cat_scores_100)
                    if ml_val is not None:
                        _save_ml_score(month_date, ml_val)
                item["ml_score"] = ml_val
                # Forward horizons are filled in one batch after the loop.
                ml_inputs.append(
                    {k: v * 100.0 for k, v in _json.loads(row.category_breakdown).items()}
                    if row.category_breakdown else None
                )
            results.append(item)
        else:
            # Compute on demand and cache to DB for future calls
            try:
                result = compute_recession_score(as_of_date=month_date)
                score = result["score"]
                band = result["band"]
                cat_scores = result.get("category_scores", {})  # 0–100 scale
                cat_scores_01 = {k: v / 100.0 for k, v in cat_scores.items()}
                breakdown_json = _json.dumps(cat_scores_01) if cat_scores_01 else None
                # Save to DB so subsequent calls are instant
                session = get_session()
                try:
                    existing = session.query(RecessionScore).filter_by(date=month_date).first()
                    if existing is None:
                        session.add(RecessionScore(
                            date=month_date, score=score, band=band,
                            computed_at=datetime.utcnow(),
                            category_breakdown=breakdown_json,
                        ))
                        session.commit()
                except Exception:
                    session.rollback()
                finally:
                    session.close()
                item = {"date": month_date.isoformat(), "score": score, "band": band}
                if include_ml:
                    from backend.ml_scorer import compute_ml_score, _save_ml_score
                    ml_val = compute_ml_score(cat_scores)
                    if ml_val is not None:
                        _save_ml_score(month_date, ml_val)
                    item["ml_score"] = ml_val
                    ml_inputs.append(cat_scores)
                results.append(item)
            except Exception as exc:
                logger.warning("Could not compute score for %s: %s", month_date, exc)

    if include_ml:
        # Forward horizons — the Recession Probability card's headline is 12m.
        # Not cached: one batched predict() per horizon.
        from backend.ml_scorer import compute_ml_scores_batch
        for key, horizon in (("ml_6m", "6m"), ("ml_12m", "12m")):
            for item, p in zip(results, compute_ml_scores_batch(ml_inputs, horizon)):
                item[key] = p

    return jsonify(results)


@app.route("/api/score/drivers")
def api_score_drivers():
    """Which KPIs moved the Recession Risk Score between the two latest days.

    Live: diff of the two newest per-KPI snapshots written by live refreshes
    (basis "snapshot"), or category-level only from the live score rows until
    two snapshots exist (basis "category_only"). Time Machine (?as_of=):
    reconstruction at as_of vs the previous business day ("reconstructed").
    See backend/score_history.py for why live mode must not reconstruct.
    """
    from backend.score_history import DRIVER_MIN_IMPACT, compute_drivers
    as_of = _parse_as_of()
    if as_of is not None and as_of >= date.today():
        as_of = None   # "today" in the Time Machine is live; reconstruction would give the wrong answer
    result = compute_drivers(as_of)

    kpi_meta = {k["id"]: k for k in _load_config()["kpis"]}
    for k in result["kpis"]:
        meta = kpi_meta.get(k["kpi_id"], {})
        k["status_from"] = _compute_kpi_status(meta, k["value_from"])
        k["status_to"] = _compute_kpi_status(meta, k["value_to"])
        k["impact"] = round(k["impact"], 3)
    for c in result["categories"]:
        c["label"] = _CATEGORY_INFO.get(c["id"], {}).get("label", c["id"])
        c["impact"] = round(c["impact"], 3)
    result["min_impact"] = DRIVER_MIN_IMPACT
    return jsonify(result)


# ---------------------------------------------------------------------------
# API: ML model endpoints
# ---------------------------------------------------------------------------

@app.route("/api/ml/train", methods=["POST"])
def api_ml_train():
    """Trigger ML model training in a background thread. Returns 202 Accepted."""
    import threading
    from backend.ml_scorer import get_or_train_model
    threading.Thread(
        target=get_or_train_model, kwargs={"force_retrain": True}, daemon=True
    ).start()
    return jsonify({"status": "started"}), 202


@app.route("/api/ml/status")
def api_ml_status():
    """Return per-horizon ML model metadata: training stats, coefficients."""
    from backend.ml_scorer import get_ml_metadata
    meta = get_ml_metadata()
    if meta is None:
        return jsonify({"available": False})
    return jsonify({"available": True, "horizons": meta})


@app.route("/api/ml/score/history")
def api_ml_score_history():
    """Return monthly ML Logit scores from from_date to as_of (or today).

    Optional ?horizon=now|6m|12m (default now).
    """
    from backend.ml_scorer import HORIZONS, compute_ml_score_history
    raw_from = request.args.get("from_date", "2007-01-01")
    horizon = request.args.get("horizon", "now")
    if horizon not in HORIZONS:
        return jsonify({"error": f"Unknown horizon '{horizon}'. Valid: {list(HORIZONS)}"}), 400
    as_of = _parse_as_of()
    try:
        from_date = date.fromisoformat(raw_from)
    except (ValueError, TypeError):
        from_date = date(2007, 1, 1)
    # Cap end_date at today; future as_of must not generate or persist
    # synthetic future-dated rows (which would corrupt /api/score's
    # MAX(date) lookup — see BUGS.md AR5-001).
    end_date = min(as_of, date.today()) if as_of is not None else date.today()
    results = compute_ml_score_history(from_date=from_date, end_date=end_date, horizon=horizon)
    return jsonify(results)


# ---------------------------------------------------------------------------
# API: Leading-indicator index + diffusion breadth
# ---------------------------------------------------------------------------

@app.route("/api/leading")
def api_leading():
    """Current leading/coincident indices + diffusion breadth snapshot."""
    from backend.leading import compute_timing_snapshot
    as_of = _parse_as_of()
    snapshot = compute_timing_snapshot(as_of=min(as_of, date.today()) if as_of else None)
    return jsonify(snapshot)


@app.route("/api/leading/history")
def api_leading_history():
    """Monthly leading/coincident/diffusion index history."""
    from backend.leading import compute_timing_history
    raw_from = request.args.get("from_date", "2007-01-01")
    as_of = _parse_as_of()
    try:
        from_date = date.fromisoformat(raw_from)
    except (ValueError, TypeError):
        from_date = date(2007, 1, 1)
    end_date = min(as_of, date.today()) if as_of is not None else date.today()
    return jsonify(compute_timing_history(from_date, end_date))


# ---------------------------------------------------------------------------
# API: Depression severity
# ---------------------------------------------------------------------------

@app.route("/api/severity")
def api_severity():
    """Depression Severity score: debt-deflation dynamics + persistence."""
    from backend.severity import compute_severity
    as_of = _parse_as_of()
    return jsonify(compute_severity(as_of=min(as_of, date.today()) if as_of else None))


@app.route("/api/benchmarks")
def api_benchmarks():
    """Independent benchmark probabilities: yield-curve probit (NY Fed method)
    and the retrospective Chauvet-Piger smoothed probability. In Time Machine
    mode both use only data/labels that were public at as_of."""
    from backend.benchmarks import current_benchmarks
    as_of = _parse_as_of()
    if as_of is not None and as_of >= date.today():
        as_of = None        # today or a future date is simply live mode
    return jsonify(current_benchmarks(as_of=as_of))


# ---------------------------------------------------------------------------
# API: Backtest / model performance
# ---------------------------------------------------------------------------

@app.route("/api/backtest")
def api_backtest():
    """Lead times, false alarms and AUROC for every signal vs NBER history."""
    from backend.backtester import run_backtest
    raw_from = request.args.get("from_date", "2007-01-01")
    try:
        from_date = date.fromisoformat(raw_from)
    except (ValueError, TypeError):
        from_date = date(2007, 1, 1)
    return jsonify(run_backtest(from_date=from_date))


# ---------------------------------------------------------------------------
# API: Admin — clear cached score history (forces full recompute on next call)
# ---------------------------------------------------------------------------

@app.route("/api/admin/reset-score-history", methods=["DELETE"])
def admin_reset_score_history():
    from backend.models import RecessionScore, get_session
    session = get_session()
    try:
        deleted = session.query(RecessionScore).delete()
        session.commit()
        logger.info("Admin: cleared %d cached recession scores", deleted)
        return jsonify({"deleted": deleted,
                        "message": "Score history cleared. Call GET /api/score/history to recompute."})
    except Exception as exc:
        session.rollback()
        logger.error("Failed to clear score history: %s", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: 3-month forecast score
# ---------------------------------------------------------------------------

@app.route("/api/score/forecast")
def api_score_forecast():
    """
    Compute a forecasted Recession Risk Score 3 months into the future.

    Uses linear regression on recent KPI history to project each indicator
    forward, then feeds those projected values through the standard scoring
    pipeline.

    In Time Machine mode (?as_of=YYYY-MM-DD) the forecast is computed from
    data available as of that date.  The response also includes the *actual*
    score that materialised 3 months later (if the data exists in the DB),
    enabling validation.
    """
    from backend.models import get_session
    from backend.scorer import compute_recession_score, get_risk_band
    from backend.forecaster import forecast_all_kpis
    from dateutil.relativedelta import relativedelta

    as_of = _parse_as_of()
    effective_date = as_of if as_of is not None else date.today()
    forecast_target = effective_date + relativedelta(months=3)

    config = _load_config()
    session = get_session()
    try:
        # Step 1: forecast each KPI
        forecasts = forecast_all_kpis(config["kpis"], effective_date, session)

        # Step 2: build overrides dict (skip KPIs with no forecast)
        overrides = {
            kpi_id: fc["forecast_value"]
            for kpi_id, fc in forecasts.items()
            if fc.get("forecast_value") is not None
        }
        logger.info("Forecast overrides: %d KPIs covered out of %d total",
                    len(overrides), len(config["kpis"]))

        # Step 3: compute forecast score using projected values.
        # Pass as_of_date so non-override KPIs use the correct historical baseline
        # in Time Machine mode (as_of=None in normal mode → no change in behavior).
        forecast_result = compute_recession_score(kpi_value_overrides=overrides, as_of_date=as_of)

        # Step 4: In Time Machine mode, compute the actual score at forecast_target
        actual_score = None
        actual_band = None
        if as_of is not None and forecast_target <= date.today():
            try:
                actual_result = compute_recession_score(as_of_date=forecast_target)
                actual_score = actual_result["score"]
                actual_band = actual_result["band"]
            except Exception as exc:
                logger.warning("Could not compute actual score at %s: %s", forecast_target, exc)

        return jsonify({
            "forecast_score": forecast_result["score"],
            "forecast_band": forecast_result["band"],
            "forecast_date": forecast_target.isoformat(),
            "as_of_date": effective_date.isoformat(),
            "actual_score": actual_score,
            "actual_band": actual_band,
            "forecast_category_scores": forecast_result["category_scores"],
            "overrides_count": len(overrides),
        })
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: All KPIs (latest values + status)
# ---------------------------------------------------------------------------

def _latest_rows_per_kpi(session, KpiData, max_date=None, per_kpi=2):
    """Return {kpi_id: [rows newest-first]} with the newest `per_kpi` rows per KPI.

    Single window-function query instead of one query per KPI (SQLite >= 3.25).
    """
    from sqlalchemy import func

    rn = (
        func.row_number()
        .over(partition_by=KpiData.kpi_id, order_by=KpiData.date.desc())
        .label("rn")
    )
    inner = session.query(
        KpiData.kpi_id, KpiData.date, KpiData.value, KpiData.fetched_at, rn
    )
    if max_date is not None:
        inner = inner.filter(KpiData.date <= max_date)
    sub = inner.subquery()
    rows = session.query(sub).filter(sub.c.rn <= per_kpi).all()

    out = {}
    for row in rows:
        out.setdefault(row.kpi_id, []).append(row)
    for kpi_rows in out.values():
        kpi_rows.sort(key=lambda r: r.date, reverse=True)
    return out


@app.route("/api/kpis")
def api_kpis():
    from backend.models import KpiData, get_session
    from backend.scorer import normalize_kpi, get_risk_band
    from backend.forecaster import forecast_all_kpis, compute_forecast_status
    from dateutil.relativedelta import relativedelta
    as_of = _parse_as_of()

    config = _load_config()
    kpi_map = {k["id"]: k for k in config["kpis"]}
    session = get_session()
    try:
        effective_date = as_of if as_of is not None else date.today()
        forecast_target = effective_date + relativedelta(months=3)

        # Compute all KPI forecasts in one pass (gracefully degrade if forecasting fails)
        try:
            forecasts = forecast_all_kpis(config["kpis"], effective_date, session)
            logger.debug("Forecast computed for %d KPIs", len(forecasts))
        except Exception as exc:
            logger.warning("Forecast computation failed; returning KPIs without forecast fields: %s", exc)
            forecasts = {}

        # ---------------------------------------------------------------------------
        # Forecast accuracy — cached daily in AppConfig (key: fc_accuracy:{kpi_id})
        # ---------------------------------------------------------------------------
        from backend.models import AppConfig
        from backend.forecaster import compute_forecast_accuracy
        today_str = str(date.today())
        acc_cache = {}
        # Load any already-cached results from today
        for row in session.query(AppConfig).filter(AppConfig.key.like("fc_accuracy:%")).all():
            kid = row.key[len("fc_accuracy:"):]
            try:
                data = json.loads(row.value)
                if data.get("date") == today_str:
                    acc_cache[kid] = data
            except Exception:
                pass

        # Compute accuracy for KPIs not yet cached today (only in live mode)
        if as_of is None:
            for kpi in config["kpis"]:
                kid = kpi["id"]
                if kid in acc_cache:
                    continue
                try:
                    result = compute_forecast_accuracy(kid, kpi, effective_date, session)
                except Exception as exc:
                    logger.warning("Accuracy computation failed for %s: %s", kid, exc)
                    result = {"accuracy": None, "samples": 0}
                payload = json.dumps({"accuracy": result["accuracy"],
                                      "samples": result["samples"],
                                      "date": today_str})
                existing = session.query(AppConfig).filter_by(key=f"fc_accuracy:{kid}").first()
                if existing:
                    existing.value = payload
                else:
                    session.add(AppConfig(key=f"fc_accuracy:{kid}", value=payload))
                acc_cache[kid] = {"accuracy": result["accuracy"], "samples": result["samples"]}
            try:
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.warning("Failed to cache forecast accuracy: %s", exc)

        # Fetch latest + prior value for ALL KPIs in one window-function query
        # (was one query per KPI — ~156 queries per request in Time Machine mode).
        latest_map = _latest_rows_per_kpi(session, KpiData, max_date=as_of, per_kpi=2)

        # Time Machine: batch the "actual value at forecast target" lookups too —
        # only when the target is on or before today, otherwise the query would
        # return today's value masquerading as a future actual (BUGS.md AR2-003).
        actual_fc_map = {}
        if as_of is not None and forecast_target <= date.today():
            actual_fc_map = {
                kid: rows[0].value
                for kid, rows in _latest_rows_per_kpi(
                    session, KpiData, max_date=forecast_target, per_kpi=1
                ).items()
            }

        from backend.fetcher import _STALENESS_WINDOW_DAYS

        results = []
        for kpi in config["kpis"]:
            kpi_id = kpi["id"]
            rows = latest_map.get(kpi_id, [])
            latest_val = rows[0].value if rows else None
            prior_val = rows[1].value if len(rows) > 1 else None
            latest_date = rows[0].date.isoformat() if rows else None
            data_retrieved = _utc_iso(rows[0].fetched_at) if rows and rows[0].fetched_at else None

            # Per-KPI staleness flag (BUGS.md AR1-002) — live mode only; in Time
            # Machine mode all data is historical so the flag is meaningless.
            stale = False
            if as_of is None and rows and kpi.get("source") != "manual_csv":
                window = kpi.get("staleness_window_days") or _STALENESS_WINDOW_DAYS.get(
                    kpi.get("frequency", "monthly"), 50
                )
                stale = (date.today() - rows[0].date).days > window

            sub_score = normalize_kpi(kpi, latest_val) if latest_val is not None else None

            status = _compute_kpi_status(kpi, latest_val)

            change_abs = None
            change_pct = None
            if latest_val is not None and prior_val is not None and prior_val != 0:
                change_abs = round(latest_val - prior_val, 4)
                change_pct = round((latest_val - prior_val) / abs(prior_val) * 100, 2)

            # Forecast fields
            fc = forecasts.get(kpi_id, {})
            fc_val = fc.get("forecast_value")
            fc_status = compute_forecast_status(kpi, fc_val)

            actual_at_fc = actual_fc_map.get(kpi_id)

            results.append({
                "id": kpi_id,
                "name": kpi["name"],
                "category": kpi["category"],
                "source": kpi.get("source"),
                "unit": kpi.get("unit"),
                "frequency": kpi.get("frequency"),
                "description": kpi.get("description", "").strip(),
                "series_id": kpi.get("series_id"),
                "warning_threshold": kpi.get("warning_threshold"),
                "danger_threshold": kpi.get("danger_threshold"),
                "latest_value": latest_val,
                "prior_value": prior_val,
                "latest_date": latest_date,
                "data_retrieved": data_retrieved,
                "change_abs": change_abs,
                "change_pct": change_pct,
                "sub_score": round(sub_score, 3) if sub_score is not None else None,
                "status": status,
                "stale": stale,
                "chart_y_min": kpi.get("chart_y_min"),
                "chart_y_max": kpi.get("chart_y_max"),
                # 3-month forecast fields
                "forecast_value": round(fc_val, 4) if fc_val is not None else None,
                "forecast_date": fc.get("forecast_date"),
                "forecast_status": fc_status,
                "forecast_trend": fc.get("trend_direction"),
                "forecast_r2": fc.get("r2"),
                "actual_value_at_forecast_date": round(actual_at_fc, 4) if actual_at_fc is not None else None,
                # Forecast accuracy (backtest over past 3 months)
                "forecast_accuracy": acc_cache.get(kpi_id, {}).get("accuracy"),
                "forecast_accuracy_samples": acc_cache.get(kpi_id, {}).get("samples"),
            })
        return jsonify(results)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: KPI history (5-year time series)
# ---------------------------------------------------------------------------

@app.route("/api/kpis/<kpi_id>/history")
def api_kpi_history(kpi_id):
    from backend.models import KpiData, get_session
    as_of = _parse_as_of()

    # Reject unknown KPI ids with 404 instead of returning 200 [] (AR4-004),
    # which prevented the frontend from distinguishing "valid KPI, no data"
    # from "garbage id".
    config = _load_config()
    if not any(k["id"] == kpi_id for k in config["kpis"]):
        return jsonify({"error": f"Unknown KPI: {kpi_id}"}), 404

    session = get_session()
    try:
        reference_date = as_of if as_of is not None else date.today()
        cutoff = reference_date - timedelta(days=365 * 20)
        q = session.query(KpiData).filter(
            KpiData.kpi_id == kpi_id, KpiData.date >= cutoff
        )
        if as_of is not None:
            q = q.filter(KpiData.date <= as_of)
        rows = q.order_by(KpiData.date.asc()).all()
        data = [{"date": r.date.isoformat(), "value": r.value} for r in rows]
        return jsonify(data)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: NBER recession shading
# ---------------------------------------------------------------------------

@app.route("/api/nber-shading")
def api_nber_shading():
    from backend.models import NberRecession, get_session

    session = get_session()
    try:
        rows = (
            session.query(NberRecession)
            .order_by(NberRecession.date.asc())
            .all()
        )
        # Convert to list of {start, end} date ranges for ReferenceArea
        periods = []
        in_rec = False
        start = None
        for row in rows:
            if row.in_recession and not in_rec:
                in_rec = True
                start = row.date.isoformat()
            elif not row.in_recession and in_rec:
                in_rec = False
                periods.append({"start": start, "end": row.date.isoformat()})
        if in_rec and start:
            periods.append({"start": start, "end": date.today().isoformat()})
        return jsonify(periods)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Category summary cards
# ---------------------------------------------------------------------------

_CATEGORY_INFO = {
    "yield_curve":       {"label": "Yield Curve & Rates",    "icon": "📈"},
    "labor_market":      {"label": "Labor Market",            "icon": "👷"},
    "consumer_health":   {"label": "Consumer Health",         "icon": "🛒"},
    "housing":           {"label": "Housing Market",          "icon": "🏠"},
    "financial_stress":  {"label": "Financial Stress",        "icon": "💹"},
    "business_activity": {"label": "Business Activity",       "icon": "🏭"},
    "energy":            {"label": "Energy Market",           "icon": "⛽"},
    "automotive":        {"label": "Automotive Market",       "icon": "🚗"},
}


@app.route("/api/categories")
def api_categories():
    from backend.models import KpiData, get_session
    as_of = _parse_as_of()

    config = _load_config()
    kpi_map = {k["id"]: k for k in config["kpis"]}
    category_info = _CATEGORY_INFO

    session = get_session()
    try:
        categories = []
        for cat_id, cat_meta in category_info.items():
            cat_kpis = [k for k in config["kpis"] if k["category"] == cat_id]
            warning_count = 0
            danger_count = 0
            # Representative KPI for sparkline = whichever FRED/yfinance KPI has the most recent data
            rep_kpi = None
            rep_latest_date = None
            for k in cat_kpis:
                if k.get("source") not in ("fred", "yfinance"):
                    continue
                q = session.query(KpiData.date).filter_by(kpi_id=k["id"])
                if as_of is not None:
                    q = q.filter(KpiData.date <= as_of)
                row = q.order_by(KpiData.date.desc()).first()
                if row and (rep_latest_date is None or row[0] > rep_latest_date):
                    rep_latest_date = row[0]
                    rep_kpi = k

            sparkline = []
            if rep_kpi:
                reference_date = as_of if as_of is not None else date.today()
                cutoff = reference_date - timedelta(days=1825)  # 5-year sparkline window
                q = session.query(KpiData).filter(
                    KpiData.kpi_id == rep_kpi["id"], KpiData.date >= cutoff
                )
                if as_of is not None:
                    q = q.filter(KpiData.date <= as_of)
                rows = q.order_by(KpiData.date.asc()).all()
                sparkline = [{"date": r.date.isoformat(), "value": r.value} for r in rows]

            for kpi in cat_kpis:
                q = session.query(KpiData.value).filter_by(kpi_id=kpi["id"])
                if as_of is not None:
                    q = q.filter(KpiData.date <= as_of)
                latest = q.order_by(KpiData.date.desc()).first()
                if latest and latest[0] is not None:
                    s = _compute_kpi_status(kpi, latest[0])
                    if s == "DANGER":
                        danger_count += 1
                    elif s == "WARNING":
                        warning_count += 1

            categories.append({
                "id": cat_id,
                "label": cat_meta["label"],
                "icon": cat_meta["icon"],
                "kpi_count": len(cat_kpis),
                "warning_count": warning_count,
                "danger_count": danger_count,
                "representative_kpi": rep_kpi["id"] if rep_kpi else None,
                "sparkline": sparkline,
            })
        return jsonify(categories)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: Manual refresh
# ---------------------------------------------------------------------------

import threading

_refresh_lock = threading.Lock()

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    # Non-blocking acquire makes the check-and-start atomic; released by the worker.
    if not _refresh_lock.acquire(blocking=False):
        return jsonify({"status": "already_running"}), 409

    def _run():
        try:
            from backend.fetcher import fetch_all_kpis
            from backend.scorer import compute_recession_score
            from backend.alerter import check_and_send_alerts
            from backend.ml_scorer import compute_ml_score, _save_ml_score
            fetch_all_kpis(incremental=True)
            result = compute_recession_score()
            check_and_send_alerts(
                result["score"], result["band"],
                result.get("kpi_contributions", [])
            )
            # Update today's ML score
            ml = compute_ml_score(result.get("category_scores", {}))
            if ml is not None:
                _save_ml_score(date.today(), ml)
            _invalidate_live_commentary()
        finally:
            _refresh_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


def _invalidate_live_commentary():
    """Drop commentary cached for today so it regenerates against refreshed data.

    Historical (Time-Machine) entries are keyed to past as_of dates whose
    underlying data is immutable, so only today's rows are cleared.
    """
    from backend.models import AiCommentary, get_session
    session = get_session()
    try:
        deleted = (
            session.query(AiCommentary)
            .filter(AiCommentary.as_of_date == date.today())
            .delete()
        )
        session.commit()
        if deleted:
            logger.info("Invalidated %d live commentary cache entries after refresh", deleted)
    except Exception:
        logger.exception("Failed to invalidate live commentary cache")
        session.rollback()
    finally:
        session.close()


@app.route("/api/refresh/status")
def api_refresh_status():
    return jsonify({"running": _refresh_lock.locked()})


# ---------------------------------------------------------------------------
# API: Settings (read / write)
# ---------------------------------------------------------------------------

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    from backend.models import AppConfig, get_session
    from backend.alerter import get_warning_threshold, get_critical_threshold, alerts_enabled

    session = get_session()
    try:
        if request.method == "GET":
            return jsonify({
                "warning_threshold": get_warning_threshold(),
                "critical_threshold": get_critical_threshold(),
                "alerts_enabled": alerts_enabled(),
                "alert_email_to": os.getenv("ALERT_EMAIL_TO", ""),
            })

        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Body must be a JSON object"}), 400
        # Type-coerce known keys before persisting so a bad value can't poison
        # subsequent GETs (which call float() on the stored string).
        coercers = {
            "warning_threshold": float,
            "critical_threshold": float,
            "alerts_enabled": lambda v: bool(v) if isinstance(v, bool)
                else str(v).strip().lower() in ("1", "true", "yes", "on"),
            "refresh_schedule": str,
        }
        for key, val in data.items():
            if key not in coercers:
                continue
            try:
                coerced = coercers[key](val)
            except (TypeError, ValueError):
                return jsonify({"error": f"Invalid value for {key}: {val!r}"}), 400
            row = session.get(AppConfig, key)
            if row:
                row.value = str(coerced)
            else:
                session.add(AppConfig(key=key, value=str(coerced)))
        session.commit()
        return jsonify({"status": "saved"})
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API: CSV upload for manual KPIs
# ---------------------------------------------------------------------------

@app.route("/api/upload-csv/<kpi_id>", methods=["POST"])
def api_upload_csv(kpi_id):
    from backend.models import KpiData, get_session
    from backend.fetcher import _save_series
    import pandas as pd

    config = _load_config()
    kpi = next((k for k in config["kpis"] if k["id"] == kpi_id), None)
    if kpi is None:
        return jsonify({"error": f"Unknown KPI: {kpi_id}"}), 404
    if kpi.get("source") != "manual_csv":
        return jsonify({"error": "KPI is not a manual_csv type"}), 400

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        content = file.read().decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"error": "File is not valid UTF-8 text"}), 400

    try:
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or "date" not in reader.fieldnames or "value" not in reader.fieldnames:
            return jsonify({
                "error": "CSV must have columns 'date' and 'value'",
                "got_columns": reader.fieldnames or [],
            }), 400
        today = date.today()
        records = {}
        for row in reader:
            try:
                d = pd.to_datetime(row.get("date", "")).date()
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid date: {row.get('date')!r}"}), 400
            if d > today:
                return jsonify({"error": f"Future-dated rows are not allowed: {d.isoformat()}"}), 400
            if d < date(1950, 1, 1):
                return jsonify({"error": f"Date too old (likely typo): {d.isoformat()}"}), 400
            try:
                v = float(row.get("value", "nan"))
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid value: {row.get('value')!r}"}), 400
            records[d] = v
        if not records:
            return jsonify({"error": "CSV had no usable rows"}), 400
        series = pd.Series(records).sort_index()
        saved = _save_series(kpi_id, series)
        return jsonify({"status": "ok", "rows_saved": saved})
    except Exception as exc:
        logger.exception("CSV upload failed for %s", kpi_id)
        return jsonify({"error": "Upload failed; see server log"}), 400


# ---------------------------------------------------------------------------
# API: AI Commentary (per-category + global)
# ---------------------------------------------------------------------------

def _get_commentary_cache(session, category_id: str, as_of: date):
    from backend.models import AiCommentary
    row = (
        session.query(AiCommentary)
        .filter_by(category_id=category_id, as_of_date=as_of)
        .first()
    )
    if row:
        return {
            "commentary": row.commentary,
            "generated_at": _utc_iso(row.generated_at),
            "model": row.model,
            "cached": True,
        }
    return None


def _save_commentary(session, category_id: str, as_of: date, commentary: str, model: str):
    from backend.models import AiCommentary
    existing = (
        session.query(AiCommentary)
        .filter_by(category_id=category_id, as_of_date=as_of)
        .first()
    )
    if existing:
        existing.commentary = commentary
        existing.generated_at = datetime.utcnow()
        existing.model = model
    else:
        session.add(AiCommentary(
            category_id=category_id,
            as_of_date=as_of,
            commentary=commentary,
            model=model,
            generated_at=datetime.utcnow(),
        ))
    session.commit()


@app.route("/api/commentary/category/<category_id>", methods=["GET"])
def get_category_commentary(category_id: str):
    from backend.models import get_session
    from backend import commentator
    if category_id not in _CATEGORY_INFO:
        return jsonify({"error": f"Unknown category: {category_id}"}), 404
    as_of = _parse_as_of() or date.today()
    session = get_session()
    try:
        cached = _get_commentary_cache(session, category_id, as_of)
        if cached:
            return jsonify(cached)
        return jsonify({"commentary": None, "generated_at": None, "model": None, "cached": False})
    finally:
        session.close()


@app.route("/api/commentary/category/<category_id>", methods=["POST"])
def generate_category_commentary(category_id: str):
    from backend.models import get_session
    from backend import commentator
    from backend.scorer import compute_recession_score

    if category_id not in _CATEGORY_INFO:
        return jsonify({"error": f"Unknown category: {category_id}"}), 404

    if not commentator.is_available():
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured."}), 503

    as_of = _parse_as_of() or date.today()
    force = request.args.get("force", "false").lower() == "true"

    session = get_session()
    try:
        if not force:
            cached = _get_commentary_cache(session, category_id, as_of)
            if cached:
                return jsonify(cached)

        # Fetch all KPI data and scores
        score_result = compute_recession_score(as_of_date=as_of if as_of != date.today() else None)
        all_kpis = _build_kpi_list(as_of)
        category_scores = {
            cat: round(s, 1)
            for cat, s in score_result.get("category_scores", {}).items()
        }
        cat_score = category_scores.get(category_id, 0.0)

        prompt = commentator.build_category_prompt(
            category_id=category_id,
            kpis=all_kpis,
            category_score=cat_score,
            all_category_scores=category_scores,
            as_of_date=as_of,
        )
        text = commentator.call_claude(prompt)
        model = commentator._get_model()

        _save_commentary(session, category_id, as_of, text, model)

        return jsonify({
            "commentary": text,
            "generated_at": _utc_iso(datetime.utcnow()),
            "model": model,
            "cached": False,
        })
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.exception("Failed to generate category commentary for %s", category_id)
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


@app.route("/api/commentary/global", methods=["GET"])
def get_global_commentary():
    from backend.models import get_session
    as_of = _parse_as_of() or date.today()
    session = get_session()
    try:
        cached = _get_commentary_cache(session, "global", as_of)
        if cached:
            return jsonify(cached)
        return jsonify({"commentary": None, "generated_at": None, "model": None, "cached": False})
    finally:
        session.close()


@app.route("/api/commentary/global", methods=["POST"])
def generate_global_commentary():
    from backend.models import get_session
    from backend import commentator
    from backend.scorer import compute_recession_score, get_risk_band

    if not commentator.is_available():
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured."}), 503

    as_of = _parse_as_of() or date.today()
    force = request.args.get("force", "false").lower() == "true"

    session = get_session()
    try:
        if not force:
            cached = _get_commentary_cache(session, "global", as_of)
            if cached:
                return jsonify(cached)

        score_result = compute_recession_score(as_of_date=as_of if as_of != date.today() else None)
        overall_score = round(score_result.get("score", 0), 1)
        band = get_risk_band(overall_score)
        category_scores = {
            cat: round(s, 1)
            for cat, s in score_result.get("category_scores", {}).items()
        }
        all_kpis = _build_kpi_list(as_of)

        prompt = commentator.build_global_prompt(
            all_kpis=all_kpis,
            category_scores=category_scores,
            overall_score=overall_score,
            band=band,
            as_of_date=as_of,
        )
        text = commentator.call_claude(prompt)
        model = commentator._get_model()

        _save_commentary(session, "global", as_of, text, model)

        return jsonify({
            "commentary": text,
            "generated_at": datetime.utcnow().isoformat(),
            "model": model,
            "cached": False,
        })
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.exception("Failed to generate global commentary")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()


def _build_kpi_list(as_of: date) -> list:
    """Build a lightweight KPI list with value/status/sub_score for commentary prompts."""
    from backend.models import KpiData, get_session
    from backend.scorer import normalize_kpi
    config = _load_config()
    session = get_session()
    try:
        results = []
        for kpi in config["kpis"]:
            kpi_id = kpi["id"]
            q = session.query(KpiData).filter_by(kpi_id=kpi_id)
            if as_of != date.today():
                q = q.filter(KpiData.date <= as_of)
            rows = q.order_by(KpiData.date.desc()).limit(2).all()
            latest_val = rows[0].value if rows else None
            prior_val = rows[1].value if len(rows) > 1 else None
            sub_score = normalize_kpi(kpi, latest_val) if latest_val is not None else None
            status = _compute_kpi_status(kpi, latest_val)
            change_abs = None
            change_pct = None
            if latest_val is not None and prior_val is not None and prior_val != 0:
                change_abs = round(latest_val - prior_val, 4)
                change_pct = round((latest_val - prior_val) / abs(prior_val) * 100, 2)
            results.append({
                "id": kpi_id,
                "name": kpi["name"],
                "category": kpi["category"],
                "unit": kpi.get("unit", ""),
                "latest_value": latest_val,
                "status": status,
                "sub_score": sub_score,
                "change_abs": change_abs,
                "change_pct": change_pct,
                "forecast_status": None,
            })
        return results
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Serve React SPA
# ---------------------------------------------------------------------------

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path):
    dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    # Serve a real file from frontend/dist if it exists; otherwise fall back to
    # index.html so React Router can resolve client-side routes (e.g.
    # /category/yield_curve, /kpi/t10y2y). Without this fallback, deep links
    # 404 because Flask's default static handler refuses unknown paths.
    if path and os.path.isfile(os.path.join(dist, path)):
        return send_from_directory(dist, path)
    return send_from_directory(dist, "index.html")


# ---------------------------------------------------------------------------
# Startup checklist & main
# ---------------------------------------------------------------------------

def print_startup_checklist(next_run: str):
    from backend.models import DB_PATH
    db_status = "found" if os.path.exists(DB_PATH) else "created"
    keys = {
        "FRED": os.getenv("FRED_API_KEY", ""),
        "BLS": os.getenv("BLS_API_KEY", ""),
        "EIA": os.getenv("EIA_API_KEY", ""),
        "CENSUS": os.getenv("CENSUS_API_KEY", ""),
        "BEA": os.getenv("BEA_API_KEY", ""),
    }
    key_summary = ", ".join(
        f"{k} {'OK' if v else '--'}" for k, v in keys.items()
    )
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    ai_status = "OK -- AI commentary enabled" if anthropic_key else "-- AI commentary disabled (set ANTHROPIC_API_KEY)"
    print("\n" + "=" * 60)
    print("  US Economy KPI Dashboard -- Recession Risk Monitor")
    print("=" * 60)
    print(f"  [OK] Database : data/recession_kpi.db ({db_status})")
    print(f"  [{'OK' if keys['FRED'] else '--'}] API Keys  : {key_summary}")
    print(f"  [{'OK' if anthropic_key else '--'}] Claude AI : {ai_status}")
    print(f"  [OK] Scheduler: daily refresh at {next_run}")
    print(f"  [OK] Server   : http://localhost:5000")
    print("=" * 60 + "\n")


def _set_appconfig(key: str, value: str) -> None:
    """Upsert a single AppConfig key-value pair."""
    from backend.models import AppConfig, get_session
    session = get_session()
    try:
        row = session.get(AppConfig, key)
        if row:
            row.value = value
        else:
            session.add(AppConfig(key=key, value=value))
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    from backend.models import init_db, DB_PATH
    from backend.scheduler import start_scheduler, next_run_time
    from backend.fetcher import bootstrap_history

    # Init DB
    init_db()

    # Bootstrap if DB is empty, or extend history if HISTORY_YEARS increased
    from backend.models import KpiData, AppConfig, get_session
    from backend.fetcher import clear_and_refetch_changed_series
    session = get_session()
    count = session.query(KpiData).count()
    stored_years_row = session.get(AppConfig, "history_years")
    stored_years = int(stored_years_row.value) if stored_years_row else 0
    session.close()

    if count == 0:
        bootstrap_history()
        _set_appconfig("history_years", str(HISTORY_YEARS))
    elif stored_years < HISTORY_YEARS:
        logger.info(
            "Extending history from %d to %d years — re-bootstrapping (this may take 20–40 min)…",
            stored_years, HISTORY_YEARS,
        )
        bootstrap_history()   # _save_series is idempotent; won't duplicate existing data
        _set_appconfig("history_years", str(HISTORY_YEARS))
    else:
        # Clear and re-fetch any KPIs whose series_id changed since last run
        clear_and_refetch_changed_series()

    # Benchmark inputs (yield-curve probit, Chauvet-Piger) live in their own
    # table; fetch them once on first launch after the upgrade.
    from backend.fetcher import fetch_reference_series, reference_series_empty
    if reference_series_empty():
        fetch_reference_series()

    # Start scheduler
    config = _load_config()
    refresh_time = config.get("refresh_schedule", "07:00")
    sched = start_scheduler(refresh_time)

    print_startup_checklist(next_run_time())

    # Background ML model training (if not already trained)
    import threading as _threading
    from backend.ml_scorer import load_model as _load_ml_model, get_or_train_model as _train_ml
    _ml_result, _ = _load_ml_model()
    if _ml_result is None:
        logger.info("ML model not found — training will start in 10 seconds in background")
        _threading.Timer(10.0, _train_ml).start()
    else:
        logger.info("ML model already trained — skipping background training")

    app.run(host="0.0.0.0", port=5000, debug=False)
