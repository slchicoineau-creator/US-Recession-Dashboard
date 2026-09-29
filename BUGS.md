# Recession Dashboard — Bug Triage

Findings from automated tests and exploratory bug-hunt loops.
Severity: BLOCK (broken feature) > HIGH (silent wrong result) > MED > LOW (cosmetic).

## Status (2026-06-12 bug-sweep session)

Tests: 74 pytest + 72 Playwright = **146 passing**.

New findings this session (BS2-xxx) and closures of previously deferred items:

| ID | Severity | Status |
|---|---|---|
| BS2-001 | HIGH | FIXED — `sp500` computed 12-trading-day change, not YoY: `compute_pct_change_periods` 12 → 252 (`kpi_config.yaml`); values were ~1/20th of true YoY and DANGER never fired (Lehman now correctly shows -19.6% YoY DANGER) |
| BS2-002 | MED | FIXED — incremental-fetch lookback map missing `daily` key (`fetcher.py`): 252-period daily KPIs re-downloaded ~22 years per refresh; added `"daily": 2` |
| BS2-003 | MED | FIXED — `/api/refresh` check-then-set race: replaced `_refresh_running` flag with non-blocking `threading.Lock` |
| BS2-004 | MED | FIXED — live AI commentary cache never invalidated after data refresh: refresh worker now deletes today's `AiCommentary` rows (historical Time-Machine cache kept) |
| BS2-005 | MED | FIXED — N+1 queries in `/api/kpis` (~156/request in Time Machine): batched via `row_number()` window query (`_latest_rows_per_kpi`); 78 KPIs in 0.17s |
| BS2-006 | MED | FIXED — missing stale-token guards in CategoryPage / KpiDetailPage / KpiDetailChart (HomePage pattern replicated) + error states added |
| BS2-007 | MED | FIXED — SettingsPage swallowed save errors (try/finally, no catch) and load errors; both now surfaced in UI |
| BS2-008 | MED | FIXED — HomePage had no error state on core fetch failure; added catch + retry view |
| BS2-009 | MED | FIXED — tautological e2e assertion `/\/(\?|$)/` in `category.spec.ts` masked a REAL regression: top-nav Overview/Settings/brand links dropped `?as_of=`; nav now propagates the param (new `TopNav` component in `App.jsx`) |
| BS2-010 | LOW | FIXED — f-string SQL in `cleanup_db.py` → parameterized |
| BS2-011 | LOW | FIXED — `uploadCsv` didn't check `res.ok`; now throws with backend `error` field |
| BS2-012 | LOW | FIXED — `derived_ratio` logs WARNING when numerator >45 days newer than denominator (stale-GDP Buffett values) |
| PYT-001 | HIGH | FIXED — 7 KPI thresholds recalibrated in `kpi_config.yaml` |
| PYT-002 | HIGH | FIXED — `gold_price` thresholds raised to 25/50 |
| PYT-003 | MED | DEFERRED — likely accurate (CAPE in extreme territory) |
| PYT-004 | LOW | DEFERRED — upstream FRED publication lag |
| PYT-005 | MED | DEFERRED — known intentional dup per CLAUDE.md |
| PW-001 | BLOCK | FIXED — Flask `static_folder=None` |
| AR1-001 | LOW | FIXED (2026-06-12) — `fedfunds` added to `_RETIRED_KPI_IDS`; 243 orphan rows purged |
| AR1-002 | MED | FIXED (2026-06-12) — per-KPI `stale` flag in /api/kpis (live mode, `_STALENESS_WINDOW_DAYS` windows) + "⚠ stale" badge in category table |
| AR2-001 | HIGH | FIXED — capped `end_date` in score history; cleaned 873 rows |
| AR2-002 | MED | PARTIAL — future as_of still returns simulated, but no longer pollutes DB |
| AR2-003 | HIGH | FIXED — guard on forecast target ≤ today |
| AR2-004 | LOW | DEFERRED — missing live-mode forecast actual_score |
| AR3-001 | MED | FIXED (2026-06-12) — chart shows dots when history < 3 points |
| AR3-002 | MED | FIXED (2026-06-12) — KpiDetailChart distinguishes fetch failure ("Failed to load chart") from empty data |
| AR3-003 | LOW | DEFERRED — tooltip edge dead-zone |
| AR3-004 | LOW | DEFERRED — Promise.all coupling |
| AR4-001 | BLOCK | FIXED — type coercers in `POST /api/config` |
| AR4-002 | HIGH | FIXED — CSV future-date rejection |
| AR4-003 | HIGH | FIXED — CSV column validation |
| AR4-004 | MED | FIXED — 404 for unknown KPI id |
| AR4-005 | MED | FIXED — 404 for unknown category id |
| AR4-006 | LOW | DEFERRED — cosmetic stack-trace leak (now wraps to "see server log") |
| AR5-001 | BLOCK | FIXED — same root cause as AR2-001 |
| AR5-002 | MED | RESOLVED — downstream of AR5-001 |
| AR5-003 | LOW | DEFERRED — /api/* typos fall through to SPA shell |
| AR5-004 | HIGH | RESOLVED — re-confirmation; the underlying items fixed |
| AR5-005 | MED | RESOLVED (2026-06-12) — `buffett_indicator` has 81 rows (2006–2026 Q1, values 195–232% GDP); the empty result was a transient fetch failure, implementation verified correct; lag warning added (BS2-012) |

---

## Initial pytest run findings (2026-04-25)

### [PYT-001] Threshold NEVER_TRIGGERS for 7 KPIs
- **File:** [kpi_config.yaml](kpi_config.yaml)
- **Severity:** HIGH (silently wrong scoring contributions)
- **Detail:** Five-year history has values that never cross even the WARNING threshold. These KPIs always contribute 0.0 to the recession score, so they're effectively dead weight in the composite. Need threshold recalibration based on observed value range.
  - `housing_starts`: warn=1200, danger=900, but min(5y) = 1265K starts. Suggested: warn=1300, danger=1000.
  - `building_permits`: warn=1200, danger=900, min(5y) = 1330K. Suggested: warn=1400, danger=1100.
  - `housing_affordability` (also HOUST): warn=1000, danger=700, min(5y) = 1265K. Same recalibration as above.
  - `mortgage_delinquency`: warn=3.0, danger=5.0, max(5y) = 2.3%. Suggested: warn=2.5, danger=4.0.
  - `nfci`: warn=0.3, danger=0.7, max(5y) = -0.10. Suggested: warn=0.0, danger=0.5.
  - `biz_loan_delinquency`: warn=1.5, danger=2.5, max(5y) = 1.34%. Suggested: warn=1.3, danger=2.0.
  - `anfci`: warn=0.3, danger=0.7, max(5y) = -0.023. Suggested: warn=0.0, danger=0.5.
- **Reasonable as-is (extreme/crisis thresholds):** `t5yie`, `t10yie`, `avg_earnings`, `existing_home_sales` (only 1 row), `wei`.
- **Repro:** `python -m pytest tests/test_thresholds_audit.py::test_threshold_audit_all_kpis -v -s`

### [PYT-002] gold_price always at DANGER over past year
- **File:** [kpi_config.yaml](kpi_config.yaml)
- **Severity:** HIGH (silent over-contribution)
- **Detail:** YoY gold thresholds are warn=15%/danger=30%. Gold YoY has been >30% for 251 trading days straight (min over last year = 32.4%). The KPI permanently emits sub_score=1.0, biasing the financial_stress category upward forever. Either raise threshold (40%/50%?) or adopt a rolling-z transform.
- **Repro:** `python -m pytest tests/test_thresholds_audit.py::test_no_kpi_always_at_danger_with_recent_data -v -s`

### [PYT-003] shiller_cape always at DANGER (likely accurate, but worth confirming)
- **File:** [kpi_config.yaml](kpi_config.yaml)
- **Severity:** MED (could be intentional)
- **Detail:** CAPE thresholds warn=25/danger=35. Last 19 monthly readings min=35.08. Either CAPE is genuinely in extreme territory (consistent with current market valuations) or threshold needs adjustment to discriminate "high but normal" vs "tail risk". Recommend comparing to long-run 90th/95th percentile.

### [PYT-004] 7 stale KPIs in live DB — verified upstream
- **File:** [data/recession_kpi.db](data/recession_kpi.db), [backend/fetcher.py:885](backend/fetcher.py#L885)
- **Severity:** LOW (real-world FRED publication lag, not a code bug)
- **Detail:** 5 monthly housing series (housing_starts, building_permits, new_home_sales, case_shiller, housing_affordability) all stuck at 2026-01-01 (114 days old) AND `rail_carloads` stuck at 2026-01-01. Verified with direct FRED query: those series in FRED itself have latest=2026-01-01. So the watchdog is correctly reporting the underlying data delay, not a fetcher failure. `foreign_treasury_holdings` is quarterly (FDHBFIN) with a 2-quarter natural publication lag.
- **Action:** Bump monthly staleness window from 95d→125d and weekly from 60d→90d to reduce false-positive ERROR logs for known-laggy series. Or accept the noise; the watchdog is doing its job.
- **Repro:** `python -m pytest tests/test_staleness.py::test_live_db_no_stale_kpis -v -s`

### [PYT-005] housing_starts and housing_affordability share FRED:HOUST
- **File:** [kpi_config.yaml](kpi_config.yaml)
- **Severity:** MED (documented in CLAUDE.md as intentional, but suspect)
- **Detail:** Two KPIs back to the same series_id. They will move identically and both contribute to housing category. CLAUDE.md notes housing_affordability was "repurposed" to track HOUST after FIXHAI was discontinued. Decision: either drop `housing_affordability` entirely or back it with a different series (e.g. NAHB sentiment or affordability index from a non-FRED source).

---

## Playwright run findings

### [PW-001] [FIXED] Flask returns 404 for SPA deep-links
- **File:** [app.py:46](app.py#L46), [app.py:1014-1020](app.py#L1014)
- **Severity:** BLOCK (deep links to /category/* and /kpi/* completely broken)
- **Detail:** `Flask(static_url_path="")` registers a static rule `/<path:filename>` that intercepts SPA routes before the catch-all handler can serve `index.html`. Result: visiting `/category/yield_curve` directly returns Flask's `<h1>Not Found</h1>` instead of the React SPA. Only `/` worked because of the explicit root-route registration. Discovered when 8 Playwright category tests + 6 KPI detail tests all failed with "Not Found" page snapshots.
- **Fix:** Disabled Flask's auto-static handler with `static_folder=None`; the existing `serve_spa` catch-all now serves the SPA shell for unknown paths and falls through to `send_from_directory(dist, path)` only for real files. Verified by curl: `GET /category/yield_curve` → 200 + index.html.
- **Repro:** `curl -i http://localhost:5000/category/yield_curve` (before fix → 404)

## Add new findings below as work proceeds.

---

## Autoresearch Loop 4 — API Error Paths

Tests run 2026-04-25 against live `http://127.0.0.1:5000` Flask process. All bugs reproduced multiple times. DB pollution from tests was cleaned up at end of session.

### [AR4-001] POST /api/config persists arbitrary string for numeric thresholds → next GET 500s
- **File:** [app.py:721-749](app.py#L721), [backend/alerter.py:34-39](backend/alerter.py#L34)
- **Severity:** BLOCK (server-side denial-of-service via single POST; settings page becomes unloadable until DB is hand-edited)
- **Detail:** `api_config` whitelists keys but does NO type validation on values. Posting `{"warning_threshold":"high"}` returns `200 {"status":"saved"}` and stores the string `"high"` in `app_config`. The very next `GET /api/config` calls `get_warning_threshold()` → `float("high")` → uncaught `ValueError` → Flask 500 HTML response. Same pattern applies to `critical_threshold` and `alerts_enabled`. A misbehaving frontend (or any user with curl) can lock the settings page indefinitely. Reproduced 3x; restored manually after.
- **Repro:**
  ```
  curl -X POST localhost:5000/api/config -H 'Content-Type: application/json' -d '{"warning_threshold":"high"}'  # → 200 saved
  curl localhost:5000/api/config                                                                               # → 500
  ```
- **Fix idea:** Coerce numeric keys with `float(val)` inside the handler in a try/except → return 400 on failure. Alternatively guard `get_warning_threshold/critical_threshold` with `try/except ValueError` and fall back to default.

### [AR4-002] CSV upload accepts future-dated rows (year 2099) and writes them to DB
- **File:** [app.py:756-785](app.py#L756)
- **Severity:** HIGH (silent data corruption; a stray row poisons charts, score history, and forecast accuracy backtests)
- **Detail:** `api_upload_csv` calls `pd.to_datetime(row['date']).date()` and `float(row['value'])` with no sanity check on the resulting date. Uploading `date,value\n2099-01-01,42.5` returned `{"rows_saved":1,"status":"ok"}` and the value is now visible at `GET /api/kpis/hotel_occupancy/history` as the latest data point. Because `_compute_kpi_status` reads "latest value <= as_of_date", a single future row becomes the de-facto current reading until 2099. (Cleaned up after testing.)
- **Repro:** `printf "date,value\n2099-01-01,42.5\n" > x.csv && curl -X POST localhost:5000/api/upload-csv/hotel_occupancy -F "file=@x.csv"`
- **Fix idea:** Reject `d > date.today()` in the loop with a 400 ("future-dated rows not permitted"). Also reject `d < date(1950,1,1)` to catch typos.

### [AR4-003] CSV upload silently accepts files missing required columns
- **File:** [app.py:776-783](app.py#L776)
- **Severity:** HIGH (user gets `200 ok` with `rows_saved:0` and assumes import succeeded)
- **Detail:** Uploading a CSV like `foo,bar\n1,2\n3,4\n` returns `{"rows_saved":0,"status":"ok"}` instead of an error. The handler iterates DictReader and calls `row.get("date","")` / `row.get("value","nan")` — when keys are missing, `pd.to_datetime("")` throws → caught by the bare `except Exception` only when ALL rows fail; if even one row parsed (e.g. headers only), the function returns 200. Same outcome for empty file and header-only file.
- **Repro:** `printf "foo,bar\n1,2\n" | curl -X POST localhost:5000/api/upload-csv/hotel_occupancy -F "file=@-;filename=bad.csv"` → 200 with `rows_saved:0`
- **Fix idea:** Validate `reader.fieldnames` contains both `date` and `value` before iterating; return 400 if missing. Also return 400 when `rows_saved == 0` after iteration.

### [AR4-004] Path-traversal / unknown id on `/api/kpis/<id>/history` returns 200 [] instead of 404
- **File:** [app.py:538-556](app.py#L538)
- **Severity:** MED (no security risk — SQL is parameterised — but contract is wrong; clients have no way to distinguish "valid KPI with no data" from "garbage KPI id")
- **Detail:** `GET /api/kpis/nonexistent_kpi/history` → `200 []`. `GET /api/kpis/..%2F..%2Fetc%2Fpasswd/history` is rerouted by Flask URL parsing to the SPA fallback and returns `200` + `index.html` (HTML in a JSON endpoint). Neither case validates `kpi_id` against `kpi_config`. Cosmetically wrong + frontend cannot show "Unknown KPI" error.
- **Repro:** `curl -i localhost:5000/api/kpis/garbage_xyz/history` → `200 []`
- **Fix idea:** Look up `kpi_id` in `_load_config()` map at top of handler; return 404 if absent.

### [AR4-005] `/api/commentary/category/<bad_id>` POST generates AI commentary for non-existent categories
- **File:** [app.py:846-898](app.py#L846)
- **Severity:** MED (wastes Anthropic API calls + tokens on garbage input; persists nonsense rows in `ai_commentary` table)
- **Detail:** Posting to `/api/commentary/category/INVALID_CATEGORY` returned `200` with a fully generated 200-word commentary about "the data pipeline for this monitoring category has returned no valid readings" — model dutifully hallucinates analysis for a category id that doesn't exist. The handler never validates `category_id` against the known `category_info` keys defined in `api_categories`. The result is also cached to DB so subsequent calls return the bogus row indefinitely.
- **Repro:** `curl -X POST localhost:5000/api/commentary/category/INVALID_CATEGORY` → 200 + fabricated commentary
- **Fix idea:** Hoist `category_info` to module scope and validate `category_id in category_info` (and "global") at top of both GET and POST handlers; return 404 if not.

### [AR4-006] CSV upload returns 500 stack-trace bytes for binary uploads
- **File:** [app.py:773-785](app.py#L773)
- **Severity:** LOW (returned as 400 not 500, so spec says we're fine — but error message leaks Python internals)
- **Detail:** Uploading 100KB of `/dev/urandom` returns `400 {"error":"'utf-8' codec can't decode byte 0xa6 in position 3: invalid start byte"}`. Status code is correct but the body exposes the raw `UnicodeDecodeError.args` to the client. Low-priority because no PII or path leak, but worth normalising.
- **Repro:** `head -c 102400 /dev/urandom > x.bin && curl -X POST localhost:5000/api/upload-csv/hotel_occupancy -F "file=@x.bin"`
- **Fix idea:** Replace bare `except Exception as exc: return jsonify({"error": str(exc)}), 400` with explicit handlers for `UnicodeDecodeError`, `ValueError`, etc., returning friendly messages.

### Hypotheses verified WORKING AS DESIGNED (no bug)
- **H1 — Concurrent /api/refresh:** First call → `200 {"status":"started"}`, subsequent calls → `409 {"status":"already_running"}`. Lock works; no race condition seen on rapid 3x POST.
- **H4 — Unknown keys in /api/config:** `extra_keys` are silently ignored as commented at app.py:737-738. No 500. Behaviour matches comment.
- **H6 — /api/ml/train without ALERT_EMAIL_PASSWORD:** Returns `202 started` regardless of email config (training thread is independent of alerter). Correct.
- **H8 — /api/score/history with from_date > as_of:** Returns `200 []`. The while loop `d <= end_date` short-circuits because `d.replace(day=1) > end_date`. Correct.
- **H3b — Truly malformed JSON:** `not_json{{{` → Flask returns its own `400 Bad Request` HTML (not JSON). Could be polished to JSON error body but not a bug per se.

---

## Autoresearch Loop 1 — Data Integrity

Probed 7 hypotheses, 2 bugs found. (H1 NULL latest_value: clean — only the two manual_csv pending-upload KPIs. H2 sign-mismatch: clean — code uses `abs(prior_val)` so sign always matches abs change. H4 NBER overlap: clean — 2 ordered, non-overlapping ranges. H5 category counts: clean — all 8 categories' `kpi_count` match actual KPI list. H6: `category_scores` is not exposed at all by `/api/score`, so hypothesis is moot. H7 score history cadence: clean — 232 monthly entries Jan 2007 → Apr 2026, no gaps, no duplicates, all bands consistent with score thresholds.)

### [AR1-001] Orphan `fedfunds` rows persist in DB after retirement
- **File / endpoint:** [data/recession_kpi.db](data/recession_kpi.db) `kpi_data`, [backend/fetcher.py:858](backend/fetcher.py#L858) `_RETIRED_KPI_IDS`
- **Repro:** `python -c "import sqlite3,yaml;con=sqlite3.connect('data/recession_kpi.db');db=set(r[0] for r in con.execute('SELECT DISTINCT kpi_id FROM kpi_data'));cfg=set(k['id'] for k in yaml.safe_load(open('kpi_config.yaml'))['kpis']);print('orphan:',db-cfg)"` → `{'fedfunds'}` (243 rows, 2006-01-01 → 2026-03-01).
- **Expected:** Either `fedfunds` rows are purged on startup (added to `_RETIRED_KPI_IDS`), or `fedfunds` is restored to `kpi_config.yaml`. DB should not contain rows for any kpi_id absent from config.
- **Actual:** `fedfunds` was removed from config but the 243 historical rows remain forever — `purge_retired_kpis` only deletes ids hard-coded in `_RETIRED_KPI_IDS = ("consumer_confidence", "gdp_personal_savings")`. Orphan rows are dead weight; if `fedfunds` is ever re-added with a different transform, stale rows would be silently merged.
- **Severity:** LOW (no user-facing breakage; DB hygiene + future-foot-gun risk).

### [AR1-002] /api/kpis exposes no `stale` flag despite watchdog detecting 7 stale KPIs
- **File / endpoint:** [app.py:392-516](app.py#L392) `/api/kpis`, [backend/fetcher.py:893](backend/fetcher.py#L893) `check_staleness`
- **Repro:** `curl -s localhost:5000/api/kpis | python -c "import json,sys,datetime as dt;t=dt.date(2026,4,25);[print(k['id'],k['frequency'],k['latest_date'],(t-dt.date.fromisoformat(k['latest_date'])).days) for k in json.load(sys.stdin) if k.get('latest_date') and (t-dt.date.fromisoformat(k['latest_date'])).days > {'daily':15,'weekly':60,'monthly':95,'quarterly':250}.get(k['frequency'],95)]"` → 7 KPIs (housing_starts, building_permits, new_home_sales, case_shiller, housing_affordability, foreign_treasury_holdings, rail_carloads) all return `status: OK` despite being beyond the per-frequency staleness window used by `check_staleness`.
- **Expected:** Per-KPI dict in `/api/kpis` should include a boolean `stale` field (matching the same windows the watchdog uses), so the frontend can grey out or annotate the card. `/api/score` already exposes a top-level `stale` field, but per-KPI staleness is not surfaced.
- **Actual:** The watchdog logs ERROR lines to `logs/app.log` but the API only returns OK/WARNING/DANGER status, hiding the stale state from the UI. Users see "OK" cards for KPIs whose data is months out of date.
- **Severity:** MED (silent staleness in user-facing dashboard; also why PYT-004 was filed but no UI signal exists).

---

## Autoresearch Loop 2 — Time Machine Correctness

Probed 7 hypotheses; 4 confirmed bugs. Hypotheses 1, 2, 3, 5, 7 verified working: Lehman 2008-09-15 → 74.7 HIGH (correct), `/api/score/history?as_of=X` is a strict subset of live history with 0 mismatches, `/api/kpis?as_of=2008-01-01` returns dates ≤ 2008-01-01 for all 78 KPIs (no leakage), category sparklines and `/api/kpis/<id>/history` truncate cleanly to as_of, and `?as_of=today` reconstructs live (35.4) exactly. Forecast verified self-consistent: `forecast?as_of=2008-09-15` reports `actual_score=82.0` matching `score?as_of=2008-12-15=82.0`.

### [AR2-001] /api/score/history?as_of=<future> generates and persists 873 fake-future cache rows
- **File / endpoint:** [app.py:166-251](app.py#L166) `/api/score/history`
- **Severity:** HIGH (DB pollution + misleading response payload)
- **Repro:** `curl -s "localhost:5000/api/score/history?as_of=2099-01-01" | python -c "import json,sys; d=json.load(sys.stdin); print(len(d), d[-3:])"` → 1105 entries, last entry `{"date":"2099-01-01","score":35.4}`. Then `python -c "import sqlite3; c=sqlite3.connect('data/recession_kpi.db'); print(c.execute(\"SELECT COUNT(*) FROM recession_scores WHERE date>'2026-04-25'\").fetchone())"` → **(873,)** rows now permanently in the DB.
- **Expected:** `end_date = as_of if as_of is not None else date.today()` (app.py:166) should be clamped to `min(as_of, date.today())` so future dates never enter the month loop. Or: skip caching writes for any month past today.
- **Actual:** The month loop happily generates monthly rows from Jan 2007 to Jan 2099, computes a score for each (which falls back to today's KPI values via `_value_as_of`), and the unconditional `session.add(RecessionScore(...))` block at app.py:230-235 persists every one of them. Future-dated rows survive process restarts and would resurface if anyone re-queries with `as_of >= 2026-05-01`. Verified: `/api/score/history?from_date=2030-01-01&as_of=2099-01-01` returns 829 cached entries on the second call.

### [AR2-002] Time Machine score is never clamped — future as_of returns live score with no signal
- **File / endpoint:** [app.py:99-115](app.py#L99) `/api/score`, [backend/scorer.py:109-121](backend/scorer.py#L109) `_value_as_of`
- **Severity:** MED (silently wrong UX — user thinks they're seeing 2099 but they're seeing today)
- **Repro:** `curl -s "localhost:5000/api/score?as_of=2099-01-01"` → `{"score":35.4,"band":"ELEVATED","date":"2099-01-01","simulated":true,...}`. Identical to live score (35.4); only the `date` field is the future date.
- **Expected:** Either reject `as_of > date.today()` with `400 {"error":"as_of cannot be in the future"}`, or surface a flag like `as_of_clamped_to_today: true` so the UI doesn't lie about being a 2099 simulation.
- **Actual:** `_parse_as_of` accepts any valid ISO date including far-future. `_value_as_of` then returns the most recent value `<=` as_of, which for any future date is just today's value. The score is identical to live but returned with `simulated: true` and the user-supplied future `date`, masquerading as a future projection. Same issue affects `/api/kpis?as_of=2099-01-01` (returns 2026-04-24 dates with no warning) and `/api/categories?as_of=2099-01-01`.

### [AR2-003] /api/kpis?as_of=<past> reports today's data as `actual_value_at_forecast_date` when forecast_target > today
- **File / endpoint:** [app.py:486-495](app.py#L486)
- **Severity:** HIGH (silent data fabrication used by Time Machine forecast-validation UI)
- **Repro:** `curl -s "localhost:5000/api/kpis?as_of=2026-03-01"` (forecast_target = 2026-06-01, in the future). 76 KPIs report a non-null `actual_value_at_forecast_date`, of which 26 exactly equal `latest_value` (2026-04-23/24 data labeled as "the value at 2026-06-01"). Example: `t5yie latest=2.4 (date 2026-02-27) actual_at_fc=2.61` (where 2.61 is today's value, not the value at 2026-06-01 because that date hasn't happened yet).
- **Expected:** Mirror the guard used in `/api/score/forecast` (app.py:366: `if as_of is not None and forecast_target <= date.today()`). When `forecast_target > date.today()`, set `actual_value_at_forecast_date = None`.
- **Actual:** The query `KpiData.date <= forecast_target` always finds today's row when the target is in the future, so the "actual" field becomes whatever the latest published value is. The dashboard treats this as ground-truth for the forecast horizon and any forecast-vs-actual delta computed from it is silently corrupted.

### [AR2-004] /api/score/forecast in live mode never returns an actual_score, even for back-tests
- **File / endpoint:** [app.py:363-372](app.py#L363)
- **Severity:** LOW (missing feature, not wrong data)
- **Repro:** `curl -s localhost:5000/api/score/forecast` → `actual_score: null` (no as_of). Correct in the sense that target=today+90d hasn't happened. But by setting `as_of=today-90d` the code path can compute a real backtest, e.g. `as_of=2026-01-25` → forecast target 2026-04-25 = today, so actual_score is computable. The hard `as_of is not None` gate at line 366 forces users to switch into Time Machine mode to see any accuracy comparison.
- **Expected:** Either compute and surface a "live 3-month-look-back accuracy" field by automatically running the forecast pipeline at `today-90d` and comparing to today's actual score, or document that actual_score is intentionally Time-Machine-only.
- **Actual:** `actual_score` is unconditionally None in live mode. UX paper cut: live-mode users have no visibility into whether the most recent quarter's forecast came true.

## Autoresearch Loop 3 — Frontend Rendering

Probed 8 hypotheses via curl + a throwaway Playwright spec (8 cases initially, then 12 follow-up cases for deeper inspection); spec deleted after run. Hypotheses cleared: H3 (extreme outliers — `payems` and `icsa` both have `chart_y_min/max` set so the line clips correctly; 2 ReferenceLines + 2 ReferenceAreas render fine), H5 (sparkline crash on empty cat — all 8 categories have ≥254 sparkline points; `SparkLine.jsx` already handles `data.length === 0` with a "No data" fallback), H6 (CSV upload — `Settings` exposes 4 file inputs and an 11MB buffer uploads without console errors), H7 (AI commentary without ANTHROPIC_API_KEY — `/api/commentary/global` returns `{"cached":false,"commentary":null}` and the UI shows the Generate button without spinning forever), H8a (refresh poll on 500 — `RefreshButton.jsx:33` already `clearInterval`s on fetch error; spinner releases after 1 failed poll, button re-enables).

### [AR3-001] KpiDetailChart renders blank line for KPIs with a single data point
- **File / endpoint:** [frontend/src/components/KpiDetailChart.jsx:125-134](frontend/src/components/KpiDetailChart.jsx#L125), `GET /api/kpis/existing_home_sales/history`
- **Repro:** `curl -s http://127.0.0.1:5000/api/kpis/existing_home_sales/history` → `[{"date":"2026-03-01","value":-0.995…}]` (1 row). Visit `/kpi/existing_home_sales`. Playwright DOM snapshot: `recharts-wrapper=1`, `recharts-line=1`, but `recharts-line-curve=0`, `svg path=0`, `recharts-line-dot=1`. The mocked-1-point control test (`vix` mocked to 1 point) confirms identical behavior: `lineCurves=0, lineDots=1, pathD=null`.
- **Expected:** Chart should either (a) render a visible single-point marker with a clear label/value, OR (b) treat single-point history as "insufficient data" and show the same "No historical data available yet" message used for empty arrays. The `Line` component must use `dot={true}` (or `dot={{ r: 4 }}`) when `history.length === 1` because a `<path>` requires ≥2 points and `dot={false}` then renders nothing visible.
- **Actual:** User sees the page header with "Current Value: -0.995% YoY" and the "Reporting period" tag, then a 340px-tall *empty* chart area with axes and threshold dashed lines but no line and no dot. `existing_home_sales` was migrated to `EXHOSLUSM495S` in the April 2026 alignment cleanup which has only ~13 monthly rows in production, but the KPI detail page returns just 1 row at this moment (compute_pct_change_periods=12 consumes 12 of 13 rows). Same risk applies to any newly-onboarded KPI for ~1 release cycle until it accumulates ≥2 transformed values.
- **Severity:** MED (user-facing, makes the page look broken; `shiller_cape` confirmed working with multi-point pathD `M80,166…` so the issue is specifically tied to length≤1 after transforms).

### [AR3-002] history endpoint 500 misreported as "No historical data — run a refresh"
- **File / endpoint:** [frontend/src/components/KpiDetailChart.jsx:41-54](frontend/src/components/KpiDetailChart.jsx#L41), [frontend/src/api.js:9](frontend/src/api.js#L9)
- **Repro:** Mock `**/api/kpis/t10y2y/history*` → `500`. Visit `/kpi/t10y2y`. The `Promise.all([api.kpiHistory(...), api.nberShading()])` rejects, but `KpiDetailChart` only wires `.finally(() => setLoading(false))` — there is **no `.catch`**. `history` stays `[]`, the unhandled rejection propagates to `window.onerror` (Playwright captured `pageerror: API /kpis/t10y2y/history → 500`), and the user sees the same "No historical data available yet. Run a refresh to fetch data." message used for the legitimately-empty case (verified by AR3-M control: empty `[]` body produces `noData=1`).
- **Expected:** The 500 path should produce a distinct error UI ("Could not load chart data — server error") and the `pageerror` (uncaught promise rejection) should be caught explicitly. Telling the user to "run a refresh" when the server is broken is misleading because refresh hits the same backend.
- **Actual:** Two bugs in one — (a) silent unhandled promise rejection on every transient 500, (b) misleading copy that conflates "no data" with "fetch failed". Both `api.get` (api.js:9-10) and `api.nberShading` use bare `fetch` + `res.json()` with no try/catch and no status check beyond the throw at api.js:11.
- **Severity:** MED (silent failure mode; users will assume their data is gone and click refresh, hiding genuine backend errors).

### [AR3-003] Tooltip invisible at far-left/far-right edges of every Recharts time-series chart
- **File / endpoint:** [frontend/src/components/KpiDetailChart.jsx:21-34](frontend/src/components/KpiDetailChart.jsx#L21) `CustomTooltip`, also affects `ScoreHistoryChart.jsx`
- **Repro:** Visit `/kpi/t10y2y`. Move mouse to x-fractions 0.001, 0.01, 0.5, 0.99, 0.999 of the `.recharts-wrapper` bounding box. Result: `xFrac=0.001 visible=false`, `xFrac=0.01 visible=false`, `xFrac=0.5 visible=true ("Jun 2015 ● 1.7")`, `xFrac=0.99 visible=false`, `xFrac=0.999 visible=false`. Reproducible at every chart that uses the default Recharts `<Tooltip>` placement.
- **Expected:** Tooltip should display for every x-position over a data point, especially the first and last dates which are the most useful (current value and oldest baseline).
- **Actual:** The first/last ~1% of the chart width is a "dead zone" where Recharts' tooltip-positioning computes `x = mouseX - tipWidth/2` and the tip element gets pushed off-screen (negative left CSS), so it has zero visibility. No `position={{ x, y }}` or `wrapperStyle` clipping override is set on the `<Tooltip>` element.
- **Severity:** LOW (data still visible via the chart axis labels; usability paper-cut on the most-clicked dates — most-recent and oldest values).

### [AR3-004] `KpiDetailChart` has no `pageerror` boundary; uncaught rejection on slow/down nberShading API will blank the page
- **File / endpoint:** [frontend/src/components/KpiDetailChart.jsx:44-50](frontend/src/components/KpiDetailChart.jsx#L44)
- **Repro:** The `Promise.all([api.kpiHistory(...), api.nberShading()])` pattern: if **either** call rejects, the *entire* Promise.all rejects without partial-success handling. So if NBER shading endpoint is intermittently down but kpiHistory is fine, the user gets *no chart at all* + an unhandled rejection — even though NBER shading is just decorative grey bands.
- **Expected:** Use `Promise.allSettled([…])` or fetch them independently, so a failed `nberShading` call only suppresses the grey bands and the line chart still renders.
- **Actual:** A 500 on `/api/nber-shading` (which is not currently failing but historically has) would suppress the entire chart and show "No historical data" — a worse UX than just losing the recession bands.
- **Severity:** LOW-MED (currently dormant since `/api/nber-shading` is stable, but the coupling is wrong).



---

## Autoresearch Loop 5 — Cross-Cutting

Tests run 2026-04-25 against live `http://127.0.0.1:5000`. Validates that subsystems agree with each other (score endpoints, category counts, refresh idempotency, log noise, prior-loop bug status). 5 of 8 hypotheses cleared, 3 active bugs found, plus re-confirmation that PYT-001/002/003/AR4-001 remain unfixed.

