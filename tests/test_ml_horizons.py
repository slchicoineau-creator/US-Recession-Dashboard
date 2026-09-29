"""Unit tests for the multi-horizon ML scorer (forward labels + training)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.ml_scorer import (
    CATEGORIES,
    HORIZON_MONTHS,
    HORIZONS,
    _LABEL_COLS,
    _add_months,
    forward_label,
    train_logit_model,
)


# ---------------------------------------------------------------------------
# forward_label
# ---------------------------------------------------------------------------

def _nber(start: date, months: int, recession_months: set) -> dict:
    """Build an NBER dict of `months` consecutive months from start."""
    out = {}
    cur = start
    for _ in range(months):
        out[cur] = 1 if cur in recession_months else 0
        cur = _add_months(cur, 1)
    return out


class TestForwardLabel:
    def test_horizon_zero_is_coincident_flag(self):
        nber = {date(2020, 3, 1): 1, date(2020, 2, 1): 0}
        assert forward_label(nber, date(2020, 3, 1), 0) == 1
        assert forward_label(nber, date(2020, 2, 1), 0) == 0

    def test_recession_inside_window_labels_positive(self):
        # Recession at 2008-01; month 2007-06 is 7 months before.
        rec = {date(2008, 1, 1)}
        nber = _nber(date(2007, 1, 1), 24, rec)
        assert forward_label(nber, date(2007, 6, 1), 12) == 1   # within 12
        assert forward_label(nber, date(2007, 6, 1), 6) == 0    # not within 6
        assert forward_label(nber, date(2007, 7, 1), 6) == 1    # exactly 6 ahead

    def test_recession_this_month_does_not_label_forward(self):
        # forward window is (t, t+h] — exclusive of t itself.
        rec = {date(2008, 1, 1)}
        nber = _nber(date(2007, 1, 1), 24, rec)
        assert forward_label(nber, date(2008, 1, 1), 6) == 0

    def test_censoring_beyond_nber_coverage(self):
        # Coverage ends 2026-06; a 12m window from 2025-08 needs 2026-08 → None.
        nber = _nber(date(2024, 1, 1), 30, set())  # through 2026-06
        assert forward_label(nber, date(2025, 8, 1), 12) is None
        assert forward_label(nber, date(2025, 6, 1), 12) == 0   # fits exactly

    def test_horizon_constants_consistent(self):
        assert set(HORIZONS) == set(HORIZON_MONTHS) == set(_LABEL_COLS)
        assert HORIZON_MONTHS["now"] == 0
        assert HORIZON_MONTHS["6m"] == 6
        assert HORIZON_MONTHS["12m"] == 12


# ---------------------------------------------------------------------------
# train_logit_model with forward labels
# ---------------------------------------------------------------------------

def _synthetic_matrix(n: int = 200, seed: int = 7) -> pd.DataFrame:
    """Feature matrix where financial_stress cleanly drives the label."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {cat: rng.uniform(0, 1, n) for cat in CATEGORIES},
        index=pd.date_range("2000-01-01", periods=n, freq="MS").date,
    )
    df["in_recession"] = (df["financial_stress"] > 0.7).astype(int)
    # Forward label with trailing censored months
    df["recession_within_12m"] = df["in_recession"]
    df.iloc[-12:, df.columns.get_loc("recession_within_12m")] = np.nan
    return df


class TestTrainLogit:
    def test_trains_and_predicts_in_range(self):
        df = _synthetic_matrix()
        result = train_logit_model(df, "in_recession")
        preds = result.predict()
        assert ((preds >= 0) & (preds <= 1)).all()
        # The driving feature must get a positive coefficient
        assert result.params["financial_stress"] > 0

    def test_censored_rows_excluded(self):
        df = _synthetic_matrix()
        result = train_logit_model(df, "recession_within_12m")
        assert result.nobs == len(df) - 12

    def test_no_positives_raises(self):
        df = _synthetic_matrix()
        df["in_recession"] = 0
        with pytest.raises(ValueError):
            train_logit_model(df, "in_recession")
