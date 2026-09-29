"""Zoomed score history + day-over-day score drivers (backend/score_history.py)."""

from datetime import date, datetime, timedelta
import json

import pytest

from backend.score_history import (
    _SeriesIndex, _scored_kpi_ids, attribute_change, compute_drivers,
    compute_zoomed_history, sample_dates,
)
from backend.scorer import _load_config, compute_recession_score, score_from_values


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def test_weekly_samples_anchor_at_end_and_step_seven_days():
    end = date(2026, 9, 25)
    ds = sample_dates("5y", end)
    assert ds[-1] == end
    assert ds == sorted(ds)
    assert all((b - a).days == 7 for a, b in zip(ds, ds[1:]))
    assert ds[0] >= date(2021, 9, 25)
    assert 259 <= len(ds) <= 262


def test_business_day_samples_skip_weekends_and_federal_holidays():
    end = date(2026, 9, 25)                  # a Friday
    ds = sample_dates("1y", end)
    assert ds[-1] == end
    assert all(d.weekday() < 5 for d in ds)
    assert date(2025, 12, 25) not in ds      # Christmas
    assert date(2026, 7, 3) not in ds        # Independence Day (observed)
    assert date(2026, 9, 7) not in ds        # Labor Day
    assert 245 <= len(ds) <= 255


def test_every_other_business_day_is_anchored_at_end():
    end = date(2026, 9, 25)
    every = sample_dates("1y", end)
    other = sample_dates("2y", end)
    assert other[-1] == end
    # Within the last year the 2y grid is exactly every second 1y point, counted from the end.
    last_year = [d for d in other if d >= every[0]]
    assert last_year == every[::-1][::2][::-1][-len(last_year):]


def test_weekend_end_date_is_still_the_last_point():
    sat = date(2026, 9, 26)
    for res in ("1y", "2y", "5y"):
        assert sample_dates(res, sat)[-1] == sat


# ---------------------------------------------------------------------------
# Parity: the fast path must equal compute_recession_score(as_of_date=d)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("d", [
    "2008-09-15", "2020-04-15", "2026-09-01", "2026-09-08",
    "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
])
def test_fast_history_matches_scorer_exactly(real_db_path, d):
    if not real_db_path.exists():
        pytest.skip("live DB not present")
    d = date.fromisoformat(d)
    cfg = _load_config()
    ids = _scored_kpi_ids(cfg)
    index = _SeriesIndex(ids)
    fast = score_from_values(cfg, {k: index.value_as_of(k, d) for k in ids})
    slow = compute_recession_score(as_of_date=d)
    assert fast["score"] == slow["score"]
    assert {k: round(v * 100, 1) for k, v in fast["category_scores"].items()} == slow["category_scores"]


def test_zoomed_history_last_point_is_end_date(real_db_path):
    if not real_db_path.exists():
        pytest.skip("live DB not present")
    end = date(2026, 9, 25)
    pts = compute_zoomed_history("1y", end)
    assert pts[-1]["date"] == end.isoformat()
    assert pts[-1]["score"] == compute_recession_score(as_of_date=end)["score"]


def test_unknown_resolution_rejected():
    with pytest.raises(ValueError):
        compute_zoomed_history("10y", date(2026, 1, 1))


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def _mini_config():
    return {
        "category_weights": {"a": 0.5, "b": 0.5},
        "kpis": [
            {"id": "x", "name": "X", "category": "a", "warning_threshold": 10, "danger_threshold": 20},
            {"id": "y", "name": "Y", "category": "a", "warning_threshold": 10, "danger_threshold": 20},
            {"id": "z", "name": "Z", "category": "b", "warning_threshold": 5, "danger_threshold": 1, "invert": True},
        ],
    }


def test_single_kpi_move_is_fully_attributed():
    cfg = _mini_config()
    before = {"x": 5, "y": 5, "z": 10}
    after = {"x": 15, "y": 5, "z": 10}
    r = attribute_change(cfg, before, after)
    assert [k["kpi_id"] for k in r["kpis"]] == ["x"]          # unchanged KPIs omitted
    assert r["kpis"][0]["impact"] == pytest.approx(r["delta"], abs=1e-9)
    assert r["interaction"] == pytest.approx(0, abs=1e-9)
    assert r["delta"] > 0
    cat = {c["id"]: c for c in r["categories"]}
    assert cat["a"]["impact"] == pytest.approx(r["delta"], abs=1e-9)
    assert cat["b"]["impact"] == pytest.approx(0, abs=1e-9)


def test_improving_kpi_has_negative_impact():
    cfg = _mini_config()
    r = attribute_change(cfg, {"x": 5, "z": 2}, {"x": 5, "z": 10})   # inverted KPI recovers
    assert r["kpis"][0]["kpi_id"] == "z"
    assert r["kpis"][0]["impact"] < 0


def test_kpi_appearing_is_reported():
    cfg = _mini_config()
    r = attribute_change(cfg, {"x": 5, "z": 10}, {"x": 5, "y": 20, "z": 10})
    y = next(k for k in r["kpis"] if k["kpi_id"] == "y")
    assert y["value_from"] is None and y["value_to"] == 20
    assert y["impact"] > 0