### [AR5-001] /api/score returns date `2099-01-01` from corrupt cache; 873 future-dated rows in `recession_scores`
- **File:** [app.py:117-145](app.py#L117), [app.py:228-235](app.py#L228), [data/recession_kpi.db](data/recession_kpi.db) `recession_scores`
- **Severity:** BLOCK (the headline `score` shown on the homepage is dated 73 years in the future; if the score ever varies by date, the displayed value is no longer "today's" score)
- **Detail:** `api_score()` reads `RecessionScore.order_by(date.desc()).first()` — picks `MAX(date)`. The DB contains 873 future-dated rows (range `2026-05-01 → 2099-01-01`), all `score=35.4 band=ELEVATED`, so `/api/score` returns `{"date":"2099-01-01","score":35.4}` even after a fresh refresh (which correctly inserted a `2026-04-25` row at `computed_at=2026-04-25 16:45:02`). The future rows were inserted by `/api/score/history` when invoked with future `as_of` query params — the history endpoint persists every computed month to DB as a "cache" with no upper bound on `month_date`. Today's log shows hundreds of `Simulated score as of 2099-01-01: 35.4 (ELEVATED)` lines confirming this happened.
- **Repro:**
  ```
  sqlite3 data/recession_kpi.db "SELECT COUNT(*) FROM recession_scores WHERE date > date('now')"  # 873
  curl localhost:5000/api/score   # → {"date":"2099-01-01", ...}
  ```
- **Fix idea:** (a) Cap `end_date = min(as_of, date.today())` in the history endpoint. (b) Refuse to persist computed scores when `month_date > today`. (c) `/api/score` should filter `RecessionScore.date <= date.today()` before `order_by`. (d) One-time cleanup: `DELETE FROM recession_scores WHERE date > date('now')`.
- **Cross-link:** Same root cause as AR4-002 (CSV upload accepts future dates) — codebase has no shared "no future-dated writes" guard.

### [AR5-002] /api/score and /api/score/history latest disagree by 1.0 point — score endpoint shows wrong "current" value
- **File:** [app.py:94-145](app.py#L94), [app.py:152-256](app.py#L152)
- **Severity:** MED (downstream consequence of AR5-001 — the homepage gauge shows 35.4 while the chart's last data point reads 36.4 for April 2026)
- **Detail:** `/api/score` → 35.4 (date 2099-01-01, corrupt). `/api/score/history[-1]` → 36.4 (date 2026-04-01, the genuine current monthly snapshot). Delta 1.0 > the 0.5-point tolerance. Once AR5-001 is fixed, the residual difference comes from the two endpoints reading different reference dates (today's daily row vs first-of-month snapshot). Recommend the homepage either pull the latest entry from `/api/score/history` or annotate the gauge with the actual reference date.

### [AR5-003] /api/forecast 404 silently masked as 200 + index.html (SPA fallback hides API typos)
- **File:** [app.py:320](app.py#L320), [app.py:1014-1020](app.py#L1014)
- **Severity:** LOW (real path `/api/score/forecast` works; only matters for tooling/docs/future API consumers)
- **Detail:** `GET /api/forecast` → `200 text/html` with the React shell. There is no 404 for unknown `/api/*` paths because the SPA catch-all matches first. A typo in any frontend `fetch()` call would silently get an HTML page (which then JSON-parses to fail with cryptic `Unexpected token '<'`). The real endpoint is `/api/score/forecast` and is healthy: `forecast_score=37.2` ∈ [0,100], `forecast_band="ELEVATED"`, `forecast_date="2026-07-25"` exactly 3 months ahead of today (2026-04-25).
- **Fix idea:** Add an explicit `@app.route("/api/<path:_>")` handler that returns `404 application/json` before the SPA catch-all. Optional alias `/api/forecast → /api/score/forecast`.

### [AR5-004] PYT-001 / PYT-002 / PYT-003 / AR4-001 / AR1-001 / AR1-002 ALL still active (re-confirmation)
- **Severity:** HIGH (silently-wrong scoring carries forward unfixed)
- **Detail:** Re-ran `pytest tests/test_thresholds_audit.py -v -s`. Audit emits 12 NEVER_TRIGGERS findings — exactly the 7 KPIs flagged in PYT-001 (`housing_starts`, `building_permits`, `housing_affordability`, `mortgage_delinquency`, `nfci`, `biz_loan_delinquency`, `anfci`) plus 5 noted as reasonable-as-is in BUGS.md. The "always at danger" test still flags `gold_price` (min YoY 32.4% > danger 30%) and `shiller_cape` (min 35.08 ≥ danger 35.0), matching PYT-002/PYT-003 exactly. AR4-001 also still reproduces — today's log contains `Exception on /api/config [GET] ValueError: could not convert string to float: 'high'` from a recent test run. Tests pass only because they emit advisory print() rather than assert. **No prior-loop bugs have been fixed in code.**

### [AR5-005] Today's ERROR-level log contains 41 entries — staleness watchdog noise + buffett_indicator failure
- **File:** [logs/app.log](logs/app.log), [backend/fetcher.py](backend/fetcher.py) (`derived_ratio`, `check_staleness`)
- **Severity:** MED (BUFFET fetch failing silently drops the KPI from scoring; staleness-as-ERROR causes log alarm fatigue)
- **Detail:** Top error categories on 2026-04-25:
  - `[5] Failed to fetch KPI buffett_indicator: Empty series for derived_ratio: num=0, den=0` — every refresh, this KPI fails its `derived_ratio` lookup. The CLAUDE.md says it uses NCBCEL/GDP, but at fetch time both numerator and denominator return empty series. KPI is being silently dropped from scoring.
  - `[5×7=35] Stale KPI ... source may have been discontinued` — 7 known-laggy series log ERROR (housing_starts, building_permits, new_home_sales, case_shiller, housing_affordability, foreign_treasury_holdings, rail_carloads). PYT-004 already documents these as real-world publication lag (not bugs); the watchdog should log them at WARN, not ERROR, to prevent log-alarm fatigue.
  - `[1] Exception on /api/config [GET] ValueError: could not convert string to float: 'high'` — verifies AR4-001 persists.

### Hypotheses verified WORKING AS DESIGNED (cross-cutting)
- **H2 (per-category status counts):** `categories[c].danger_count`/`warning_count` match `/api/kpis` filtered by category for all 8 categories. Status distribution: 53 OK, 17 WARNING, 6 DANGER, 2 NO_DATA. Total 78 = sum of per-category `kpi_count` (8+10+8+10+22+8+5+7).
- **H3 (refresh + recompute):** POST `/api/refresh` finished in 18.2s. Pre-refresh score 35.4, post 35.4 (delta 0.0, well within ±5).
- **H4 (DB size):** `data/recession_kpi.db` = 19.7 MB (well under 100 MB threshold). `kpi_data`: 151,908 rows; `recession_scores`: 1,106 (of which 873 are AR5-001 corrupt rows; ~233 legitimate). No leak.
- **H6 (NBER shading cache):** Two consecutive `GET /api/nber-shading` calls returned identical bytes — `[{2007-12-01,2009-07-01}, {2020-02-01,2020-04-01}]`. Stable.
- **H7 (forecast envelope):** All invariants hold (see AR5-003) — score in [0,100], band valid, date exactly 3 months ahead.

