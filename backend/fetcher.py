"""
Data fetcher for the Recession Risk Dashboard.

Dispatches to the correct API client for each KPI source:
  - fred    : fredapi Python package
  - bls     : BLS public API v2
  - eia     : EIA API v2
  - yfinance: Yahoo Finance (S&P 500, VIX)
  - tsa     : TSA public CSV (passenger throughput)
  - scrape_nyfed_auto: NY Fed Household Debt & Credit xlsx (auto delinquency)
  - manual_csv: skipped; handled via Settings page upload endpoint
"""

import io
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv

from backend.models import KpiData, NberRecession, get_session, init_db

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load KPI config
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "kpi_config.yaml")

# BLS/Census-style government releases revise recent months after first
# publication (e.g. CES payrolls gets two revision rounds in the two months
# following initial release). Every incremental FRED fetch re-requests this
# trailing window and upserts, so revisions are picked up automatically
# instead of the DB permanently keeping the first-published value.
# NOTE: this window does NOT cover annual benchmark/seasonal-factor
# revisions (e.g. BLS's February benchmark), which can revise years of
# history — those still require a periodic full (incremental=False) refetch.
REVISION_LOOKBACK_DAYS = 120

def load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def _retry(func, max_retries=3, base_delay=2):
    """Exponential-backoff retry wrapper."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            delay = base_delay ** attempt
            logger.warning("Attempt %d failed (%s). Retrying in %ss…", attempt + 1, exc, delay)
            time.sleep(delay)


# ---------------------------------------------------------------------------
# FRED fetcher
# ---------------------------------------------------------------------------

def fetch_fred_series(series_id: str, start_date: date, end_date: date) -> pd.Series:
    """Fetch a FRED series via fredapi. Returns a pandas Series indexed by date."""
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        raise RuntimeError("FRED_API_KEY not set")

    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)
    except ImportError:
        raise RuntimeError("fredapi package not installed. Run: pip install fredapi")

    def _fetch():
        return fred.get_series(
            series_id,
            observation_start=start_date.strftime("%Y-%m-%d"),
            observation_end=end_date.strftime("%Y-%m-%d"),
        )

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# BLS fetcher
# ---------------------------------------------------------------------------

def fetch_bls_series(series_id: str, start_year: int, end_year: int) -> pd.Series:
    """Fetch a BLS series via the public API v2."""
    api_key = os.getenv("BLS_API_KEY", "")
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    payload = {
        "seriesid": [series_id],
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if api_key:
        payload["registrationkey"] = api_key

    def _fetch():
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API error: {data.get('message', data)}")
        rows = data["Results"]["series"][0]["data"]
        records = {}
        for row in rows:
            try:
                period = row["period"]  # e.g. M01
                if period.startswith("M") and period != "M13":
                    month = int(period[1:])
                    d = date(int(row["year"]), month, 1)
                    records[d] = float(row["value"].replace(",", ""))
            except (ValueError, KeyError):
                continue
        return pd.Series(records).sort_index()

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# EIA fetcher
# ---------------------------------------------------------------------------

def fetch_eia_series(series_id: str) -> pd.Series:
    """Fetch a weekly/daily EIA series via EIA API v2."""
    api_key = os.getenv("EIA_API_KEY", "")
    if not api_key:
        raise RuntimeError("EIA_API_KEY not set")

    url = f"https://api.eia.gov/v2/seriesid/{series_id}"
    params = {"api_key": api_key, "data[0]": "value"}

    def _fetch():
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("response", {}).get("data", [])
        records = {}
        for row in rows:
            try:
                d = pd.to_datetime(row["period"]).date()
                records[d] = float(row["value"])
            except (ValueError, KeyError, TypeError):
                continue
        return pd.Series(records).sort_index()

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# yfinance fetcher
# ---------------------------------------------------------------------------

def fetch_yfinance(ticker: str, start: date, end: date, frequency: str = "daily") -> pd.Series:
    """Fetch closing prices from Yahoo Finance. frequency: 'daily' or 'monthly'."""
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance package not installed. Run: pip install yfinance")

    def _fetch():
        interval = "1mo" if frequency == "monthly" else "1d"
        df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                         end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                         interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            raise RuntimeError(f"No data returned for {ticker}")
        close = df["Close"]
        # yfinance 0.2+ returns MultiIndex columns for single tickers; flatten to Series
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        series = close.squeeze()
        # squeeze() on a 1-row Series returns a numpy scalar; close may also be a
        # scalar in some yfinance versions for single-day windows.
        if not isinstance(series, pd.Series):
            if hasattr(close, 'index'):
                idx = close.index
            else:
                idx = df.index  # fallback: use the original DataFrame's DatetimeIndex
            series = pd.Series([float(series)], index=idx)
        if hasattr(series.index, "date"):
            series.index = [d.date() if hasattr(d, "date") else d for d in series.index]
        return series

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# TSA throughput fetcher
# ---------------------------------------------------------------------------

def _fetch_enplane_historical() -> pd.Series:
    """Fetch FRED ENPLANE (monthly US air enplanements, thousands) and convert
    to estimated daily passenger counts as a historical TSA proxy.

    ENPLANE = 'Enplanements for U.S. Air Carrier Domestic and International,
    Scheduled Passenger Flights' — BTS/DOT, monthly, 2000-present.
    Units: thousands of passengers per month.
    Conversion: daily average = value * 1000 / days_in_month.
    Scale matches TSA checkpoint counts well (2019 avg ~2.4M/day in both series).
    """
    import calendar
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        logger.warning("FRED_API_KEY not set — skipping ENPLANE historical backfill")
        return pd.Series(dtype=float)

    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)
        series = fred.get_series(
            "ENPLANE",
            observation_start="2000-01-01",
            observation_end=date.today().strftime("%Y-%m-%d"),
        )
        # Convert monthly thousands to estimated daily average
        records = {}
        for dt, val in series.items():
            if pd.isna(val) or val <= 0:
                continue
            d = dt.date() if hasattr(dt, "date") else dt
            days = calendar.monthrange(d.year, d.month)[1]
            records[d] = (val * 1000) / days
        return pd.Series(records).sort_index()
    except Exception as exc:
        logger.warning("Failed to fetch ENPLANE historical data: %s", exc)
        return pd.Series(dtype=float)


def fetch_tsa_throughput() -> pd.Series:
    """Fetch TSA daily passenger throughput from the public HTML table,
    backfilled with FRED ENPLANE monthly data for historical coverage.

    TSA page format (as of 2026): two columns [Date (M/D/YYYY), Numbers].
    Previously the page had multi-year columns [MM/DD, 2026, 2025, ...];
    the scraper handles both formats for robustness.
    TSA only publishes ~80 days of data; ENPLANE (FRED) provides monthly
    data back to 2000 as a daily-average proxy. TSA daily data takes
    precedence over ENPLANE estimates for overlapping dates.
    """
    url = "https://www.tsa.gov/travel/passenger-volumes"

    def _fetch():
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        if not tables:
            raise RuntimeError("No tables found on TSA page")
        df = tables[0]
        df.columns = [str(c).strip() for c in df.columns]
        date_col = df.columns[0]
        today = date.today()

        # Check for old multi-year column format (columns are numeric years)
        year_cols = [c for c in df.columns[1:] if c.isdigit() and 2000 < int(c) <= today.year]

        records = {}
        for _, row in df.iterrows():
            date_str = str(row[date_col]).strip()
            if not date_str or date_str.lower() in ("nan", "date"):
                continue

            if year_cols:
                # Old format: date col = MM/DD, value cols = year labels
                for year_col in year_cols:
                    try:
                        year = int(year_col)
                        d = datetime.strptime(f"{date_str}/{year}", "%m/%d/%Y").date()
                        if d > today:
                            continue
                        raw = str(row[year_col]).replace(",", "").strip()
                        if not raw or raw.lower() == "nan":
                            continue
                        v = float(raw)
                        if v > 0:
                            records[d] = v
                    except (ValueError, TypeError):
                        continue
            else:
                # New format (2026+): date col has full date M/D/YYYY, col 2 = Numbers
                try:
                    d = pd.to_datetime(date_str).date()
                    if d > today:
                        continue
                    raw = str(row[df.columns[1]]).replace(",", "").strip()
                    if not raw or raw.lower() == "nan":
                        continue
                    v = float(raw)
                    if v > 0:
                        records[d] = v
                except (ValueError, TypeError):
                    continue

        tsa_series = pd.Series(records).sort_index()

        # Backfill with FRED ENPLANE for historical coverage (TSA data takes precedence)
        enplane = _fetch_enplane_historical()
        if not enplane.empty:
            # Only use ENPLANE dates not already covered by TSA daily data
            tsa_dates = set(tsa_series.index)
            enplane_fill = enplane[~enplane.index.isin(tsa_dates)]
            combined = pd.concat([enplane_fill, tsa_series]).sort_index()
            logger.info("TSA throughput: %d TSA daily rows + %d ENPLANE historical rows",
                        len(tsa_series), len(enplane_fill))
            return combined

        return tsa_series

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# Shiller CAPE Ratio scraper (multpl.com)
# ---------------------------------------------------------------------------

def fetch_shiller_cape() -> pd.Series:
    """Fetch Shiller CAPE ratio from multpl.com HTML table."""
    url = "https://www.multpl.com/shiller-pe/table/by-month"

    def _fetch():
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        if not tables:
            raise RuntimeError("No tables found on multpl.com CAPE page")
        df = tables[0]
        records = {}
        for _, row in df.iterrows():
            try:
                d = pd.to_datetime(str(row.iloc[0])).date()
                v = float(str(row.iloc[1]).replace(",", "").strip())
                if v > 0:
                    records[d] = v
            except (ValueError, TypeError):
                continue
        return pd.Series(records).sort_index()

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# Atlanta Fed GDPNow scraper (xlsx direct from atlantafed.org)
# ---------------------------------------------------------------------------

# Moved 2026-09 from .../Documents/cqer/researchcq/gdpnow/ when the Atlanta Fed
# reorganised its site. The old path now returns HTTP 200 with an HTML "404
# Page" (a soft 404), so raise_for_status() cannot detect a move — the zip
# magic-byte check below is what does. On a miss, the xlsx link is rediscovered
# from the GDPNow landing page, so the next site move self-heals.
_ATLANTA_GDPNOW_URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
    "research-and-data/data/gdpnow/GDPTrackingModelDataAndForecasts.xlsx"
)
_ATLANTA_GDPNOW_LANDING = "https://www.atlantafed.org/research-and-data/data/gdpnow"
_GDPNOW_XLSX_LINK_RE = re.compile(
    r"""["']([^"']*GDPTrackingModelDataAndForecasts\.xlsx[^"']*)["']""", re.I
)


