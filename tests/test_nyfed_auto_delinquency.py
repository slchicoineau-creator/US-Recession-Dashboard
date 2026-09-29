"""Tests for the NY Fed Consumer Credit Panel auto delinquency KPI.

Covers the `scrape_nyfed_auto` source added 2026-07 to replace `vehicle_repos`:
  - the sheet parser (header/column discovery, "YY:QN" label parsing)
  - the workbook discovery walk-back, which must not trust HTTP 200
  - config wiring and threshold calibration against known regimes
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from backend.fetcher import (
    _PLAUSIBLE_RANGES,
    _RETIRED_KPI_IDS,
    _fetch_nyfed_hhdc_workbook,
    load_config,
)

KPI_ID = "auto_90d_delinquency"


@pytest.fixture(scope="module")
def kpi():
    matches = [k for k in load_config()["kpis"] if k["id"] == KPI_ID]
    assert matches, f"{KPI_ID} missing from kpi_config.yaml"
    return matches[0]


class TestConfig:
    def test_source_and_frequency(self, kpi):
        assert kpi["source"] == "scrape_nyfed_auto"
        assert kpi["frequency"] == "quarterly"
        # No transform: thresholds are raw percentages.
        assert not kpi.get("compute_pct_change_periods")
        assert not kpi.get("compute_diff")

    def test_thresholds_calibrated_to_history(self, kpi):
        # 90+ delinquency ran 1.99-5.60% over 2003Q1-2026Q1. Thresholds must sit
        # above the 2015-19 expansion range (max 4.94) so the KPI is not pinned
        # to WARNING during good times, and DANGER must sit at/above the
        # 2010Q4 GFC peak of 5.27.
        assert kpi["warning_threshold"] == 4.8
        assert kpi["danger_threshold"] == 5.25
        assert kpi["invert"] is False

    def test_lagging_and_consumer_health(self, kpi):
        # 90+ day delinquency is a realised-loss measure — tagging it `leading`
        # would corrupt the leading index and the backtester.
        assert kpi["timing"] == "lagging"
        assert kpi["category"] == "consumer_health"

    def test_plausible_range_covers_raw_percent(self):
        lo, hi = _PLAUSIBLE_RANGES[KPI_ID]
        assert lo < 1.99 and hi > 5.60

    def test_old_vehicle_repos_kpi_is_retired(self):
        ids = {k["id"] for k in load_config()["kpis"]}
        assert "vehicle_repos" not in ids
        assert "vehicle_repos" in _RETIRED_KPI_IDS


def _fake_sheet() -> pd.DataFrame:
    """Mimic the layout of the real 'Page 12 Data' sheet."""
    return pd.DataFrame([
        ["Percent of Balance 90+ Days Delinquent by Loan Type", None, None, None, None],
        ["Percent", None, None, None, None],
        ["Return to Table of Contents", None, None, None, None],
        [None, "MORTGAGE", "HELOC", "AUTO", "CC"],
        ["03:Q1", 1.21, 0.35, 2.33, 8.84],
        ["10:Q4", 2.90, 1.10, 5.27, 11.20],
        ["26:Q1", 1.09, 0.95, 5.60, 13.12],
        [None, None, None, None, None],
    ])


class TestParser:
    def _run(self, sheet):
        from backend import fetcher
        with patch.object(fetcher, "_fetch_nyfed_hhdc_workbook", return_value=b"PK-stub"), \
             patch.object(fetcher.pd, "read_excel", return_value=sheet):
            return fetcher.fetch_nyfed_auto_delinquency()

    def test_parses_auto_column_by_name(self):
        s = self._run(_fake_sheet())
        assert list(s.values) == [2.33, 5.27, 5.60]

    def test_quarter_labels_map_to_quarter_start_dates(self):
        s = self._run(_fake_sheet())
        assert list(s.index) == [date(2003, 1, 1), date(2010, 10, 1), date(2026, 1, 1)]

    def test_finds_auto_when_columns_are_reordered(self):
        sheet = _fake_sheet()
        # Report editions have moved the loan-type columns around; the parser
        # must key off the header text, not a fixed offset.
        sheet = sheet[[0, 3, 1, 2, 4]]
        sheet.columns = range(5)
        s = self._run(sheet)
        assert list(s.values) == [2.33, 5.27, 5.60]

    def test_raises_when_auto_column_absent(self):
        sheet = _fake_sheet()
        sheet.iloc[3, 3] = "STUDENT LOAN"
        with pytest.raises(RuntimeError, match="AUTO"):
            self._run(sheet)

    def test_ignores_non_quarter_rows(self):
        sheet = _fake_sheet()
        sheet.loc[len(sheet)] = ["Source: New York Fed CCP", None, None, "n/a", None]
        s = self._run(sheet)
        assert len(s) == 3


class TestWorkbookDiscovery:
    """An unpublished quarter returns HTTP 200 with an HTML error page, so
    status codes are useless — only the xlsx zip magic bytes are reliable."""

    def test_walks_back_past_unpublished_quarters(self):
        from backend import fetcher

        class Resp:
            def __init__(self, content):
                self.status_code = 200
                self.content = content

        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            # First two quarters not yet published -> HTML error page.
            return Resp(b"PK\x03\x04xlsx" if len(calls) > 2 else b"<!DOCTYPE html>")

        with patch.object(fetcher.requests, "get", side_effect=fake_get):
            content = _fetch_nyfed_hhdc_workbook()

        assert content.startswith(b"PK")
        assert len(calls) == 3

    def test_raises_after_exhausting_lookback(self):
        from backend import fetcher

        class Resp:
            status_code = 200
            content = b"<!DOCTYPE html>"

        with patch.object(fetcher.requests, "get", return_value=Resp()):
            with pytest.raises(RuntimeError, match="No NY Fed HHDC workbook"):
                _fetch_nyfed_hhdc_workbook(max_lookback=3)

    def test_survives_transient_request_errors(self):
        from backend import fetcher

        class Resp:
            status_code = 200
            content = b"PK\x03\x04xlsx"

        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise ConnectionError("boom")
            return Resp()

        with patch.object(fetcher.requests, "get", side_effect=fake_get):
            assert _fetch_nyfed_hhdc_workbook().startswith(b"PK")


class TestIncrementalSkip:
    """Rows are dated to the quarter start, so fetch_kpi's generic
    "(today - latest).days < 1" guard can never trip. Without the `since`
    check the ~1MB workbook would be re-downloaded every daily refresh."""

    @staticmethod
    def _head_resp(is_xlsx: bool):
        class Resp:
            status_code = 200
            headers = {
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if is_xlsx else "text/html; charset=utf-8"
                )
            }
        return Resp()

    def test_skips_download_when_latest_quarter_already_stored(self):
        from backend import fetcher

        seen = []

        def fake_head(url, **kwargs):
            seen.append(url)
            return self._head_resp("2026Q1" in url)

        with patch.object(fetcher.requests, "head", side_effect=fake_head), \
             patch.object(fetcher, "_fetch_nyfed_hhdc_workbook") as dl, \
             patch.object(fetcher, "date", wraps=date) as fake_date:
            fake_date.today.return_value = date(2026, 7, 29)
            s = fetcher.fetch_nyfed_auto_delinquency(since=date(2026, 1, 1))

        assert s.empty
        dl.assert_not_called()          # no ~1MB GET
        assert seen                     # discovery still happened, via HEAD

    def test_downloads_when_a_newer_quarter_is_published(self):
        from backend import fetcher

        with patch.object(fetcher.requests, "head",
                          side_effect=lambda url, **kw: self._head_resp("2026Q2" in url)), \
             patch.object(fetcher, "_fetch_nyfed_hhdc_workbook",
                          return_value=b"PK-stub") as dl, \
             patch.object(fetcher.pd, "read_excel", return_value=_fake_sheet()), \
             patch.object(fetcher, "date", wraps=date) as fake_date:
            fake_date.today.return_value = date(2026, 7, 29)
            s = fetcher.fetch_nyfed_auto_delinquency(since=date(2026, 1, 1))

        dl.assert_called_once()
        assert not s.empty

    def test_full_backfill_ignores_since(self):
        from backend import fetcher

        with patch.object(fetcher, "_fetch_nyfed_hhdc_workbook",
                          return_value=b"PK-stub") as dl, \
             patch.object(fetcher.pd, "read_excel", return_value=_fake_sheet()):
            s = fetcher.fetch_nyfed_auto_delinquency(since=None)

        dl.assert_called_once()
        assert len(s) == 3

    def test_falls_back_to_get_when_head_is_unusable(self):
        from backend import fetcher

        with patch.object(fetcher.requests, "head", side_effect=ConnectionError("no HEAD")), \
             patch.object(fetcher, "_fetch_nyfed_hhdc_workbook",
                          return_value=b"PK-stub") as dl, \
             patch.object(fetcher.pd, "read_excel", return_value=_fake_sheet()):
            s = fetcher.fetch_nyfed_auto_delinquency(since=date(2026, 1, 1))

        # HEAD discovery failed -> must not silently stop fetching.
        dl.assert_called_once()
        assert not s.empty
