"""Tests for the September 2026 KPI source-health fixes.

  - GDPNow: the Atlanta Fed moved its workbook and the old URL became a soft
    404 (HTTP 200 + HTML). The download must reject non-xlsx bodies and
    rediscover the link from the landing page, skipping stale links.
  - hotel_occupancy / auto_loan_rate: migrated off manual_csv (0 rows ever)
    to free FRED series; config wiring and threshold calibration.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend import fetcher
from backend.fetcher import _PLAUSIBLE_RANGES, _download_gdpnow_xlsx, load_config

XLSX = b"PK\x03\x04fake-workbook"
SOFT_404 = b"\r\n<!DOCTYPE html><title>404 Page - Not Found</title>"
LANDING = fetcher._ATLANTA_GDPNOW_LANDING


def _resp(content: bytes = b"", status: int = 200, text: str = "", url: str = ""):
    r = MagicMock()
    r.status_code = status
    r.content = content
    r.text = text
    r.url = url
    r.headers = {"Content-Type": "application/xlsx" if content[:2] == b"PK" else "text/html"}
    r.raise_for_status = MagicMock()
    return r


def _router(routes: dict):
    def _get(url, *args, **kwargs):
        if url not in routes:
            raise AssertionError(f"unexpected GET {url}")
        return routes[url]
    return _get


class TestGdpnowDownload:
    def test_known_url_xlsx_is_used_directly(self):
        routes = {fetcher._ATLANTA_GDPNOW_URL: _resp(XLSX)}
        with patch.object(fetcher.requests, "get", side_effect=_router(routes)) as g:
            assert _download_gdpnow_xlsx() == XLSX
        assert g.call_count == 1   # no landing-page discovery

    def test_soft_404_triggers_discovery_and_skips_stale_links(self):
        stale = "https://www.frbatlanta.org/-/media/Documents/cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx?la=en&amp;hash=X"
        moved = "/-/media/Project/NewPlace/GDPTrackingModelDataAndForecasts.xlsx"
        page = f'<a href="{stale}">old</a> <a href="{moved}">new</a>'
        routes = {
            fetcher._ATLANTA_GDPNOW_URL: _resp(SOFT_404),
            LANDING: _resp(text=page, url=LANDING),
            stale.replace("&amp;", "&"): _resp(SOFT_404),
            "https://www.atlantafed.org" + moved: _resp(XLSX),
        }
        with patch.object(fetcher.requests, "get", side_effect=_router(routes)):
            assert _download_gdpnow_xlsx() == XLSX

    def test_all_candidates_soft_404_raises_clear_error(self):
        page = '<a href="/x/GDPTrackingModelDataAndForecasts.xlsx">x</a>'
        routes = {
            fetcher._ATLANTA_GDPNOW_URL: _resp(SOFT_404),
            LANDING: _resp(text=page, url=LANDING),
            "https://www.atlantafed.org/x/GDPTrackingModelDataAndForecasts.xlsx": _resp(SOFT_404),
        }
        with patch.object(fetcher.requests, "get", side_effect=_router(routes)):
            with pytest.raises(RuntimeError, match="soft 404"):
                _download_gdpnow_xlsx()


@pytest.fixture(scope="module")
def kpis():
    return {k["id"]: k for k in load_config()["kpis"]}


class TestGdpnowConfig:
    def test_staleness_window_tighter_than_weekly_default(self, kpis):
        # Nowcasts arrive every few days (max gap 13d since 2022). The 60-day
        # weekly default hid a broken download for weeks.
        assert 13 < kpis["gdp_growth"]["staleness_window_days"] <= 30


class TestManualCsvMigrations:
    def test_hotel_occupancy_uses_accommodation_employment(self, kpis):
        k = kpis["hotel_occupancy"]
        assert k["source"] == "fred"
        assert k["series_id"] == "CES7072100001"
        assert k["frequency"] == "monthly"
        assert k["compute_pct_change_periods"] == 12   # monthly -> YoY
        assert k["invert"] is True
        # Recession troughs -6.2 (2001), -6.9 (2009); the 2026 wobble bottomed
        # at -1.14 and must stay OK.
        assert -1.14 > k["warning_threshold"] > k["danger_threshold"] > -6.2

    def test_hotel_plausible_range_covers_covid_swings(self):
        lo, hi = _PLAUSIBLE_RANGES["hotel_occupancy"]
        assert lo < -48.9 and hi > 34.7

    def test_auto_loan_rate_uses_weekly_bankrate(self, kpis):
        k = kpis["auto_loan_rate"]
        assert k["source"] == "fred"
        assert k["series_id"] == "BRMALR0102"
        assert k["frequency"] == "weekly"
        assert not k.get("compute_pct_change_periods")
        assert k["invert"] is False
        # Series max is 9.81 (2000) and the 5-year max 7.94: DANGER must be
        # reachable and WARNING must be crossable within 5 years.
        assert k["warning_threshold"] <= 7.94
        assert k["danger_threshold"] < 9.81

    def test_auto_loan_plausible_range(self):
        lo, hi = _PLAUSIBLE_RANGES["auto_loan_rate"]
        assert lo < 3.85 and hi > 9.81


class TestYfinanceYoY:
    def test_yfinance_pct_change_kpis_are_daily_252(self, kpis):
        # pct_change is row-based. Yahoo's monthly bars skip whole months for
        # thin contracts (LBR=F: 9 gaps since 2022), so pct_change(12) on them
        # is not a YoY change. Daily bars with 252 periods are complete.
        for k in kpis.values():
            if k.get("source") == "yfinance" and k.get("compute_pct_change_periods"):
                assert k["frequency"] == "daily", k["id"]
                assert k["compute_pct_change_periods"] == 252, k["id"]