def _download_gdpnow_xlsx() -> bytes:
    """Return the GDPNow workbook bytes, rediscovering the URL if it moved.

    Tries the known URL, then every xlsx link on the landing page (the page
    also carries stale legacy links, so each candidate is tried and only a
    real xlsx — zip magic bytes ``PK`` — is accepted).
    """
    headers = {"User-Agent": "Mozilla/5.0"}

    def _get_xlsx(url: str) -> Optional[bytes]:
        try:
            resp = requests.get(url, timeout=60, headers=headers)
        except requests.RequestException as exc:
            logger.warning("GDPNow: GET %s failed: %s", url, exc)
            return None
        if resp.status_code == 200 and resp.content[:2] == b"PK":
            return resp.content
        logger.warning("GDPNow: %s is not an xlsx (HTTP %s, %s) — soft 404?",
                       url, resp.status_code, resp.headers.get("Content-Type"))
        return None

    content = _get_xlsx(_ATLANTA_GDPNOW_URL)
    if content is not None:
        return content

    page = requests.get(_ATLANTA_GDPNOW_LANDING, timeout=60, headers=headers)
    page.raise_for_status()
    seen = {_ATLANTA_GDPNOW_URL}
    for link in _GDPNOW_XLSX_LINK_RE.findall(page.text):
        url = requests.compat.urljoin(page.url, link.replace("&amp;", "&"))
        if url in seen:
            continue
        seen.add(url)
        content = _get_xlsx(url)
        if content is not None:
            logger.error("GDPNow: workbook moved — found at %s; update "
                         "_ATLANTA_GDPNOW_URL in backend/fetcher.py", url)
            return content
    raise RuntimeError(
        "Atlanta Fed GDPNow workbook not found: the known URL is a soft 404 and "
        f"no xlsx link on {_ATLANTA_GDPNOW_LANDING} returned a workbook"
    )


