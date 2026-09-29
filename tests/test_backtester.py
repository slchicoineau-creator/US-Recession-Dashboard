"""Unit tests for the backtester's metric functions (pure, no DB)."""

from __future__ import annotations

from datetime import date

from backend.backtester import (
    _auroc,
    _false_alarm_episodes,
    _lead_times,
    _recession_onsets,
)
from backend.ml_scorer import _add_months


def _months(start: date, values: list) -> dict:
    """Monthly series dict from a list of values starting at `start`."""
    out = {}
    cur = start
    for v in values:
        out[cur] = v
        cur = _add_months(cur, 1)
    return out


# ---------------------------------------------------------------------------
# _recession_onsets
# ---------------------------------------------------------------------------

class TestOnsets:
    def test_finds_episode_starts(self):
        # 11 zeros (2007-01..2007-11), 18 ones (2007-12..2009-05),
        # 100 zeros (2009-06..2017-09), then two ones starting 2017-10.
        nber = _months(date(2007, 1, 1), [0] * 11 + [1] * 18 + [0] * 100 + [1, 1] + [0] * 10)
        onsets = _recession_onsets(nber)
        assert onsets == [date(2007, 12, 1), date(2017, 10, 1)]

    def test_recession_at_series_start_counts(self):
        nber = _months(date(2020, 3, 1), [1, 1, 0, 0])
        assert _recession_onsets(nber) == [date(2020, 3, 1)]


# ---------------------------------------------------------------------------
# _lead_times
# ---------------------------------------------------------------------------

class TestLeadTimes:
    def test_first_alarm_within_window(self):
        # Signal crosses 50 five months before the onset
        onset = date(2008, 1, 1)
        series = _months(date(2007, 1, 1), [10, 10, 10, 10, 10, 10, 10, 60, 65, 70, 80, 90, 95])
        result = _lead_times(series, [onset], threshold=50)
        assert result[0]["lead_months"] == 5
        assert result[0]["first_alarm"] == "2007-08-01"

    def test_never_crossing_is_missed(self):
        onset = date(2008, 1, 1)
        series = _months(date(2007, 1, 1), [10] * 13)
        result = _lead_times(series, [onset], threshold=50)
        assert result[0]["lead_months"] is None
        assert result[0]["first_alarm"] is None

    def test_alarm_older_than_24_months_ignored(self):
        onset = date(2010, 1, 1)
        # Alarm only in 2007 — more than 24 months before the 2010 onset
        series = _months(date(2007, 1, 1), [90, 90] + [10] * 40)
        result = _lead_times(series, [onset], threshold=50)
        assert result[0]["lead_months"] is None


# ---------------------------------------------------------------------------
# _false_alarm_episodes
# ---------------------------------------------------------------------------

class TestFalseAlarms:
    def test_isolated_spike_counts_once(self):
        nber = _months(date(2010, 1, 1), [0] * 60)
        series = _months(date(2010, 1, 1), [10] * 20 + [80, 85, 80] + [10] * 37)
        assert _false_alarm_episodes(series, nber, [], threshold=50) == 1

    def test_alarm_leading_recession_not_false(self):
        onset = date(2012, 1, 1)
        nber = _months(date(2010, 1, 1), [0] * 24 + [1] * 6 + [0] * 30)
        # Alarm 4 months before onset — inside the 18-month grace window
        series = _months(date(2010, 1, 1), [10] * 20 + [80, 85] + [10] * 38)
        assert _false_alarm_episodes(series, nber, [onset], threshold=50) == 0

    def test_alarm_during_recession_not_false(self):
        nber = _months(date(2010, 1, 1), [0] * 12 + [1] * 6 + [0] * 42)
        series = _months(date(2010, 1, 1), [10] * 12 + [90] * 6 + [10] * 42)
        assert _false_alarm_episodes(series, nber, [date(2011, 1, 1)], threshold=50) == 0

    def test_two_separate_false_episodes(self):
        nber = _months(date(2010, 1, 1), [0] * 60)
        series = _months(date(2010, 1, 1),
                         [10] * 5 + [80] * 2 + [10] * 20 + [80] * 3 + [10] * 30)
        assert _false_alarm_episodes(series, nber, [], threshold=50) == 2

    def test_trailing_open_episode_not_counted(self):
        # Alarm still active at the end of the series — future unknown, not false
        nber = _months(date(2010, 1, 1), [0] * 24)
        series = _months(date(2010, 1, 1), [10] * 20 + [80] * 4)
        assert _false_alarm_episodes(series, nber, [], threshold=50) == 0


# ---------------------------------------------------------------------------
# _auroc
# ---------------------------------------------------------------------------

class TestAuroc:
    def test_perfect_separation(self):
        assert _auroc([1, 2, 3, 90, 95], [0, 0, 0, 1, 1]) == 1.0

    def test_inverse_separation(self):
        assert _auroc([90, 95, 1, 2, 3], [0, 0, 1, 1, 1]) == 0.0

    def test_constant_signal_is_coin_flip(self):
        assert _auroc([5, 5, 5, 5], [0, 1, 0, 1]) == 0.5

    def test_single_class_returns_none(self):
        assert _auroc([1, 2, 3], [0, 0, 0]) is None
        assert _auroc([1, 2, 3], [1, 1, 1]) is None
