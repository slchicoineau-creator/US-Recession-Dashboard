"""
Statsmodels Logistic Regression overlay for the Recession Risk Score.

Trains THREE Logit models on the 8 category sub-scores from
compute_recession_score() (features), one per prediction horizon:

  "now"  - target: NBER in_recession this month (coincident nowcast)
  "6m"   - target: any NBER recession month within the NEXT 6 months
  "12m"  - target: any NBER recession month within the NEXT 12 months

The forward-horizon models are what make the dashboard predictive: they answer
"P(recession within N months)" rather than "are we in one right now".
Months whose forward window extends beyond NBER coverage are censored
(excluded from training) rather than assumed to be expansion.

Architecture:
  - Features: 8 category sub-scores (0-1 scale), one per month
  - Training window: 1990-01-01 to present (in practice limited by DB history)
  - Class imbalance handled via frequency weights
  - All three models persisted together in data/ml_model.pkl with version guard

Known limitation (documented on the Model Performance page): features are
computed from today's REVISED data, not the vintages available in real time,
so in-sample lead times are somewhat optimistic.
"""

import functools
import json
import logging
import os
import pickle
import threading
from datetime import date, datetime
from typing import Optional

import pandas as pd
import statsmodels.api as sm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRAIN_START = date(1990, 1, 1)
MIN_CATEGORIES = 5        # min number of categories with data to include a month
FFILL_LIMIT = 3           # max months to forward-fill (handles quarterly KPIs)
ML_MODEL_VERSION = 2      # v2: multi-horizon models (now / 6m / 12m)

DEFAULT_NBER_LABEL_LAG = 12  # fallback when kpi_config.yaml has no usrecm_long entry

# Walk-forward (out-of-sample) evaluation: a refit needs at least this many
# usable rows and this many months of EACH class. With 8 features and a single
# recession episode, fewer positives/negatives reliably produce perfect
# separation (infinite coefficients), so those months get no prediction.
WF_MIN_ROWS = 36
WF_MIN_PER_CLASS = 6
WF_MAX_ABS_COEF = 50.0       # |coef| beyond this = quasi-separation, reject fit

HORIZON_MONTHS = {"now": 0, "6m": 6, "12m": 12}
HORIZONS = tuple(HORIZON_MONTHS)          # ("now", "6m", "12m")
_LABEL_COLS = {"now": "in_recession", "6m": "recession_within_6m", "12m": "recession_within_12m"}

CATEGORIES = [
    "yield_curve", "labor_market", "consumer_health", "housing",
    "financial_stress", "business_activity", "energy", "automotive",
]

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ML_MODEL_PATH = os.path.join(_DATA_DIR, "ml_model.pkl")

_train_lock = threading.Lock()
_model_cache: Optional[dict] = None       # {horizon: LogitResults}
_model_meta_cache: Optional[dict] = None  # {horizon: metadata dict}


# ---------------------------------------------------------------------------
# Feature matrix builder
# ---------------------------------------------------------------------------

def _iter_months(start: date, end: date):
    """Yield first-of-month dates from start to end (inclusive)."""
    cur = start.replace(day=1)
    while cur <= end:
        yield cur
        # advance one month
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)


def _add_months(d: date, n: int) -> date:
    """First-of-month date n months after d."""
    total = d.year * 12 + (d.month - 1) + n
    return date(total // 12, total % 12 + 1, 1)


def forward_label(nber: dict, month: date, horizon_months: int) -> Optional[int]:
    """1 if any NBER recession month falls within (month, month + horizon].

    Returns None (censored) when any month in the window is missing from
    NBER coverage — the future is unknown there, not expansion.
    """
    if horizon_months == 0:
        return nber.get(month)
    flags = []
    for i in range(1, horizon_months + 1):
        flag = nber.get(_add_months(month, i))
        if flag is None:
            return None
        flags.append(flag)
    return int(any(flags))


@functools.lru_cache(maxsize=1)
def _nber_label_lag_months() -> int:
    """NBER dating lag from kpi_config.yaml (reference_series usrecm_long)."""
    try:
        import yaml
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "kpi_config.yaml")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        for ref in cfg.get("reference_series", []) or []:
            if ref.get("key") == "usrecm_long":
                return int(ref.get("publication_lag_months", DEFAULT_NBER_LABEL_LAG))
    except Exception as exc:
        logger.warning("Could not read NBER label lag from config: %s", exc)
    return DEFAULT_NBER_LABEL_LAG