def fetch_atlanta_gdpnow() -> pd.Series:
    """Fetch GDPNow headline nowcasts direct from Atlanta Fed xlsx.

    Replaces FRED GDPNOW series which stopped publishing after 2026-01-01.
    Combines three sheets for full history:
      - TrackingDeepArchives  (2011-08 to ~2014)
      - TrackingArchives      (2014-05 to last completed quarter)
      - CurrentQtrEvolution   (live current-quarter nowcasts)

    Returns a date-indexed Series of GDP nowcast %, one value per forecast date.
    """
    def _fetch():
        buf = io.BytesIO(_download_gdpnow_xlsx())

        records = {}

        # Archive sheets: col 0 = Forecast Date, col 27 = GDP Nowcast headline
        for sheet in ("TrackingDeepArchives", "TrackingArchives"):
            try:
                df = pd.read_excel(buf, sheet_name=sheet, header=0)
                buf.seek(0)
            except Exception as exc:
                logger.warning("GDPNow: could not read sheet %s: %s", sheet, exc)
                continue
            if "Forecast Date" not in df.columns or "GDP Nowcast" not in df.columns:
                logger.warning("GDPNow: sheet %s missing expected columns", sheet)
                continue
            for _, row in df.iterrows():
                fd = row["Forecast Date"]
                gv = row["GDP Nowcast"]
                if pd.isna(fd) or pd.isna(gv):
                    continue
                d = fd.date() if hasattr(fd, "date") else pd.to_datetime(fd).date()
                records[d] = float(gv)

        # CurrentQtrEvolution: three groups of (Date, Major Releases, GDP*) in columns
        # 0..2, 3..5, 6..8. Headline GDP value is the 3rd column of each group.
        try:
            evo = pd.read_excel(buf, sheet_name="CurrentQtrEvolution", header=0)
            buf.seek(0)
            for col_base in (0, 3, 6):
                if col_base + 2 >= evo.shape[1]:
                    continue
                date_col = evo.iloc[:, col_base]
                val_col = evo.iloc[:, col_base + 2]
                for dt, val in zip(date_col, val_col):
                    if pd.isna(dt) or pd.isna(val):
                        continue
                    d = dt.date() if hasattr(dt, "date") else pd.to_datetime(dt).date()
                    records[d] = float(val)
        except Exception as exc:
            logger.warning("GDPNow: could not read CurrentQtrEvolution: %s", exc)

        if not records:
            raise RuntimeError("Atlanta Fed GDPNow xlsx returned no parseable rows")

        return pd.Series(records).sort_index()

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# NY Fed Household Debt & Credit — auto loan delinquency
# ---------------------------------------------------------------------------

_NYFED_HHDC_URL = (
    "https://www.newyorkfed.org/medialibrary/interactives/householdcredit/"
    "data/xls/HHD_C_Report_{year}Q{quarter}.xlsx"
)

def _quarter_start(year: int, quarter: int) -> date:
    return date(year, 3 * (quarter - 1) + 1, 1)


def _iter_recent_quarters(max_lookback: int):
    """Yield (year, quarter) pairs newest-first from the current quarter."""
    today = date.today()
    year, quarter = today.year, (today.month - 1) // 3 + 1
    for _ in range(max_lookback):
        yield year, quarter
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4


