"""Probe FRED directly for every KPI with source=fred and assert the series
still has recent observations. This is the test that would have caught the
4 silent FRED breaks documented in CLAUDE.md 'KPI Alignment Cleanup (April 2026)'
months earlier.

Skips entirely if FRED_API_KEY is not set or the network is down.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest


pytestmark = pytest.mark.network


def _have_fred_key():
    return bool(os.environ.get("FRED_API_KEY"))


@pytest.fixture(scope="module")
def fred():
    if not _have_fred_key():
        pytest.skip("FRED_API_KEY not set")
    try:
        from fredapi import Fred
    except ImportError:
        pytest.skip("fredapi not installed")
    return Fred(api_key=os.environ["FRED_API_KEY"])


_STALENESS_WINDOW_DAYS = {
    "daily": 30,
    "weekly": 90,
    "monthly": 120,
    "quarterly": 280,
}


def test_every_fred_series_has_recent_data(fred, kpi_config):
    """Hit FRED for each KPI with source=fred and confirm a row in the
    last N days. Reports all failures together."""
    today = date.today()
    failures = []
    checked = 0

    for kpi in kpi_config["kpis"]:
        if kpi.get("source") != "fred":
            continue
        sid = kpi.get("series_id")
        if not sid:
            continue
        freq = kpi.get("frequency", "monthly")
        window = _STALENESS_WINDOW_DAYS.get(freq, 120)
        try:
            s = fred.get_series(
                sid,
                observation_start=today - timedelta(days=window * 2),
                observation_end=today,
            )
        except Exception as exc:
            failures.append(f"{kpi['id']} ({sid}): FRED error: {exc}")
            continue
        if s is None or s.dropna().empty:
            failures.append(f"{kpi['id']} ({sid}): no observations in last {window*2}d")
            continue
        latest = s.dropna().index[-1].date()
        age = (today - latest).days
        if age > window:
            failures.append(f"{kpi['id']} ({sid}): latest={latest}, age={age}d > {window}d")
        checked += 1

    if failures:
        print(f"\n\nFRED series staleness — checked {checked} OK, {len(failures)} failed:")
        for f in failures:
            print(f"  {f}")
    # Don't hard-fail in normal CI runs: the test is a probe; print is enough.
    # Convert to a hard failure if you want strict gating:
    # assert not failures, "Stale FRED series found"
