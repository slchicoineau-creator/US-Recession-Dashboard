# Graph Report - E:\AI Back up\recession-dashboard  (2026-09-26)

## Corpus Check
- 106 files · ~98,818 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1121 nodes · 2607 edges · 53 communities (50 shown, 3 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 170 edges (avg confidence: 0.81)
- Token cost: 250,731 input · 0 output

## Community Hubs (Navigation)
- _is_plausible
- TestSeverityConfig
- Test Fixtures & KPI Status
- ML Inference & Persistence
- Recession Score Computation
- Composite Subscore Tests
- Email Alerting & Thresholds
- AI Commentary Generation
- Severity Computation & History
- Signal Backtesting
- NY Fed Auto Delinquency Fetch
- Timing Snapshot & Config Loading
- Category API & 404 Contract
- SPA Routing & NBER Shading
- fetch_kpi
- Python Dependencies & Refresh Docs
- assets/README.md
- Leading Index History & Diffusion
- Core Model Classes
- _save_ml_score
- ML Feature Matrix & Score History
- APScheduler Daily Refresh
- references/README.md
- Threshold Audit Tests
- Frontend Build Script
- Database Cleanup Script
- Frontend NPM Dependencies
- Playwright E2E Suite
- React App Routing
- Series
- Recession Gauge Component
- Category Page UI
- Home Dashboard Charts
- Manual CSV Upload
- 2026-06-12 bug-sweep session (146 tests passing)
- Frontend API Client
- bootstrap_history
- Model Performance Page
- Vite Build Config
- Score Forecast Endpoint
- KPI Config Integrity Tests
- typing (external)
- KPI Timing Tag Tests
- os (external)
- KPI Catalog & Thresholds
- Refresh & ML Admin Endpoints
- 3-Month KPI Forecasting
- Setup & Installation Guide
- FRED Series Liveness Probe
- Time Series Forecaster
- Core Data Libraries

## God Nodes (most connected - your core abstractions)
1. `FRED Data Source` - 61 edges
2. `get_session()` - 53 edges
3. `compute_recession_score()` - 45 edges
4. `Coincident Indicator Timing Tag` - 43 edges
5. `Leading Indicator Timing Tag` - 32 edges
6. `Row-Based pct_change Periods Transform` - 27 edges
7. `Financial Stress Category (weight 0.19)` - 25 edges
8. `_compute_kpi_status()` - 23 edges
9. `run_backtest()` - 23 edges
10. `KpiData` - 23 edges

## Surprising Connections (you probably didn't know these)
- `Category Weights (must sum to 1.0)` --consumed_by--> `build_feature_matrix()`  [INFERRED]
  kpi_config.yaml → backend/ml_scorer.py
- `Daily 07:00 Refresh Schedule` --consumed_by--> `_daily_job()`  [EXTRACTED]
  kpi_config.yaml → backend/scheduler.py
- `5-Year History Window` --consumed_by--> `bootstrap_history()`  [EXTRACTED]
  kpi_config.yaml → backend/fetcher.py
- `Row-Based pct_change Periods Transform` --consumed_by--> `_is_plausible()`  [INFERRED]
  kpi_config.yaml → backend/fetcher.py
- `BS2-003: /api/refresh check-then-set race` --references--> `api_refresh_status()`  [INFERRED]
  BUGS.md → app.py

## Import Cycles
- None detected.

## Communities (53 total, 3 thin omitted)

### Community 71 - "_is_plausible"
Cohesion: 0.07
Nodes (24): DataFrame, Series, _is_plausible(), _forecast_date(), date, forecast_kpi(), forecast_all_kpis(), compute_forecast_accuracy() (+16 more)

### Community 54 - "TestSeverityConfig"
Cohesion: 0.07
Nodes (52): _load_config(), _utc_iso(), _parse_as_of(), date, api_score(), api_score_history(), api_score_drivers(), api_ml_score_history() (+44 more)

### Community 3 - "Test Fixtures & KPI Status"
Cohesion: 0.13
Nodes (10): _compute_kpi_status(), Return OK / WARNING / DANGER / NO_DATA for a single KPI value.      Single sou, TestStandardKpi, TestInvertedKpi, TestEdgeCases, TestBugRegressionWarningTrigger, Test _compute_kpi_status from app.py.  Regression test for the 'Status Display B, invert=False (higher value = worse: unemployment, VIX, spreads). (+2 more)

### Community 16 - "ML Inference & Persistence"
Cohesion: 0.05
Nodes (48): api_ml_train(), Trigger ML model training in a background thread. Returns 202 Accepted., save_model(), get_or_train_model(), Pickle the fitted per-horizon LogitResults and metadata with a version guard., Load the cached models or train all horizons from scratch. Thread-safe.     Ret, project_root(), Path (+40 more)

### Community 2 - "Recession Score Computation"
Cohesion: 0.13
Nodes (20): api_ml_status(), Return per-horizon ML model metadata: training stats, coefficients., load_model(), _get_models(), compute_ml_score(), compute_ml_scores_all(), get_ml_metadata(), compute_ml_score_history() (+12 more)

### Community 36 - "Composite Subscore Tests"
Cohesion: 0.40
Nodes (6): api_refresh(), api_refresh_status(), BS2-003: /api/refresh check-then-set race, H1 cleared: concurrent /api/refresh returns 409, Daily 7:00 AM automatic refresh, apscheduler>=3.10

### Community 13 - "Email Alerting & Thresholds"
Cohesion: 0.07
Nodes (41): api_config(), _get_config(), get_warning_threshold(), get_critical_threshold(), alerts_enabled(), _last_alert_time(), datetime, _in_cooldown() (+33 more)

### Community 14 - "AI Commentary Generation"
Cohesion: 0.18
Nodes (19): _save_commentary(), generate_category_commentary(), generate_global_commentary(), _build_kpi_list(), Build a lightweight KPI list with value/status/sub_score for commentary prompts., _get_client(), is_available(), _get_model() (+11 more)

### Community 31 - "Severity Computation & History"
Cohesion: 0.39
Nodes (8): serve_spa(), PW-001: Flask returned 404 for SPA deep links, AR5-003: /api/* typos masked as 200 + index.html by SPA fallback, Playwright run findings, One-time frontend build (npm install + npm run build), SPA shell document (index.html), #root mount element, Module entry script tag (/src/main.jsx)

### Community 4 - "Signal Backtesting"
Cohesion: 0.06
Nodes (36): _iter_months(), date, _monthly_composite(), _load_nber(), _recession_onsets(), _months_between(), _lead_times(), _false_alarm_episodes() (+28 more)

### Community 5 - "NY Fed Auto Delinquency Fetch"
Cohesion: 0.14
Nodes (25): _ref_config(), _pub_lag(), load_reference(), spread_series(), _nber_long(), _feature_month(), date, _training_frame() (+17 more)

### Community 19 - "Timing Snapshot & Config Loading"
Cohesion: 0.17
Nodes (9): discount_to_bey(), T-bill discount-basis yield (%) -> bond-equivalent yield (%), as the NY Fed does, _nber_label_lag_months(), label_known(), NBER dating lag from kpi_config.yaml (reference_series usrecm_long)., Whether the training label for `month` at `horizon_months` was public at `at`., TestLabelKnown, test_discount_to_bey() (+1 more)

### Community 21 - "Category API & 404 Contract"
Cohesion: 0.21
Nodes (9): yield_curve_now(), chauvet_piger_at(), current_benchmarks(), Yield-curve probit reading for `as_of` (default today), using only the     labe, Latest Chauvet-Piger value public at `as_of` (publication lag applied).     Liv, Payload for GET /api/benchmarks., _add_months(), First-of-month date n months after d. (+1 more)

### Community 22 - "SPA Routing & NBER Shading"
Cohesion: 0.07
Nodes (55): load_config(), _retry(), fetch_fred_series(), date, Series, fetch_bls_series(), fetch_eia_series(), fetch_yfinance() (+47 more)

### Community 56 - "fetch_kpi"
Cohesion: 0.14
Nodes (11): _download_gdpnow_xlsx(), Return the GDPNow workbook bytes, rediscovering the URL if it moved.      Trie, _resp(), _router(), TestGdpnowDownload, kpis(), TestGdpnowConfig, TestManualCsvMigrations (+3 more)

### Community 33 - "Python Dependencies & Refresh Docs"
Cohesion: 0.09
Nodes (13): _fetch_nyfed_hhdc_workbook(), Download the newest published Household Debt & Credit workbook.      The file, kpi(), TestConfig, _fake_sheet(), DataFrame, TestParser, TestWorkbookDiscovery (+5 more)

### Community 66 - "assets/README.md"
Cohesion: 0.39
Nodes (8): check_staleness(), Log ERROR for any KPI whose latest DB row is older than its window., test_no_data_no_alarm(), KPI with zero rows in DB does not fire (cannot compute age)., PYT-004: 7 stale KPIs in live DB, verified upstream, AR1-002: /api/kpis exposes no per-KPI stale flag, AR5-005: 41 ERROR log entries — watchdog noise plus buffett_indicator failure, Staleness watchdog ERROR-vs-WARN log level

### Community 18 - "Leading Index History & Diffusion"
Cohesion: 0.10
Nodes (21): _kpis_by_timing(), _load_series_map(), _value_on_or_before(), date, _composite_from_subscores(), _diffusion(), compute_timing_snapshot(), compute_timing_history() (+13 more)

### Community 47 - "Core Model Classes"
Cohesion: 0.17
Nodes (15): _iter_months(), date, forward_label(), build_feature_matrix(), DataFrame, walk_forward_ml(), _build_metadata(), Yield first-of-month dates from start to end (inclusive). (+7 more)

### Community 69 - "_save_ml_score"
Cohesion: 0.29
Nodes (7): train_logit_model(), Train a statsmodels Logit model on the feature matrix for one label column., _synthetic_matrix(), DataFrame, TestTrainLogit, Unit tests for the multi-horizon ML scorer (forward labels + training)., Feature matrix where financial_stress cleanly drives the label.

### Community 29 - "ML Feature Matrix & Score History"
Cohesion: 0.09
Nodes (44): compute_ml_scores_batch(), compute_ml_score for many rows in one predict() call (same rounding).      Use, sample_dates(), date, previous_business_day(), _SeriesIndex, _scored_kpi_ids(), _published_scores() (+36 more)

### Community 27 - "APScheduler Daily Refresh"
Cohesion: 0.05
Nodes (38): KpiData, Time-series values for every KPI., normalize_kpi(), _value_as_of(), date, compute_recession_score(), Return a 0.0–1.0 recession risk sub-score for the given KPI value.      0.0 =, Return the most recent value for kpi_id on or before as_of_date. (+30 more)

### Community 67 - "references/README.md"
Cohesion: 0.10
Nodes (21): RecessionScore, KpiSnapshot, Daily computed recession risk scores., Per-KPI values the live score actually used on a given day.      Written along, _daily_job(), start_scheduler(), BackgroundScheduler, next_run_time() (+13 more)

### Community 26 - "Threshold Audit Tests"
Cohesion: 0.10
Nodes (19): component_subscore(), get_severity_band(), _persistence_months(), date, compute_severity(), Linear 0-1 interpolation between healthy (0) and extreme (1).      Direction is, Distinct calendar months in the trailing 12 with composite >= CRITICAL., Compute the Depression Severity score for one date. (+11 more)

### Community 11 - "Frontend NPM Dependencies"
Cohesion: 0.08
Nodes (23): name, version, private, scripts, dev, build, preview, dependencies (+15 more)

### Community 23 - "Playwright E2E Suite"
Cohesion: 0.12
Nodes (3): CATEGORIES, ROUTES, playwright-test (external)

### Community 30 - "React App Routing"
Cohesion: 0.18
Nodes (6): SnapshotBanner(), App(), KpiDetailPage(), SettingsPage(), e.ai.back.up.recession.dashboard.frontend.src.styles.css (external), react-dom-client (external)

### Community 48 - "Series"
Cohesion: 0.24
Nodes (10): TopNav(), BS2-001: sp500 pct_change was 12 trading days, not YoY, BS2-002: incremental-fetch lookback map missing 'daily' key, BS2-007: SettingsPage swallowed save and load errors, BS2-008: HomePage had no error state on core fetch failure, BS2-009: tautological e2e assertion masked top-nav as_of regression, BS2-010: f-string SQL in cleanup_db.py, BS2-011: uploadCsv did not check res.ok (+2 more)

### Community 38 - "Recession Gauge Component"
Cohesion: 0.25
Nodes (8): _get(), api, fmtDate(), CustomTooltip(), staticKey(), staticDataUrl(), ReadOnlySnapshotError, AR3-003: tooltip dead zone at far-left and far-right chart edges

### Community 24 - "Category Page UI"
Cohesion: 0.23
Nodes (8): fmtDate(), AiCommentaryPanel(), CATEGORY_LABELS, STATUS_COLOR, TREND_ICON, fmtVal(), fmtMonthYear(), CategoryPage()

### Community 8 - "Home Dashboard Charts"
Cohesion: 0.13
Nodes (14): AlertBanner(), SparkLine(), BAND_COLOR, RISK_BAND_COLOR, RISK_BAND_BG, fmtMonthYear(), probColor(), EXPLAIN (+6 more)

### Community 35 - "Manual CSV Upload"
Cohesion: 0.39
Nodes (9): KpiDetailChart(), HomePage(), BS2-006: missing stale-token guards in CategoryPage / KpiDetailPage / KpiDetailChart, AR3-001: KpiDetailChart renders blank for single-data-point KPIs, AR3-002: history endpoint 500 misreported as 'no data, run a refresh', AR3-004: Promise.all coupling suppresses chart when only NBER shading fails, Autoresearch Loop 3 — Frontend Rendering, Frontend stale-response token guard pattern (+1 more)

### Community 58 - "2026-06-12 bug-sweep session (146 tests passing)"
Cohesion: 0.31
Nodes (8): BAND_COLOR, BAND_INTERP, polarToXY(), arcPath(), RecessionGauge(), RefreshButton(), Manual CSV KPIs (no free API), Step 6 — reading the dashboard UI

### Community 28 - "Frontend API Client"
Cohesion: 0.33
Nodes (7): STATUS_CLASS, fmtDay(), fmtVal(), fmtImpact(), ImpactBar(), ScoreDriversPanel(), react-router-dom (external)

### Community 53 - "bootstrap_history"
Cohesion: 0.36
Nodes (8): BAND_LINES, RANGES, fmtDate(), fmtDay(), CustomTooltip(), snapPeriods(), snapDate(), ScoreHistoryChart()

### Community 34 - "Model Performance Page"
Cohesion: 0.15
Nodes (13): SIGNAL_COLORS, SHORT_NAMES, DEFAULT_HIDDEN, VALIDATION_STYLE, fmtDate(), fmtNum(), mergeSeries(), SignalTooltip() (+5 more)

### Community 39 - "Score Forecast Endpoint"
Cohesion: 0.39
Nodes (4): _nber(), date, TestForwardLabel, Build an NBER dict of `months` consecutive months from start.

### Community 32 - "KPI Config Integrity Tests"
Cohesion: 0.22
Nodes (4): test_unique_kpi_ids(), Catch the 'two KPIs share a FRED series_id' anti-pattern.  CLAUDE.md notes that, KPI ids must be unique., collections (external)

### Community 52 - "typing (external)"
Cohesion: 0.25
Nodes (8): _get_value_range(), date, _classify(), test_threshold_audit_all_kpis(), test_no_kpi_always_at_danger_with_recent_data(), Return (verdict, reason). verdict ∈ OK | NEVER_TRIGGERS | ALWAYS_TRIGGERS | INVE, Audit every KPI; produce a markdown report. Test PASSES even if there are     fi, Soft check: if a KPI has 12+ months of data and is ALWAYS in DANGER, the     thr

### Community 40 - "KPI Timing Tag Tests"
Cohesion: 0.67
Nodes (3): make_handler(), main(), Serve a static snapshot the way GitHub Pages does, for local testing.      pytho

### Community 61 - "os (external)"
Cohesion: 0.18
Nodes (10): Plan — Honest validation, benchmarks, and a static public snapshot, Goals (the four features), Key design decisions, Tasks, Backend, Frontend, Static export + CI, Tests & QA (+2 more)

### Community 0 - "KPI Catalog & Thresholds"
Cohesion: 0.06
Nodes (116): 10Y-2Y Treasury Spread, Daily Federal Funds Rate, 10Y-3M Treasury Spread, 5-Year Breakeven Inflation Rate, 10-Year Breakeven Inflation Rate, 10-Year Real Yield (TIPS), 2-Year Treasury Yield, 10-Year Treasury Yield (+108 more)

### Community 12 - "Refresh & ML Admin Endpoints"
Cohesion: 0.33
Nodes (9): BS2-004: live AI commentary cache never invalidated after refresh, AR4-001: POST /api/config type-validation DoS, AR4-003: CSV upload silently accepts files missing required columns, AR4-004: unknown KPI id on history endpoint returns 200 [], AR4-005: AI commentary generated for non-existent categories, AR4-006: CSV upload leaks UnicodeDecodeError internals, Autoresearch Loop 4 — API Error Paths, Unknown-id 404 contract for API endpoints (+1 more)

### Community 6 - "3-Month KPI Forecasting"
Cohesion: 0.25
Nodes (8): BS2-005: N+1 queries in /api/kpis (~156 per request), Project architecture layout, sqlalchemy>=2.0, fredapi>=0.5, yfinance>=0.2, requests>=2.31, statsmodels>=0.14, scipy>=1.10

### Community 25 - "Setup & Installation Guide"
Cohesion: 0.31
Nodes (11): PYT-001: threshold NEVER_TRIGGERS for 7 KPIs, PYT-002: gold_price permanently at DANGER, PYT-003: shiller_cape always at DANGER (likely accurate), PYT-005: housing_starts and housing_affordability share FRED HOUST, AR1-001: orphan fedfunds rows persist after retirement, AR5-004: prior-loop bugs re-confirmed still active, Autoresearch Loop 1 — Data Integrity, Initial pytest run findings (2026-04-25) (+3 more)

### Community 37 - "FRED Series Liveness Probe"
Cohesion: 0.21
Nodes (16): AR2-001: future as_of generated and persisted 873 fake cache rows, AR2-002: Time Machine score never clamped for future as_of, AR2-003: actual_value_at_forecast_date leaked today's data, AR2-004: forecast never returns actual_score in live mode, AR4-002: CSV upload accepts future-dated rows, AR5-001: /api/score returned date 2099-01-01 from corrupt cache, AR5-002: /api/score and /api/score/history latest disagree by 1.0 point, Autoresearch Loop 2 — Time Machine Correctness (+8 more)

### Community 49 - "Time Series Forecaster"
Cohesion: 0.24
Nodes (12): README Quick Start (15 minutes), Free API key registration table, Step 1 — verify Python is installed and on PATH, Step 2 — obtain a free FRED API key (only required key), Step 3 — create .env from .env.example, Step 4 — pip install -r requirements.txt, Step 5 — launch via launch.bat or python app.py, First-launch 5-year history bootstrap (+4 more)

### Community 42 - "Core Data Libraries"
Cohesion: 0.67
Nodes (3): pandas>=2.0, lxml>=5.0, numpy>=1.24

## Ambiguous Edges - Review These
- `README KPI catalog count (57 indicators)` → `H2 cleared: 78 KPIs across 8 categories, status counts agree`  [AMBIGUOUS]
  README.md · relation: conceptually_related_to
- `README KPI catalog count (57 indicators)` → `First-launch 5-year history bootstrap`  [AMBIGUOUS]
  README.md · relation: conceptually_related_to
- `statsmodels>=0.14` → `Project architecture layout`  [AMBIGUOUS]
  requirements.txt · relation: conceptually_related_to

## Knowledge Gaps
- **49 isolated node(s):** `build_frontend.sh script`, `name`, `version`, `private`, `dev` (+44 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `README KPI catalog count (57 indicators)` and `H2 cleared: 78 KPIs across 8 categories, status counts agree`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `README KPI catalog count (57 indicators)` and `First-launch 5-year history bootstrap`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `statsmodels>=0.14` and `Project architecture layout`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `compute_recession_score()` connect `APScheduler Daily Refresh` to `references/README.md`, `ML Feature Matrix & Score History`?**
  _High betweenness centrality (0.002) - this node is a cross-community bridge._
- **Why does `fetch_kpi()` connect `SPA Routing & NBER Shading` to `TestSeverityConfig`?**
  _High betweenness centrality (0.001) - this node is a cross-community bridge._
- **Why does `api_kpis()` connect `TestSeverityConfig` to `APScheduler Daily Refresh`, `Test Fixtures & KPI Status`, `Email Alerting & Thresholds`, `_is_plausible`?**
  _High betweenness centrality (0.000) - this node is a cross-community bridge._
- **What connects `build_frontend.sh script`, `name`, `version` to the rest of the system?**
  _49 weakly-connected nodes found - possible documentation gaps or missing edges._