# NOTE: a URL for an unpublished quarter returns HTTP **200** with an HTML
# error page, not a 404 — raise_for_status() will not catch it. The only
# reliable checks are the content type (HEAD) and the zip magic bytes (GET).
def _find_latest_nyfed_quarter(max_lookback: int = 6) -> Optional[tuple]:
    """HEAD-probe backward for the newest published quarter.

    Discovery this way costs a few hundred bytes per probe instead of ~1MB, so
    the daily refresh can decide whether a download is warranted at all.
    Returns (year, quarter), or None if HEAD is unusable (then fall back to GET).
    """
    for year, quarter in _iter_recent_quarters(max_lookback):
        url = _NYFED_HHDC_URL.format(year=year, quarter=quarter)
        try:
            resp = requests.head(url, timeout=30, allow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:
            logger.warning("NY Fed HHDC: HEAD failed for %sQ%s: %s", year, quarter, exc)
            return None
        if resp.status_code == 200 and "spreadsheet" in resp.headers.get("Content-Type", ""):
            return year, quarter
    return None


def _fetch_nyfed_hhdc_workbook(max_lookback: int = 6) -> bytes:
    """Download the newest published Household Debt & Credit workbook.

    The file name embeds the reference quarter and there is no index to query,
    so walk backward from the current quarter until a real xlsx comes back.
    """
    for year, quarter in _iter_recent_quarters(max_lookback):
        url = _NYFED_HHDC_URL.format(year=year, quarter=quarter)
        try:
            resp = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:
            logger.warning("NY Fed HHDC: request failed for %sQ%s: %s", year, quarter, exc)
            resp = None

        # An xlsx is a zip archive — "PK" magic bytes are the ground truth.
        if resp is not None and resp.status_code == 200 and resp.content[:2] == b"PK":
            logger.info("NY Fed HHDC: using %sQ%s workbook", year, quarter)
            return resp.content

    raise RuntimeError(
        f"No NY Fed HHDC workbook found in the last {max_lookback} quarters"
    )


def fetch_nyfed_auto_delinquency(since: Optional[date] = None) -> pd.Series:
    """Percent of auto loan balance 90+ days delinquent (NY Fed CCP, quarterly).

    Source: "Page 12 Data" sheet of the Quarterly Report on Household Debt and
    Credit. Covers the full credit-bureau universe (banks, credit unions,
    captive finance arms and subprime finance companies), unlike the
    bank-only FRED delinquency series, which is why this one reaches record
    highs while DRCLACBS does not.

    `since` is the newest observation already stored. Quarter-start dating means
    the caller's generic "is it up to date?" guard can never trip (the latest row
    is always months old), so without this the ~1MB workbook would be downloaded
    and re-parsed on every daily refresh to save zero rows. When the newest
    published quarter is one we already have, return an empty Series instead.

    Returns a date-indexed Series of % values, one per quarter from 2003Q1.
    """
    if since is not None:
        latest = _find_latest_nyfed_quarter()
        if latest is not None and _quarter_start(*latest) <= since:
            logger.info(
                "NY Fed HHDC: newest published report is %sQ%s, already stored "
                "(latest=%s) — skipping download", latest[0], latest[1], since,
            )
            return pd.Series(dtype="float64", index=pd.Index([], dtype="object"))

    def _fetch():
        content = _fetch_nyfed_hhdc_workbook()
        df = pd.read_excel(io.BytesIO(content), sheet_name="Page 12 Data", header=None)

        # Locate the header row and the AUTO column by name rather than by a
        # fixed offset — the sheet layout differs page to page and shifts
        # between report editions.
        header_row = auto_col = None
        for i in range(min(12, len(df))):
            row = [str(v).strip().upper() for v in df.iloc[i].tolist()]
            if "AUTO" in row:
                header_row, auto_col = i, row.index("AUTO")
                break
        if header_row is None:
            raise RuntimeError("NY Fed HHDC: no AUTO column found on 'Page 12 Data'")

        records = {}
        for _, row in df.iloc[header_row + 1:].iterrows():
            label, val = row.iloc[0], row.iloc[auto_col]
            if pd.isna(label) or pd.isna(val):
                continue
            # Labels look like "26:Q1" — two-digit year, quarter number.
            m = re.match(r"^\s*(\d{2}):Q([1-4])\s*$", str(label))
            if not m:
                continue
            yy, q = int(m.group(1)), int(m.group(2))
            # Series begins 2003Q1, so every two-digit year is 20xx.
            records[date(2000 + yy, 3 * (q - 1) + 1, 1)] = float(val)

        if not records:
            raise RuntimeError("NY Fed HHDC: 'Page 12 Data' returned no parseable rows")

        return pd.Series(records).sort_index()

    return _retry(_fetch)


# ---------------------------------------------------------------------------
# S&P 500 200-Day Moving Average (derived)
# ---------------------------------------------------------------------------

def fetch_derived_ma(ticker: str, start: date, end: date, ma_window: int = 200) -> pd.Series:
    """Fetch daily prices and compute % distance from N-day SMA.

    Returns: Series of (date -> pct_distance) where
    pct_distance = (close - SMA) / SMA * 100
    """
    # Need extra history for the MA window warmup
    extended_start = start - timedelta(days=int(ma_window * 1.5))
    raw = fetch_yfinance(ticker, extended_start, end, frequency="daily")
    if raw.empty:
        raise RuntimeError(f"No data for {ticker}")

    sma = raw.rolling(window=ma_window, min_periods=ma_window).mean()
    pct_distance = ((raw - sma) / sma) * 100
    pct_distance = pct_distance.dropna()

    # Trim to requested date range (remove warmup period)
    pct_distance = pct_distance[
        [(x.date() if hasattr(x, "date") else x) >= start for x in pct_distance.index]
    ]
    return pct_distance


# ---------------------------------------------------------------------------
# Relative performance of two tickers (derived price ratio)
# ---------------------------------------------------------------------------

def fetch_derived_relative(kpi: dict, start: date, end: date) -> pd.Series:
    """Daily price ratio series_id / benchmark_ticker (e.g. RSP / SPY).

    Returns the raw ratio; the KPI's `compute_pct_change_periods` (applied in
    fetch_kpi) turns it into relative performance over N trading days. Dates
    where either ticker has no close are dropped rather than forward-filled,
    so a holiday mismatch can't fabricate a ratio.
    """
    ticker = kpi["series_id"]
    benchmark = kpi.get("benchmark_ticker")
    if not benchmark:
        raise RuntimeError(f"derived_relative KPI {kpi['id']} has no benchmark_ticker")
    num = fetch_yfinance(ticker, start, end, frequency="daily")
    den = fetch_yfinance(benchmark, start, end, frequency="daily")
    ratio = (num / den).dropna()
    if ratio.empty:
        raise RuntimeError(f"No overlapping data for {ticker}/{benchmark}")
    return ratio


# ---------------------------------------------------------------------------
# Buffett Indicator — derived ratio (Market Cap / GDP)
# ---------------------------------------------------------------------------

def fetch_derived_ratio(kpi: dict, start_date: date, end_date: date) -> pd.Series:
    """Fetch two FRED series, align frequencies, compute ratio * 100.

    Handles the Buffett Indicator pattern: daily numerator / quarterly denominator.
    The denominator is forward-filled to match the numerator's dates,
    then the result is resampled to quarter-end dates.
    """
    num_cfg = kpi["ratio_numerator"]
    den_cfg = kpi["ratio_denominator"]

    if num_cfg["source"] != "fred" or den_cfg["source"] != "fred":
        raise RuntimeError("derived_ratio currently only supports FRED sources")

    numerator = fetch_fred_series(num_cfg["series_id"], start_date, end_date)
    denominator = fetch_fred_series(den_cfg["series_id"], start_date, end_date)

    if numerator.empty or denominator.empty:
        # Normal on incremental fetches: quarterly inputs often have no new
        # observations since the last stored row. A truly dead input series is
        # caught by check_staleness, not here.
        logger.info(
            "derived_ratio %s: no observations in window %s..%s (num=%d, den=%d) — skipping",
            kpi.get("id", "?"), start_date, end_date, len(numerator), len(denominator),
        )
        return pd.Series(dtype=float)

    # Apply unit conversions if specified (e.g. NCBCEL millions -> billions)
    if num_cfg.get("unit_divisor"):
        numerator = numerator / float(num_cfg["unit_divisor"])
    if den_cfg.get("unit_divisor"):
        denominator = denominator / float(den_cfg["unit_divisor"])

    # Publication lag check: NCBCEL and GDP publish ~30-45 days apart. When the
    # numerator is much newer, the latest ratios silently use a stale denominator.
    num_last = numerator.index[-1]
    den_last = denominator.index[-1]
    lag_days = (pd.Timestamp(num_last) - pd.Timestamp(den_last)).days
    if lag_days > 45:
        logger.warning(
            "derived_ratio %s: numerator (%s) is %d days newer than denominator (%s) — "
            "latest ratio values use a stale denominator",
            kpi.get("id", "?"), num_cfg["series_id"], lag_days, den_cfg["series_id"],
        )

    # Align: forward-fill denominator to numerator's dates
    combined_idx = numerator.index.union(denominator.index).sort_values()
    den_aligned = denominator.reindex(combined_idx).ffill()
    num_aligned = numerator.reindex(combined_idx).ffill()

    # Compute ratio as percentage
    ratio = (num_aligned / den_aligned) * 100
    ratio = ratio.dropna()

    # Resample to quarter-end to avoid storing noisy daily ratios
    ratio.index = pd.to_datetime(ratio.index)
    quarterly = ratio.resample("QE").last().dropna()

    # Convert index back to date objects for consistency
    quarterly.index = [d.date() for d in quarterly.index]

    return quarterly


# ---------------------------------------------------------------------------
# NBER recession shading (USRECM)
# ---------------------------------------------------------------------------

def fetch_nber_shading() -> None:
    """Fetch FRED USRECM (monthly 0/1 recession indicator) and cache to DB."""
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        logger.warning("FRED_API_KEY not set — skipping NBER shading fetch")
        return

    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)
    except ImportError:
        return

    end = date.today()
    start = date(end.year - 21, end.month, 1)

    try:
        series = fred.get_series("USRECM",
                                  observation_start=start.strftime("%Y-%m-%d"),
                                  observation_end=end.strftime("%Y-%m-%d"))
    except Exception as exc:
        logger.error("Failed to fetch NBER shading: %s", exc)
        return

    session = get_session()
    try:
        for idx, val in series.items():
            d = idx.date() if hasattr(idx, "date") else idx
            rec = session.get(NberRecession, d)
            if rec is None:
                rec = NberRecession(date=d, in_recession=bool(val == 1))
                session.add(rec)
            else:
                rec.in_recession = bool(val == 1)
        session.commit()
        logger.info("NBER recession shading updated: %d months", len(series))
    except Exception as exc:
        session.rollback()
        logger.error("DB error saving NBER shading: %s", exc)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Benchmark reference series (kpi_config.yaml `reference_series:`)