def label_known(month: date, horizon_months: int, at: date,
                lag_months: Optional[int] = None) -> bool:
    """Whether the training label for `month` at `horizon_months` was public at `at`.

    THE single leakage rule for every walk-forward / Time-Machine fit (ML
    walk-forward, yield-curve benchmark, /api/benchmarks). A label covering
    (month, month + horizon] is only settled once that whole window has passed
    AND NBER has had `lag_months` to date the turning points (it dated the
    Dec-2007 peak in Dec-2008). Month granularity: `at` is floored to its month.
    """
    lag = _nber_label_lag_months() if lag_months is None else lag_months
    return _add_months(month.replace(day=1), horizon_months + lag) <= at.replace(day=1)


def build_feature_matrix(
    start_date: date = TRAIN_START,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """
    Build monthly feature matrix for Logit training/evaluation.

    Returns a DataFrame with columns
    [*CATEGORIES, 'in_recession', 'recession_within_6m', 'recession_within_12m'],
    indexed by first-of-month dates. The forward-label columns contain NaN for
    censored months (forward window beyond NBER coverage).

    Fast path: reads cached category_breakdown JSON from RecessionScore table.
    Slow path: calls compute_recession_score(as_of_date=month) for missing months.
    """
    from backend.models import RecessionScore, NberRecession, get_session
    from backend.scorer import compute_recession_score

    if end_date is None:
        end_date = date.today()

    session = get_session()
    try:
        # Load all cached RecessionScore rows with category_breakdown
        cached_rows = (
            session.query(RecessionScore.date, RecessionScore.category_breakdown)
            .filter(
                RecessionScore.date >= start_date,
                RecessionScore.date <= end_date,
                RecessionScore.category_breakdown.isnot(None),
            )
            .all()
        )
        cached = {row.date: json.loads(row.category_breakdown) for row in cached_rows}

        # Load NBER recession flags
        nber_rows = session.query(NberRecession.date, NberRecession.in_recession).all()
        nber = {row.date: int(row.in_recession) for row in nber_rows}
    finally:
        session.close()

    records = []
    months = list(_iter_months(start_date, end_date))
    logger.info("Building ML feature matrix for %d months (%s to %s)",
                len(months), start_date, end_date)

    for i, month in enumerate(months):
        if month in cached:
            cat_scores = cached[month]  # already 0–1 scale
        else:
            # Compute on-demand — division by 100 because compute_recession_score
            # returns category_scores scaled to 0–100
            try:
                result = compute_recession_score(as_of_date=month)
                cat_scores = {k: v / 100.0 for k, v in result["category_scores"].items()}
            except Exception as exc:
                logger.warning("Could not compute score for %s: %s", month, exc)
                cat_scores = {}

        row = {"date": month}
        for cat in CATEGORIES:
            row[cat] = cat_scores.get(cat, None)

        # Labels per horizon — NBER flags match first-of-month (USRECM is monthly)
        for horizon, col in _LABEL_COLS.items():
            row[col] = forward_label(nber, month, HORIZON_MONTHS[horizon])
        records.append(row)

        if (i + 1) % 50 == 0:
            logger.info("  processed %d / %d months", i + 1, len(months))

    df = pd.DataFrame(records).set_index("date")

    # Forward-fill up to FFILL_LIMIT months to handle quarterly KPIs
    df[CATEGORIES] = df[CATEGORIES].ffill(limit=FFILL_LIMIT)

    # Drop months where NBER flag is missing (data predates USRECM coverage)
    df = df.dropna(subset=["in_recession"])

    # Drop months with too few categories
    cat_count = df[CATEGORIES].notna().sum(axis=1)
    dropped = (cat_count < MIN_CATEGORIES).sum()
    if dropped:
        logger.warning("Dropping %d months with fewer than %d categories", dropped, MIN_CATEGORIES)
    df = df[cat_count >= MIN_CATEGORIES]

    # Impute remaining NaN category values as 0.0 (no signal)
    nan_cells = df[CATEGORIES].isna().sum().sum()
    if nan_cells:
        logger.warning("Imputing %d missing category-month cells as 0.0", nan_cells)
    df[CATEGORIES] = df[CATEGORIES].fillna(0.0)

    logger.info(
        "Feature matrix: %d rows | positives now=%d, 6m=%d, 12m=%d",
        len(df),
        int(df["in_recession"].sum()),
        int(df["recession_within_6m"].sum(skipna=True)),
        int(df["recession_within_12m"].sum(skipna=True)),
    )
    return df


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

def train_logit_model(df: pd.DataFrame, label_col: str = "in_recession"):
    """
    Train a statsmodels Logit model on the feature matrix for one label column.

    Rows with NaN in label_col (censored forward windows) are excluded.

    Trains unweighted maximum-likelihood Logit. (v1 passed freq_weights to
    sm.Logit, which silently ignores them — Logit has no such kwarg. Unweighted
    MLE is the deliberate choice now: it keeps predicted probabilities
    calibrated to the true base rate of recession months, which is what an
    early-warning probability should report.)

    Returns a fitted LogitResults object.
    """
    train_df = df.dropna(subset=[label_col])
    X = sm.add_constant(train_df[CATEGORIES], has_constant="add")
    y = train_df[label_col].astype(int)

    n_pos = int((y == 1).sum())
    if n_pos == 0:
        raise ValueError(f"No positive months for label {label_col} — cannot train.")

    logger.info("Training Logit[%s]: %d obs, %d positive months",
                label_col, len(y), n_pos)

    model = sm.Logit(y, X)
    result = model.fit(method="bfgs", maxiter=200, disp=False)
    return result


def safe_fit(model_cls, y, X):
    """Fit a statsmodels binary model; return None on separation/non-convergence.

    Used by walk-forward refits, where small early training sets routinely
    separate. The live models keep using train_logit_model unchanged.
    """
    import warnings
    from statsmodels.tools import sm_exceptions as sme

    sep_warning = getattr(sme, "PerfectSeparationWarning", None)
    import numpy as np

    try:
        # Newton converges in a handful of iterations on these small problems;
        # on separated data it diverges/singular-matrix errors, which is the
        # "no usable fit" signal we want. Overflow in exp() is part of that.
        with warnings.catch_warnings(), np.errstate(over="ignore", divide="ignore"):
            warnings.simplefilter("error", sme.ConvergenceWarning)
            warnings.simplefilter("ignore", RuntimeWarning)
            if sep_warning is not None:
                warnings.simplefilter("error", sep_warning)
            result = model_cls(y, X).fit(method="newton", maxiter=100, disp=False)
    except Exception:
        return None
    if not result.mle_retvals.get("converged", False):
        return None
    if float(result.params.abs().max()) > WF_MAX_ABS_COEF:
        return None
    return result


def walk_forward_ml(horizon: str, from_date: date, end_date: date,
                    df: Optional[pd.DataFrame] = None) -> dict:
    """Out-of-sample Logit probabilities, one expanding-window refit per month.

    For each evaluation month t, the model is fit ONLY on rows whose label was
    public at t (label_known), then predicts t from t's own features. This
    removes the model-fit leakage of the in-sample backtest. It does NOT remove
    two other sources of optimism: features are computed from today's revised
    data, and KPI thresholds were calibrated in 2026 with hindsight.

    Returns {"probs": {month: pct}, "fits": int, "failed_fits": int,
             "skipped_months": int, "first_prediction": iso|None}.
    """
    label_col = _LABEL_COLS[horizon]
    h = HORIZON_MONTHS[horizon]
    if df is None:
        df = build_feature_matrix(start_date=TRAIN_START, end_date=end_date)

    probs: dict = {}
    fits = failed = skipped = 0
    last_n, last_result = None, None
    labelled = df.dropna(subset=[label_col])

    for t in _iter_months(from_date.replace(day=1), end_date):
        if t not in df.index:
            continue
        train = labelled[[label_known(m, h, t) for m in labelled.index]]
        n_pos = int(train[label_col].sum()) if len(train) else 0
        n_neg = len(train) - n_pos
        if len(train) < WF_MIN_ROWS or n_pos < WF_MIN_PER_CLASS or n_neg < WF_MIN_PER_CLASS:
            skipped += 1
            continue
        if len(train) != last_n:            # training set grew -> refit
            last_n = len(train)
            fits += 1
            X = sm.add_constant(train[CATEGORIES], has_constant="add")
            last_result = safe_fit(sm.Logit, train[label_col].astype(int), X)
            if last_result is None:
                failed += 1
        if last_result is None:
            skipped += 1
            continue
        x_t = sm.add_constant(df.loc[[t], CATEGORIES], has_constant="add")
        probs[t] = round(float(last_result.predict(x_t).iloc[0]) * 100.0, 1)

    return {
        "probs": probs,
        "fits": fits,
        "failed_fits": failed,
        "skipped_months": skipped,
        "first_prediction": min(probs).isoformat() if probs else None,
    }


# ---------------------------------------------------------------------------
# Model persistence
# ---------------------------------------------------------------------------

def save_model(models: dict, metadata: dict) -> None:
    """Pickle the fitted per-horizon LogitResults and metadata with a version guard."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    payload = {
        "version": ML_MODEL_VERSION,
        "models": models,        # {horizon: LogitResults}
        "metadata": metadata,    # {horizon: dict}
    }
    with open(ML_MODEL_PATH, "wb") as f:
        pickle.dump(payload, f)
    logger.info("ML models saved to %s (horizons: %s)", ML_MODEL_PATH, list(models))


def load_model():
    """
    Load pickled per-horizon models. Returns (models_dict, metadata_dict) or
    (None, None) if file missing or version mismatch (e.g. v1 single-model pickle).
    """
    if not os.path.exists(ML_MODEL_PATH):
        return None, None
    try:
        with open(ML_MODEL_PATH, "rb") as f:
            payload = pickle.load(f)
        if payload.get("version") != ML_MODEL_VERSION:
            logger.warning("ML model version mismatch — will retrain")
            return None, None
        return payload["models"], payload["metadata"]
    except Exception as exc:
        logger.warning("Failed to load ML model: %s", exc)
        return None, None


def _build_metadata(result, df: pd.DataFrame, label_col: str) -> dict:
    train_df = df.dropna(subset=[label_col])
    coef_names = list(result.params.index)
    return {
        "trained_at": datetime.utcnow().isoformat(),
        "label": label_col,
        "n_observations": int(len(train_df)),
        "n_positive_months": int(train_df[label_col].sum()),
        "train_start": str(train_df.index.min()),
        "train_end": str(train_df.index.max()),
        "pseudo_r2": round(float(result.prsquared), 4),
        "coefficients": {k: round(float(v), 4) for k, v in result.params.items()},
        "p_values": {k: round(float(v), 4) for k, v in result.pvalues.items()},
        "coef_names": coef_names,
    }


# ---------------------------------------------------------------------------
# Thread-safe train-or-load
# ---------------------------------------------------------------------------

def get_or_train_model(force_retrain: bool = False):
    """
    Load the cached models or train all horizons from scratch. Thread-safe.
    Returns {horizon: LogitResults} or None on failure.
    Updates module-level _model_cache and _model_meta_cache.
    """
    global _model_cache, _model_meta_cache

    with _train_lock:
        if not force_retrain:
            models, meta = load_model()
            if models is not None:
                _model_cache = models
                _model_meta_cache = meta
                logger.info("ML models loaded from disk (horizons: %s)", list(models))
                return models

        logger.info("Training ML Logit models (force_retrain=%s)...", force_retrain)
        try:
            df = build_feature_matrix(start_date=TRAIN_START)
            if len(df) < 50:
                logger.warning("Insufficient training data (%d rows) — ML scoring unavailable", len(df))
                return None
            models, meta = {}, {}
            for horizon in HORIZONS:
                label_col = _LABEL_COLS[horizon]
                result = train_logit_model(df, label_col)
                models[horizon] = result
                meta[horizon] = _build_metadata(result, df, label_col)
                logger.info("ML model[%s] trained: n=%d, pseudo_R2=%.3f",
                            horizon, meta[horizon]["n_observations"], meta[horizon]["pseudo_r2"])
            save_model(models, meta)
            _model_cache = models
            _model_meta_cache = meta
            return models
        except Exception as exc:
            logger.error("ML model training failed: %s", exc, exc_info=True)
            return None


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _get_models() -> Optional[dict]:
    global _model_cache, _model_meta_cache
    if _model_cache is None:
        models, meta = load_model()
        if models is None:
            return None
        _model_cache = models
        _model_meta_cache = meta
    return _model_cache


def compute_ml_score(category_scores_dict: dict, horizon: str = "now") -> Optional[float]:
    """
    Compute ML recession probability for the given category scores and horizon.

    category_scores_dict: values in 0–100 scale (from compute_recession_score output).
    Returns P(recession) × 100 as a float, or None if model unavailable.
    """
    models = _get_models()
    if models is None or horizon not in models:
        return None

    try:
        # Convert 0–100 → 0–1 scale
        feature_row = {cat: category_scores_dict.get(cat, 0.0) / 100.0 for cat in CATEGORIES}
        X = pd.DataFrame([feature_row])[CATEGORIES]
        X = sm.add_constant(X, has_constant="add")
        prob = float(models[horizon].predict(X)[0])
        return round(prob * 100.0, 1)
    except Exception as exc:
        logger.warning("ML score inference failed (%s): %s", horizon, exc)
        return None


def compute_ml_scores_batch(category_score_rows: list, horizon: str) -> list:
    """compute_ml_score for many rows in one predict() call (same rounding).

    Used by the score-history endpoints, which need a probability per chart
    point; ~250 separate predict() calls cost ~1s, one batched call ~ms.
    Rows that are None yield None.
    """
    out = [None] * len(category_score_rows)
    models = _get_models()
    if models is None or horizon not in models:
        return out
    idx = [i for i, r in enumerate(category_score_rows) if r is not None]
    if not idx:
        return out
    try:
        X = pd.DataFrame([
            {cat: category_score_rows[i].get(cat, 0.0) / 100.0 for cat in CATEGORIES}
            for i in idx
        ])[CATEGORIES]
        X = sm.add_constant(X, has_constant="add")
        probs = models[horizon].predict(X)
        for i, p in zip(idx, probs):
            out[i] = round(float(p) * 100.0, 1)
    except Exception as exc:
        logger.warning("Batched ML inference failed (%s): %s", horizon, exc)
    return out


def compute_ml_scores_all(category_scores_dict: dict) -> dict:
    """All-horizon probabilities: {"now": x, "6m": y, "12m": z} (values may be None)."""
    return {h: compute_ml_score(category_scores_dict, horizon=h) for h in HORIZONS}


def get_ml_metadata() -> Optional[dict]:
    """Return cached per-horizon model metadata, or load from disk."""
    global _model_meta_cache
    if _model_meta_cache is not None:
        return _model_meta_cache
    _, meta = load_model()
    if meta:
        _model_meta_cache = meta
    return meta


# ---------------------------------------------------------------------------
# History computation
# ---------------------------------------------------------------------------

def compute_ml_score_history(
    from_date: date,
    end_date: Optional[date] = None,
    horizon: str = "now",
) -> list:
    """
    Compute (or retrieve cached) monthly ML scores from from_date to end_date.

    Returns list of {"date": str, "logit_score": float}.
    The "now" horizon is cached in the ml_scores DB table (existing behavior);
    forward horizons are computed on the fly from cached category breakdowns —
    inference is a dot product per month, so no persistence is needed.
    """
    from backend.models import MLScore, RecessionScore, get_session

    if end_date is None:
        end_date = date.today()

    if _get_models() is None:
        logger.warning("ML model unavailable — returning empty history")
        return []

    session = get_session()
    try:
        # Load cached ML scores (nowcast horizon only)
        cached_ml = {}
        if horizon == "now":
            cached_ml = {
                row.date: row.logit_score
                for row in session.query(MLScore.date, MLScore.logit_score)
                .filter(MLScore.date >= from_date, MLScore.date <= end_date)
                .all()
            }

        # Load category_breakdown from RecessionScore for fast inference
        cached_breakdown = {
            row.date: json.loads(row.category_breakdown)
            for row in session.query(RecessionScore.date, RecessionScore.category_breakdown)
            .filter(
                RecessionScore.date >= from_date,
                RecessionScore.date <= end_date,
                RecessionScore.category_breakdown.isnot(None),
            )
            .all()
        }
    finally:
        session.close()

    results = []
    months = list(_iter_months(from_date.replace(day=1), end_date))

    for month in months:
        if month in cached_ml:
            results.append({"date": month.isoformat(), "logit_score": cached_ml[month]})
            continue

        # Need to compute — get category scores
        if month in cached_breakdown:
            # breakdown is stored at 0–1 scale; convert to 0–100 for compute_ml_score
            cat_scores_100 = {k: v * 100.0 for k, v in cached_breakdown[month].items()}
        else:
            from backend.scorer import compute_recession_score
            try:
                r = compute_recession_score(as_of_date=month)
                cat_scores_100 = r["category_scores"]  # already 0–100
            except Exception as exc:
                logger.warning("Could not compute score for %s: %s", month, exc)
                continue

        ml_score = compute_ml_score(cat_scores_100, horizon=horizon)
        if ml_score is None:
            continue

        if horizon == "now":
            _save_ml_score(month, ml_score)
        results.append({"date": month.isoformat(), "logit_score": ml_score})

    return results


def _save_ml_score(dt: date, logit_score: float) -> None:
    """Upsert a single ML score into the ml_scores table."""
    from backend.models import MLScore, get_session
    session = get_session()
    try:
        existing = session.query(MLScore).filter_by(date=dt).first()
        if existing:
            existing.logit_score = logit_score
            existing.computed_at = datetime.utcnow()
        else:
            session.add(MLScore(date=dt, logit_score=logit_score, computed_at=datetime.utcnow()))
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Failed to save ML score for %s: %s", dt, exc)
    finally:
        session.close()
