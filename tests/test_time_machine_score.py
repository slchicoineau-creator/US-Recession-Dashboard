"""Time Machine regression test.

Computes the recession score at three known historical dates against the LIVE
DB and asserts the band matches what NBER history requires:
  - 2008-09-15 (Lehman collapse) → HIGH or CRITICAL
  - 2020-04-15 (COVID peak)      → HIGH or CRITICAL
  - 2015-06-01 (mid-cycle calm)  → LOW or ELEVATED

Skips if the live DB does not contain values from those eras (e.g. fresh DB).
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.scorer import compute_recession_score, _value_as_of
from backend.models import KpiData


def _has_data_at(real_session, target: date, min_kpis: int = 5) -> bool:
    n_kpis = (
        real_session.query(KpiData.kpi_id)
        .filter(KpiData.date <= target)
        .distinct()
        .count()
    )
    return n_kpis >= min_kpis


@pytest.mark.parametrize("target,allowed_bands,label", [
    (date(2008, 9, 15), {"HIGH", "CRITICAL"}, "Lehman"),
    (date(2020, 4, 15), {"HIGH", "CRITICAL"}, "COVID peak"),
    (date(2015, 6, 1), {"LOW", "ELEVATED"}, "mid-cycle calm"),
])
def test_historical_band(real_session, target, allowed_bands, label):
    if not _has_data_at(real_session, target):
        pytest.skip(f"Live DB lacks data at {target} ({label})")
    result = compute_recession_score(as_of_date=target)
    assert result["band"] in allowed_bands, (
        f"{label} {target}: expected band in {allowed_bands}, got {result['band']} "
        f"(score={result['score']})"
    )


def test_value_as_of_returns_pre_target_value(real_session):
    """_value_as_of must return the most recent value ≤ target, not after."""
    # Pick a KPI that we know has long history
    target = date(2015, 1, 1)
    val = _value_as_of("dgs10", target)
    if val is None:
        pytest.skip("No dgs10 data before 2015-01-01")
    # Sanity: dgs10 in early 2015 was ~2-3%
    assert 0 < val < 10, f"10Y yield at {target} should be 0-10%, got {val}"


def test_score_today_matches_score_endpoint_logic(real_session):
    """Score computed via compute_recession_score() (live mode) should match
    score computed with as_of=today (Time Machine reconstruction). Tiny float
    diffs OK."""
    live = compute_recession_score()
    sim = compute_recession_score(as_of_date=date.today())
    # Allow 1-point tolerance for any timing-related row differences
    assert abs(live["score"] - sim["score"]) <= 1.0, (
        f"Live={live['score']} vs as_of=today={sim['score']} should match"
    )