# ---------------------------------------------------------------------------

def fetch_reference_series() -> None:
    """Fetch every `reference_series:` entry in full and upsert it.

    These are small monthly series (<1k rows each), so a full refetch is cheap
    and picks up revisions for free (no incremental bookkeeping needed).
    Stored in ReferenceSeries, never in KpiData/NberRecession — see the config
    comment for why.
    """
    from backend.models import ReferenceSeries

    if not os.getenv("FRED_API_KEY", ""):
        logger.warning("FRED_API_KEY not set — skipping reference series fetch")
        return

    for ref in load_config().get("reference_series", []) or []:
        key, series_id = ref["key"], ref["series_id"]
        start = date.fromisoformat(str(ref.get("start", "1959-01-01")))
        try:
            series = fetch_fred_series(series_id, start, date.today()).dropna()
        except Exception as exc:
            logger.error("Reference series %s (%s) fetch failed: %s", key, series_id, exc)
            continue

        session = get_session()
        try:
            existing = {
                row.date: row
                for row in session.query(ReferenceSeries).filter_by(series_key=key).all()
            }
            now = datetime.utcnow()
            for idx, val in series.items():
                d = idx.date() if hasattr(idx, "date") else idx
                row = existing.get(d)
                if row is None:
                    session.add(ReferenceSeries(series_key=key, date=d,
                                                value=float(val), fetched_at=now))
                else:
                    row.value = float(val)
                    row.fetched_at = now
            session.commit()
            logger.info("Reference series %s (%s): %d observations", key, series_id, len(series))
        except Exception as exc:
            session.rollback()
            logger.error("DB error saving reference series %s: %s", key, exc)
        finally:
            session.close()


def reference_series_empty() -> bool:
    """True when no reference series rows exist yet (first launch after upgrade)."""
    from backend.models import ReferenceSeries
    session = get_session()
    try:
        return session.query(ReferenceSeries.id).first() is None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Plausibility validation
# ---------------------------------------------------------------------------