# ---------------------------------------------------------------------------
# Snapshots + drivers against a temp DB
# ---------------------------------------------------------------------------

def test_live_score_writes_kpi_snapshot(tmp_session):
    from backend.models import KpiData, KpiSnapshot
    tmp_session.add_all([
        KpiData(kpi_id="vix", date=date.today() - timedelta(days=1), value=30.0),
        KpiData(kpi_id="unrate", date=date.today() - timedelta(days=20), value=4.5),
    ])
    tmp_session.commit()
    compute_recession_score()
    compute_recession_score()          # second refresh same day replaces, not duplicates
    rows = tmp_session.query(KpiSnapshot).filter(KpiSnapshot.date == date.today()).all()
    assert sorted(r.kpi_id for r in rows) == ["unrate", "vix"]


def test_drivers_diff_two_snapshots(tmp_session):
    from backend.models import KpiSnapshot
    d0, d1 = date.today() - timedelta(days=1), date.today()
    tmp_session.add_all([
        KpiSnapshot(date=d0, kpi_id="vix", value=15.0, sub_score=0.0),
        KpiSnapshot(date=d0, kpi_id="unrate", value=4.0, sub_score=0.0),
        KpiSnapshot(date=d1, kpi_id="vix", value=45.0, sub_score=1.0),
        KpiSnapshot(date=d1, kpi_id="unrate", value=4.0, sub_score=0.0),
    ])
    tmp_session.commit()
    r = compute_drivers()
    assert r["basis"] == "snapshot"
    assert (r["from_date"], r["to_date"]) == (d0.isoformat(), d1.isoformat())
    assert [k["kpi_id"] for k in r["kpis"]] == ["vix"]
    assert r["kpis"][0]["impact"] > 0 and r["delta"] > 0


def test_drivers_fall_back_to_category_split_from_live_rows(tmp_session):
    from backend.models import RecessionScore
    d0, d1 = date.today() - timedelta(days=1), date.today()
    tmp_session.add_all([
        RecessionScore(date=d0, score=30.0, band="ELEVATED",
                       computed_at=datetime.combine(d0, datetime.min.time()) + timedelta(hours=12),
                       category_breakdown=json.dumps({"labor_market": 0.2, "energy": 0.4})),
        RecessionScore(date=d1, score=31.0, band="ELEVATED",
                       computed_at=datetime.combine(d1, datetime.min.time()) + timedelta(hours=12),
                       category_breakdown=json.dumps({"labor_market": 0.3, "energy": 0.4})),
        # A monthly history-cache row (computed weeks later) must not count as live.
        RecessionScore(date=d0 - timedelta(days=40), score=99.0, band="CRITICAL",
                       computed_at=datetime.combine(d1, datetime.min.time()),
                       category_breakdown=json.dumps({"labor_market": 1.0})),
    ])
    tmp_session.commit()
    r = compute_drivers()
    assert r["basis"] == "category_only"
    assert (r["score_from"], r["score_to"]) == (30.0, 31.0)
    top = r["categories"][0]
    assert top["id"] == "labor_market" and top["impact"] > 0


# ---------------------------------------------------------------------------
# ML probability on the chart = the Recession Probability card's headline
# ---------------------------------------------------------------------------

def test_batched_ml_matches_single_row_inference(real_db_path):
    if not real_db_path.exists():
        pytest.skip("live DB not present")
    from backend.ml_scorer import compute_ml_score, compute_ml_scores_batch
    rows = [{"yield_curve": 30.0, "labor_market": 20.0, "consumer_health": 70.0},
            None,
            {"financial_stress": 55.5, "energy": 80.0}]
    for h in ("now", "6m", "12m"):
        single = [compute_ml_score(r, horizon=h) if r is not None else None for r in rows]
        assert compute_ml_scores_batch(rows, h) == single


def test_zoomed_last_point_ml_matches_score_card(real_db_path):
    """Regression: the chart plotted the 'now' probability (~0.2%) while the card
    headlines the 12-month one (14.2%), so the rising number never appeared."""
    if not real_db_path.exists():
        pytest.skip("live DB not present")
    import app as flask_app
    client = flask_app.app.test_client()
    card = client.get("/api/score?as_of=2026-09-25").get_json()
    pts = client.get("/api/score/history?resolution=1y&include_ml=true&as_of=2026-09-25").get_json()
    last = pts[-1]
    assert last["ml_12m"] == card["ml_prob_12m"]
    assert last["ml_6m"] == card["ml_prob_6m"]
    assert last["ml_score"] == card["ml_score"]


def test_monthly_history_carries_forward_horizons(real_db_path):
    if not real_db_path.exists():
        pytest.skip("live DB not present")
    import app as flask_app
    pts = flask_app.app.test_client().get(
        "/api/score/history?from_date=2007-01-01&include_ml=true&as_of=2008-12-31").get_json()
    assert all("ml_12m" in p and "ml_6m" in p for p in pts)
    # The 12-month model flagged the 2008 recession in advance.
    assert max(p["ml_12m"] for p in pts if p["date"] < "2008-01-01") > 50
