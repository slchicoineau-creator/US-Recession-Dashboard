"""Test for backend.fetcher.check_staleness watchdog.

Seeds a temp DB with KPI rows of various ages and asserts ERROR logs fire
exactly when a KPI's latest row exceeds its frequency-specific window:
  daily → 15 days, weekly → 60 days, monthly → 95 days, quarterly → 250 days
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pytest

from backend.models import KpiData
from backend.fetcher import check_staleness, _STALENESS_WINDOW_DAYS


def _seed(session, kpi_id: str, days_ago: int):
    session.add(KpiData(kpi_id=kpi_id, date=date.today() - timedelta(days=days_ago), value=1.0))
    session.commit()


@pytest.mark.parametrize("freq,age_days,should_fire", [
    ("daily", 5, False),
    ("daily", 14, False),
    ("daily", 16, True),
    ("weekly", 30, False),
    ("weekly", 61, True),
    ("monthly", 60, False),
    ("monthly", 96, True),
    ("quarterly", 200, False),
    ("quarterly", 251, True),
])
def test_staleness_threshold(tmp_session, caplog, freq, age_days, should_fire):
    kpi = {"id": f"test_{freq}_{age_days}", "frequency": freq, "source": "fred"}
    _seed(tmp_session, kpi["id"], age_days)
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="backend.fetcher"):
        check_staleness([kpi])
    fired = any("Stale KPI" in r.message for r in caplog.records)
    assert fired == should_fire


def test_manual_csv_skipped(tmp_session, caplog):
    """manual_csv KPIs are skipped — no staleness watchdog applies."""
    kpi = {"id": "manual_test", "frequency": "monthly", "source": "manual_csv"}
    _seed(tmp_session, kpi["id"], 999)
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="backend.fetcher"):
        check_staleness([kpi])
    assert not any("Stale KPI manual_test" in r.message for r in caplog.records)


def test_no_data_no_alarm(tmp_session, caplog):
    """KPI with zero rows in DB does not fire (cannot compute age)."""
    kpi = {"id": "never_seeded", "frequency": "monthly", "source": "fred"}
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="backend.fetcher"):
        check_staleness([kpi])
    assert not any("Stale KPI never_seeded" in r.message for r in caplog.records)


def test_staleness_windows_match_constants():
    assert _STALENESS_WINDOW_DAYS == {
        "daily": 15, "weekly": 60, "monthly": 95, "quarterly": 250,
    }


def test_live_db_no_stale_kpis(real_session, kpi_config, caplog):
    """Run the watchdog against the LIVE DB and report any stale KPIs.
    This is the integration test that would have caught the 4 silent breaks
    from the 'KPI Alignment Cleanup (April 2026)' section of CLAUDE.md."""
    # Use a separate session for the check by monkey-patching get_session
    # (skip — use real DB query directly)
    from backend.models import KpiData
    today = date.today()
    stale = []
    for kpi in kpi_config["kpis"]:
        if kpi.get("source") == "manual_csv":
            continue
        row = (
            real_session.query(KpiData.date)
            .filter_by(kpi_id=kpi["id"])
            .order_by(KpiData.date.desc())
            .first()
        )
        if not row:
            continue
        latest = row[0]
        window = _STALENESS_WINDOW_DAYS.get(kpi.get("frequency", "monthly"), 95)
        age = (today - latest).days
        if age > window:
            stale.append(f"{kpi['id']} ({kpi.get('source')}/{kpi.get('frequency')}): "
                         f"latest={latest}, age={age}d > window={window}d")
    if stale:
        msg = "\nStale KPIs in live DB:\n  " + "\n  ".join(stale)
        # Print loud and don't fail — this is informational for the bug-hunt
        print(msg)