_PLAUSIBLE_RANGES = {
    "t10y2y":         (-5, 6),          # FRED ppt (e.g. -1.0 = -100bps); was (-300,600)
    "dff":            (0, 25),
    "sahm_rule":      (-1, 5),
    "unrate":         (0, 25),
    "vix":            (5, 150),
    "wti_crude":      (5, 300),
    "brent_crude":    (5, 300),
    "gasoline_price": (1.0, 8.0),
    "natgas_price":   (0.5, 30),
    "sp500":          (-60, 80),        # YoY % change (was raw index 100-20000)
    "gdp_growth":     (-60, 40),    # GDPNow nowcast; COVID May 2020 hit -53% before Q2 bottomed
    "mortgage_rate_30y": (2, 20),
    "kkr_stock":            (10, 500),
    "apo_stock":            (10, 500),
    "bx_stock":             (10, 500),
    "biz_loan_delinquency": (0.0, 15.0),
    "gold_price":           (-50,  150),   # YoY % change
    "silver_price":         (-70,  300),   # YoY % change; 2026 silver rally hit ~270%
    "cpi_inflation":        (-5,   30),    # YoY % change
    "drtscilm":             (-60,  90),
    "t10y3m":               (-5,   6),     # FRED ppt; was (-300,600)
    "emratio":              (50,   75),
    "wei":                  (-15,  15),    # GDP-scaled %, extreme = COVID -11%
    "jolts":                (2000, 12000),  # thousands of persons (JTSJOL)
    "usd_broad_index":           (-30, 25),   # YoY % change in trade-weighted dollar index
    "foreign_treasury_holdings": (-25, 45),   # YoY % of BOGZ1FL263061130Q; hist range -11.7..38.2 since 2000
    "used_vehicle_price":   (-40,  60),    # YoY % change (BLS CPI used cars)
    "temp_help":            (-50,  60),    # YoY % (TEMPHELPS); hist -34..44 incl COVID
    "hotel_occupancy":      (-60,  50),    # YoY % (CES7072100001 accommodation jobs); hist -48.9 (Apr 2020) .. +34.7 (May 2021)
    "auto_loan_rate":       (1,    15),    # % APR (Bankrate BRMALR0102, 60-mo new car); hist 3.85..9.81
    "bank_credit":          (-10,  15),    # YoY % (TOTBKCR); hist -2.4..7.1 since 1990
    "awhman_hours":         (-12,  12),    # YoY % (AWHMAN); hist -7.7..8.3
    "heavy_truck_sales":    (-70, 100),    # YoY % (HTRUCKSSA); hist -47.5..62
    "auto_delinquency":     (0.5,  8.0),   # % delinquency rate (DRCLACBS, all consumer)
    "auto_90d_delinquency": (0.5, 15.0),   # % of auto balance 90+ DPD (NY Fed CCP); hist 1.99..5.60
    "vehicle_days_supply":  (50, 2000),    # $ millions auto inventories (AUINSA); now high=bad
    "housing_affordability": (300, 2500),  # thousands of units (HOUST housing starts)
    # FRED raw person count series (NOT in thousands):
    "icsa":                 (50000,  7000000),  # raw persons; COVID peak ~6.9M
    "ccsa":                 (500000, 30000000), # raw persons; COVID peak ~25M
    # KPIs now using pct_change transforms (values are % after transform):
    "avg_earnings":         (-5,   20),    # YoY % change in hourly earnings
    "retail_sales":         (-25,  55),    # YoY % change; 2021 stimulus spike hit +46%
    "m2_growth":            (-10,  30),    # YoY % change in M2 money supply
    "existing_home_sales":  (-55,  65),    # HSN1F YoY % change; 2020 rebound hit +51%, 2007-08 crash hit -46%
    "case_shiller":         (-25,  25),    # YoY % change in Case-Shiller HPI
    "median_home_price":    (-25,  30),    # YoY % change; 2021 housing boom hit +22%
    "ism_services":         (-20,   8),    # CFNAI native scale; 2008 low ~-4.3, COVID -18, June 2020 rebound +6.3
    "energy_cpi":           (-30, 100),    # YoY % change in energy CPI component
    "new_vehicle_sales":    (-60,  80),    # YoY % change in new light vehicle unit sales
    # --- New daily/weekly KPIs ---
    "t5yie":                (-3,   5),     # 5Y breakeven inflation; went negative briefly in 2020
    "t10yie":               (-1,   5),     # 10Y breakeven inflation
    "dfii10":               (-3,   5),     # 10Y real yield; was deeply negative 2020-2022
    "dgs2":                 (0,   20),     # raw 2Y Treasury yield
    "dgs10":                (0,   20),     # raw 10Y Treasury yield
    "stlfsi":               (-5,  10),     # STLFSI4; COVID peak ~5.7, GFC peak ~9.1
    "anfci":                (-2,   5),     # Adjusted NFCI; typically -1 to +1, crisis peaks ~3
    "bbb_spread":           (0.5, 15),     # BBB OAS %; tight ~1.2%, GFC peak ~8%
    "walcl":                (-25, 160),    # YoY % change; GFC expansion hit ~155%, COVID ~110%
    "iursa":                (0,   20),     # insured UE rate %; COVID peak ~15.9%
    "lumber_futures":       (-80, 400),    # YoY % change; 2021 lumber mania hit +300%+
    "copper_futures_daily": (1.0, 10.0),   # USD/lb; historical range ~$1.50-$5.00
    "rail_carloads":        (500000, 1600000),  # raw carloads (not thousands); range ~760K-1.45M
    "cp_ff_spread":         (-1,  5),      # spread in %, normally 0-0.3, crisis up to 2.5
    "xhb":                  (-70, 200),    # YoY% ETF price change
    "auto_etf":             (-70, 200),    # YoY% ETF price change (CARZ)
    # --- New red-flag KPIs ---
    "umcsent":              (30, 120),     # UMich sentiment index; historical low ~50, high ~112
    "shiller_cape":         (5, 60),       # CAPE ratio; historical range ~5 (1920s) to ~45 (2021)
    "sp500_ma200":          (-50, 50),     # % distance from 200-day MA; extreme = COVID -30%
    "buffett_indicator":    (30, 250),     # % of GDP; historical range ~40% (1982) to ~200% (2021)
    # --- AI Bubble Monitor KPIs (monitor-only, not scored) ---
    "tech_capex_gdp":       (2.0, 8.0),    # % of GDP; 1995-2026 range 3.4-5.05
    "market_breadth_gap":   (-40, 40),     # pp, 12M RSP/SPY; 2004-2026 range ~-12 to +16
    "semis_ma200":          (-80, 150),    # % from 200d MA; 2002 trough ~-53, Jun 2026 peak ~+76
    "private_credit_ma200": (-70, 50),     # % from 200d MA; COVID trough ~-52
}

def _is_plausible(kpi_id: str, value: float) -> bool:
    if kpi_id not in _PLAUSIBLE_RANGES:
        return True
    lo, hi = _PLAUSIBLE_RANGES[kpi_id]
    return lo <= value <= hi


# ---------------------------------------------------------------------------
# Write a series to the database
# ---------------------------------------------------------------------------

def _save_series(kpi_id: str, series: pd.Series) -> tuple:
    """Upsert a pandas Series of (date -> value) into kpi_data.

    Returns (rows_inserted, rows_revised). "Revised" means a row that was
    already in the DB got a materially different value this run — i.e. an
    upstream government revision was just picked up. Logged explicitly so
    revisions are visible rather than silently overwritten.
    """
    session = get_session()
    saved = 0
    revised = 0
    try:
        for idx, val in series.items():
            if pd.isna(val):
                continue
            d = idx.date() if hasattr(idx, "date") else idx
            fval = float(val)
            if not _is_plausible(kpi_id, fval):
                logger.warning("KPI %s value %.4f on %s is outside plausible range — skipping",
                               kpi_id, fval, d)
                continue
            existing = (
                session.query(KpiData)
                .filter_by(kpi_id=kpi_id, date=d)
                .first()
            )
            if existing is None:
                session.add(KpiData(kpi_id=kpi_id, date=d, value=fval,
                                    fetched_at=datetime.utcnow()))
                saved += 1
            else:
                if abs(existing.value - fval) > 1e-6:
                    logger.info("KPI %s revised on %s: %.4f -> %.4f (upstream revision)",
                                kpi_id, d, existing.value, fval)
                    revised += 1
                existing.value = fval
                existing.fetched_at = datetime.utcnow()
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("DB error saving %s: %s", kpi_id, exc)
    finally:
        session.close()
    return saved, revised


# ---------------------------------------------------------------------------
# Latest date already in DB for incremental refresh
# ---------------------------------------------------------------------------

def _latest_date_in_db(kpi_id: str) -> Optional[date]:
    session = get_session()
    try:
        row = (
            session.query(KpiData.date)
            .filter_by(kpi_id=kpi_id)
            .order_by(KpiData.date.desc())
            .first()
        )
        return row[0] if row else None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Fetch one KPI
# ---------------------------------------------------------------------------

def fetch_kpi(kpi: dict, incremental: bool = True) -> None:
    """Fetch and store data for a single KPI definition dict."""
    kpi_id = kpi["id"]
    source = kpi.get("source", "")

    if source == "manual_csv":
        logger.debug("KPI %s is manual_csv — skipping automated fetch", kpi_id)
        return

    end_date = date.today()
    pct_periods = kpi.get("compute_pct_change_periods")
    floor_date = date(end_date.year - 20, 1, 1)

    if incremental:
        latest = _latest_date_in_db(kpi_id)
        if latest and (end_date - latest).days < 1:
            logger.debug("KPI %s is up to date (latest: %s)", kpi_id, latest)
            return

        if latest:
            # Re-request a trailing window even though these dates are already
            # stored, so government revisions to recently-published months
            # (e.g. BLS CES's two revision rounds) get upserted rather than
            # the DB keeping the first-published value forever.
            revision_start = latest - timedelta(days=REVISION_LOOKBACK_DAYS)

            if pct_periods:
                # pct_change(N) also requires N prior data points before the
                # first row it produces — extend back at least that far too.
                freq = kpi.get("frequency", "monthly")
                days_per_period = {"daily": 2, "quarterly": 95, "weekly": 9, "monthly": 32}.get(freq, 32)
                transform_start = latest - timedelta(days=int(pct_periods) * days_per_period)
                start_date = max(min(revision_start, transform_start), floor_date)
            else:
                start_date = max(revision_start, floor_date)
        else:
            start_date = floor_date
    else:
        start_date = floor_date

    logger.info("Fetching KPI: %s (%s) from %s to %s", kpi_id, source, start_date, end_date)

    try:
        if source == "fred":
            series = fetch_fred_series(kpi["series_id"], start_date, end_date)
        elif source == "bls":
            series = fetch_bls_series(kpi["series_id"], start_date.year, end_date.year)
        elif source == "eia":
            series = fetch_eia_series(kpi["series_id"])
            series = series[series.index >= start_date]
        elif source == "yfinance":
            freq = kpi.get("frequency", "daily")
            series = fetch_yfinance(kpi["series_id"], start_date, end_date, frequency=freq)
        elif source == "tsa":
            series = fetch_tsa_throughput()
            series = series[series.index >= start_date]
        elif source == "scrape_cape":
            series = fetch_shiller_cape()
            series = series[series.index >= start_date]
        elif source == "scrape_gdpnow":
            series = fetch_atlanta_gdpnow()
            series = series[series.index >= start_date]
        elif source == "scrape_nyfed_auto":
            series = fetch_nyfed_auto_delinquency(
                since=_latest_date_in_db(kpi_id) if incremental else None
            )
            if not series.empty:
                series = series[series.index >= start_date]
        elif source == "derived_ma":
            ma_window = kpi.get("ma_window", 200)
            series = fetch_derived_ma(kpi["series_id"], start_date, end_date, ma_window)
        elif source == "derived_ratio":
            series = fetch_derived_ratio(kpi, start_date, end_date)
        elif source == "derived_relative":
            series = fetch_derived_relative(kpi, start_date, end_date)
        else:
            logger.warning("Unknown source '%s' for KPI %s", source, kpi_id)
            return

        if kpi.get("compute_diff"):
            series = series.diff().dropna()

        if pct_periods:
            series = series.pct_change(periods=int(pct_periods)).dropna() * 100
            # Drop ±infinity values that arise when the base period value is zero
            series = series.replace([float('inf'), float('-inf')], float('nan')).dropna()

        # No cutoff filtering here: rows already in the DB are intentionally
        # re-passed to _save_series, which upserts — that's what lets a
        # revised value overwrite the first-published one.
        saved, revised = _save_series(kpi_id, series)
        logger.info("KPI %s: %d new rows saved, %d existing rows revised", kpi_id, saved, revised)

    except Exception as exc:
        logger.error("Failed to fetch KPI %s: %s", kpi_id, exc)


# ---------------------------------------------------------------------------
# Fetch all KPIs
# ---------------------------------------------------------------------------

def clear_and_refetch_changed_series() -> None:
    """
    Detect KPIs whose series_id, compute_diff, or compute_pct_change_periods changed since the last run.
    Clears stale DB rows for those KPIs and re-fetches from scratch.

    Stored in AppConfig as 'series_id_{kpi_id}', 'compute_diff_{kpi_id}', 'pct_change_periods_{kpi_id}'.
    """
    from backend.models import AppConfig, get_session
    config = load_config()
    kpis = [k for k in config.get("kpis", []) if k.get("source") not in ("manual_csv", "tsa")]

    session = get_session()
    try:
        for kpi in kpis:
            kpi_id = kpi["id"]
            source = kpi.get("source", "")

            # Synthesize series_id for derived_ratio KPIs (e.g. "WILL5000INDFC/GDP")
            if source == "derived_ratio":
                num_id = kpi.get("ratio_numerator", {}).get("series_id", "")
                den_id = kpi.get("ratio_denominator", {}).get("series_id", "")
                series_id = f"{num_id}/{den_id}"
            elif source == "derived_relative":
                series_id = f"{kpi.get('series_id', '')}/{kpi.get('benchmark_ticker', '')}"
            else:
                series_id = kpi.get("series_id") or ""

            compute_diff = str(kpi.get("compute_diff", False))
            pct_periods = str(kpi.get("compute_pct_change_periods", ""))
            ma_window = str(kpi.get("ma_window", ""))

            sid_key = f"series_id_{kpi_id}"
            diff_key = f"compute_diff_{kpi_id}"
            pct_key = f"pct_change_periods_{kpi_id}"
            ma_key = f"ma_window_{kpi_id}"
            stored_sid = session.get(AppConfig, sid_key)
            stored_diff = session.get(AppConfig, diff_key)
            stored_pct = session.get(AppConfig, pct_key)
            stored_ma = session.get(AppConfig, ma_key)
            stored_sid_val = stored_sid.value if stored_sid else None
            stored_diff_val = stored_diff.value if stored_diff else "False"
            stored_pct_val = stored_pct.value if stored_pct else ""
            stored_ma_val = stored_ma.value if stored_ma else ""

            needs_refetch = (
                (stored_sid_val != series_id)
                or (stored_diff_val != compute_diff)
                or (stored_pct_val != pct_periods)
                or (stored_ma_val != ma_window)
            )
            if needs_refetch:
                logger.info(
                    "KPI %s config changed (series_id: %s->%s, compute_diff: %s->%s, pct_periods: %s->%s) -- clearing and re-fetching",
                    kpi_id, stored_sid_val, series_id, stored_diff_val, compute_diff, stored_pct_val, pct_periods,
                )
                session.query(KpiData).filter_by(kpi_id=kpi_id).delete()
                session.commit()
                fetch_kpi(kpi, incremental=False)

                # Update stored values
                if stored_sid:
                    stored_sid.value = series_id
                else:
                    session.add(AppConfig(key=sid_key, value=series_id))
                if stored_diff:
                    stored_diff.value = compute_diff
                else:
                    session.add(AppConfig(key=diff_key, value=compute_diff))
                if stored_pct:
                    stored_pct.value = pct_periods
                else:
                    session.add(AppConfig(key=pct_key, value=pct_periods))
                if stored_ma:
                    stored_ma.value = ma_window
                else:
                    session.add(AppConfig(key=ma_key, value=ma_window))
                session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Error in clear_and_refetch_changed_series: %s", exc)
    finally:
        session.close()


# KPI ids that have been removed from kpi_config.yaml but may still have
# rows in the DB from a previous config. Listed here so startup purges them.
_RETIRED_KPI_IDS = (
    "consumer_confidence",  # retired 2026-04: FRED CSCICP03USM665S discontinued
    "gdp_personal_savings",  # orphaned from an earlier refactor
    "fedfunds",  # orphaned rows from an earlier config (BUGS.md AR1-001)
    "vehicle_repos",  # retired 2026-07: DROCLACBS replaced by auto_90d_delinquency
)


def purge_retired_kpis() -> None:
    """Delete DB rows for any KPI id that is no longer in the config."""
    session = get_session()
    try:
        for kpi_id in _RETIRED_KPI_IDS:
            n = session.query(KpiData).filter_by(kpi_id=kpi_id).delete()
            if n:
                logger.info("Purged %d rows for retired KPI %s", n, kpi_id)
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Error purging retired KPIs: %s", exc)
    finally:
        session.close()


# Max allowed age (days since DB latest) per publication frequency. Tuned to
# only catch truly stuck series (like GDPNOW after FRED stopped ingesting it
# for 111+ days), not normal publication lag. For monthly series, one missed
# release cycle is ~60 days; two missed cycles is ~90. Quarterly series like
# TIC foreign holdings publish with 2+ quarter lag naturally.
_STALENESS_WINDOW_DAYS = {
    "daily": 15,
    "weekly": 60,
    "monthly": 95,
    "quarterly": 250,
}


def check_staleness(kpis: list) -> None:
    """Log ERROR for any KPI whose latest DB row is older than its window."""
    today = date.today()
    for kpi in kpis:
        if kpi.get("source") == "manual_csv":
            continue
        latest = _latest_date_in_db(kpi["id"])
        if latest is None:
            continue
        # Per-KPI override for series with long publication lag (e.g. Case-Shiller
        # publishes ~2 months behind; BTS rail data ~3 months behind).
        window = kpi.get("staleness_window_days") or _STALENESS_WINDOW_DAYS.get(
            kpi.get("frequency", "monthly"), 50
        )
        age = (today - latest).days
        if age > window:
            logger.error(
                "Stale KPI %s (%s): latest=%s, age=%dd > window=%dd — "
                "source may have been discontinued",
                kpi["id"], kpi.get("source", "?"), latest, age, window,
            )


def fetch_all_kpis(incremental: bool = True) -> None:
    """Loop through kpi_config.yaml and fetch every KPI."""
    config = load_config()
    kpis = config.get("kpis", [])
    logger.info("Starting fetch for %d KPIs (incremental=%s)", len(kpis), incremental)

    # Clean up any retired KPI rows before fetching
    purge_retired_kpis()

    # Safety net: if a KPI has no rows at all in the DB, force a full refetch
    # regardless of AppConfig state. Catches KPIs whose initial fetch failed silently.
    if incremental:
        for kpi in kpis:
            if kpi.get("source") == "manual_csv":
                continue
            if _latest_date_in_db(kpi["id"]) is None:
                logger.warning("KPI %s has no data in DB — forcing full refetch", kpi["id"])
                fetch_kpi(kpi, incremental=False)

    for kpi in kpis:
        fetch_kpi(kpi, incremental=incremental)
    fetch_nber_shading()
    fetch_reference_series()
    check_staleness(kpis)
    logger.info("Fetch complete")


# ---------------------------------------------------------------------------
# Bootstrap: full 5-year history on first launch
# ---------------------------------------------------------------------------

def bootstrap_history() -> None:
    """Download 5 years of historical data for all KPIs. Shows progress."""
    config = load_config()
    kpis = [k for k in config.get("kpis", []) if k.get("source") != "manual_csv"]
    total = len(kpis)
    print(f"\nBootstrapping 20-year history for {total} KPIs (this may take 20–40 minutes)…\n")
    for i, kpi in enumerate(kpis, 1):
        pct = int(i / total * 40)
        bar = "█" * pct + "░" * (40 - pct)
        print(f"\r[{bar}] {i}/{total}  {kpi['id']:<30}", end="", flush=True)
        fetch_kpi(kpi, incremental=False)
    fetch_nber_shading()
    fetch_reference_series()
    print("\n\nBootstrap complete.\n")
