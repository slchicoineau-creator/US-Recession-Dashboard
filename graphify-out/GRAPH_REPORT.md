# Graph Report - E:\AI Back up\recession-dashboard  (2026-09-30)

## Corpus Check
- 81 files · ~73,035 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1167 nodes · 2717 edges · 60 communities (55 shown, 5 thin omitted)
- Extraction: 93% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 176 edges (avg confidence: 0.8)
- Token cost: 250,731 input · 0 output

## Community Hubs (Navigation)
- Manual CSV Upload
- Test Fixtures & KPI Status
- TestSeverityConfig
- FRED Series Liveness Probe
- Recession Score Computation
- Setup & Installation Guide
- Time Series Forecaster
- Email Alerting & Thresholds
- Composite Subscore Tests
- Severity Computation & History
- Database Schema & Migrations
- ML Training & Forward Labels
- Signal Backtesting
- NY Fed Auto Delinquency Fetch
- Timing Snapshot & Config Loading
- AI Commentary Generation
- assets/README.md
- fetch_kpi
- Data Fetching Pipeline
- SPA Routing & NBER Shading
- Refresh & ML Admin Endpoints
- _is_plausible
- Score & Analytics API
- Frontend Rendering Bugs
- Staleness Watchdog & Threshold Bugs
- 3-Month KPI Forecasting
- Leading Index History & Diffusion
- Category API & 404 Contract
- Score Forecast Endpoint
- _save_ml_score
- APScheduler Daily Refresh
- ML Feature Matrix & Score History
- references/README.md
- Severity Components & Bands
- Threshold Audit Tests
- Frontend Build Script
- Database Cleanup Script
- Frontend NPM Dependencies
- Playwright E2E Suite
- React App Routing
- Recession Gauge Component
- Category Page UI
- Home Dashboard Charts
- bootstrap_history
- Series
- 2026-06-12 bug-sweep session (146 tests passing)
- Frontend API Client
- Model Performance Page
- Vite Build Config
- ML Inference & Persistence
- KPI Config Integrity Tests
- typing (external)
- KPI Timing Tag Tests
- os (external)
- KPI Catalog & Thresholds
- Core Data Libraries
- matplotlib.dates (external)
- matplotlib.pyplot (external)

## God Nodes (most connected - your core abstractions)
1. `FRED Data Source` - 61 edges
2. `get_session()` - 53 edges
3. `compute_recession_score()` - 45 edges
4. `Coincident Indicator Timing Tag` - 43 edges
5. `Leading Indicator Timing Tag` - 32 edges
6. `KpiData` - 31 edges
7. `Row-Based pct_change Periods Transform` - 27 edges
8. `Financial Stress Category (weight 0.19)` - 25 edges
9. `_compute_kpi_status()` - 23 edges
10. `run_backtest()` - 23 edges

## Surprising Connections (you probably didn't know these)
- `Category Weights (must sum to 1.0)` --consumed_by--> `build_feature_matrix()`  [INFERRED]
  kpi_config.yaml → backend/ml_scorer.py
- `Row-Based pct_change Periods Transform` --consumed_by--> `_is_plausible()`  [INFERRED]
  kpi_config.yaml → backend/fetcher.py
- `BS2-003: /api/refresh check-then-set race` --references--> `api_refresh_status()`  [INFERRED]
  BUGS.md → app.py
- `BS2-004: live AI commentary cache never invalidated after refresh` --references--> `_invalidate_live_commentary()`  [INFERRED]
  BUGS.md → app.py
- `BS2-004: live AI commentary cache never invalidated after refresh` --references--> `_save_commentary()`  [INFERRED]
  BUGS.md → app.py

## Import Cycles
- None detected.

## Communities (60 total, 5 thin omitted)

### Community 35 - "Manual CSV Upload"
Cohesion: 0.13
Nodes (28): _load_config(), _utc_iso(), api_score_drivers(), admin_reset_score_history(), api_kpi_history(), api_nber_shading(), api_categories(), _invalidate_live_commentary() (+20 more)

### Community 3 - "Test Fixtures & KPI Status"
Cohesion: 0.13
Nodes (10): _compute_kpi_status(), Return OK / WARNING / DANGER / NO_DATA for a single KPI value.      Single sou, TestStandardKpi, TestInvertedKpi, TestEdgeCases, TestBugRegressionWarningTrigger, Test _compute_kpi_status from app.py.  Regression test for the 'Status Display B, invert=False (higher value = worse: unemployment, VIX, spreads). (+2 more)

### Community 54 - "TestSeverityConfig"
Cohesion: 0.12
Nodes (19): _parse_as_of(), date, api_ml_score_history(), api_leading(), api_leading_history(), api_severity(), api_ai_bubble(), api_ai_bubble_history() (+11 more)

### Community 37 - "FRED Series Liveness Probe"
Cohesion: 0.16
Nodes (22): api_score(), api_score_history(), api_score_forecast(), Compute a forecasted Recession Risk Score 3 months into the future.      Uses, compute_ml_scores_all(), All-horizon probabilities: {"now": x, "6m": y, "12m": z} (values may be None)., get_risk_band(), AR2-001: future as_of generated and persisted 873 fake cache rows (+14 more)

### Community 2 - "Recession Score Computation"
Cohesion: 0.10
Nodes (33): api_ml_train(), api_ml_status(), Trigger ML model training in a background thread. Returns 202 Accepted., Return per-horizon ML model metadata: training stats, coefficients., _iter_months(), date, build_feature_matrix(), DataFrame (+25 more)

### Community 25 - "Setup & Installation Guide"
Cohesion: 0.25
Nodes (9): _latest_rows_per_kpi(), api_kpis(), _set_appconfig(), Return {kpi_id: [rows newest-first]} with the newest `per_kpi` rows per KPI., Upsert a single AppConfig key-value pair., AppConfig, Key-value settings overrides (persists user changes from Settings page)., BS2-005: N+1 queries in /api/kpis (~156 per request) (+1 more)

### Community 49 - "Time Series Forecaster"
Cohesion: 0.11
Nodes (24): api_refresh(), api_refresh_status(), BS2-003: /api/refresh check-then-set race, H1 cleared: concurrent /api/refresh returns 409, README Quick Start (15 minutes), Free API key registration table, Project architecture layout, Daily 7:00 AM automatic refresh (+16 more)

### Community 13 - "Email Alerting & Thresholds"
Cohesion: 0.17
Nodes (20): api_config(), _get_config(), get_warning_threshold(), get_critical_threshold(), alerts_enabled(), _last_alert_time(), _in_cooldown(), _log_alert() (+12 more)

### Community 36 - "Composite Subscore Tests"
Cohesion: 0.39
Nodes (8): api_upload_csv(), _save_series(), Upsert a pandas Series of (date -> value) into kpi_data.      Returns (rows_inse, AR4-002: CSV upload accepts future-dated rows, AR4-003: CSV upload silently accepts files missing required columns, AR4-006: CSV upload leaks UnicodeDecodeError internals, Autoresearch Loop 4 — API Error Paths, Manual CSV KPIs (no free API)

### Community 31 - "Severity Computation & History"
Cohesion: 0.24
Nodes (13): serve_spa(), BS2-004: live AI commentary cache never invalidated after refresh, PW-001: Flask returned 404 for SPA deep links, AR4-004: unknown KPI id on history endpoint returns 200 [], AR4-005: AI commentary generated for non-existent categories, AR5-003: /api/* typos masked as 200 + index.html by SPA fallback, Playwright run findings, Unknown-id 404 contract for API endpoints (+5 more)

### Community 15 - "Database Schema & Migrations"
Cohesion: 0.21
Nodes (19): _all_kpi_ids(), _score_gauge(), date, compute_ai_bubble(), _exposure_peak(), compute_ai_bubble_history(), AI Bubble Monitor.  The composite Recession Risk Score measures how LIKELY a r, Exposure + puncture readings for one date (Time-Machine aware). (+11 more)

### Community 10 - "ML Training & Forward Labels"
Cohesion: 0.18
Nodes (6): get_band(), _verdict(), `exposure` should be the trailing-12-month peak (see module docstring)., TestIsolation, TestScoring, Tests for the AI Bubble Monitor (backend/ai_bubble.py) and its isolation.  The m

### Community 4 - "Signal Backtesting"
Cohesion: 0.06
Nodes (36): _iter_months(), date, _monthly_composite(), _load_nber(), _recession_onsets(), _months_between(), _lead_times(), _false_alarm_episodes() (+28 more)

### Community 5 - "NY Fed Auto Delinquency Fetch"
Cohesion: 0.10
Nodes (34): _ref_config(), _pub_lag(), load_reference(), spread_series(), _nber_long(), _feature_month(), date, _training_frame() (+26 more)

### Community 19 - "Timing Snapshot & Config Loading"
Cohesion: 0.12
Nodes (16): discount_to_bey(), T-bill discount-basis yield (%) -> bond-equivalent yield (%), as the NY Fed does, _nber_label_lag_months(), label_known(), walk_forward_ml(), NBER dating lag from kpi_config.yaml (reference_series usrecm_long)., Whether the training label for `month` at `horizon_months` was public at `at`., Out-of-sample Logit probabilities, one expanding-window refit per month. (+8 more)

### Community 14 - "AI Commentary Generation"
Cohesion: 0.16
Nodes (15): _get_client(), is_available(), _get_model(), _band(), _status_emoji(), build_category_prompt(), date_type, build_global_prompt() (+7 more)

### Community 66 - "assets/README.md"
Cohesion: 0.18
Nodes (11): _iter_recent_quarters(), _find_latest_nyfed_quarter(), Data fetcher for the Recession Risk Dashboard.  Dispatches to the correct API cl, Yield (year, quarter) pairs newest-first from the current quarter., HEAD-probe backward for the newest published quarter.      Discovery this way co, # NOTE: this window does NOT cover annual benchmark/seasonal-factor, # NOTE: a URL for an unpublished quarter returns HTTP **200** with an HTML, dotenv (external) (+3 more)

### Community 56 - "fetch_kpi"
Cohesion: 0.06
Nodes (25): load_config(), _download_gdpnow_xlsx(), _fetch_nyfed_hhdc_workbook(), Return the GDPNow workbook bytes, rediscovering the URL if it moved.      Tries, Download the newest published Household Debt & Credit workbook.      The file na, _resp(), _router(), TestGdpnowDownload (+17 more)

### Community 1 - "Data Fetching Pipeline"
Cohesion: 0.14
Nodes (16): _retry(), fetch_bls_series(), fetch_eia_series(), fetch_tsa_throughput(), fetch_shiller_cape(), fetch_atlanta_gdpnow(), Exponential-backoff retry wrapper., Fetch a BLS series via the public API v2. (+8 more)

### Community 22 - "SPA Routing & NBER Shading"
Cohesion: 0.16
Nodes (20): fetch_fred_series(), date, Series, fetch_yfinance(), _fetch_enplane_historical(), _quarter_start(), fetch_nyfed_auto_delinquency(), fetch_derived_ma() (+12 more)

### Community 12 - "Refresh & ML Admin Endpoints"
Cohesion: 0.11
Nodes (19): fetch_nber_shading(), fetch_reference_series(), Fetch FRED USRECM (monthly 0/1 recession indicator) and cache to DB., Fetch every `reference_series:` entry in full and upsert it.      These are smal, Base, DeclarativeBase, NberRecession, ReferenceSeries (+11 more)

### Community 71 - "_is_plausible"
Cohesion: 0.14
Nodes (8): _is_plausible(), TestPlausibleRanges, TestComputeDiff, TestComputePctChange, Tests for the transforms applied to FRED series before storage:   - compute_diff, compute_diff applies pandas .diff() to convert level → MoM change., compute_pct_change_periods: pct_change(N) * 100, drop ±inf., pandas (external)

### Community 9 - "Score & Analytics API"
Cohesion: 0.21
Nodes (13): _latest_date_in_db(), fetch_kpi(), clear_and_refetch_changed_series(), fetch_all_kpis(), bootstrap_history(), Fetch and store data for a single KPI definition dict., Detect KPIs whose series_id, compute_diff, or compute_pct_change_periods changed, Loop through kpi_config.yaml and fetch every KPI. (+5 more)

### Community 17 - "Frontend Rendering Bugs"
Cohesion: 0.24
Nodes (13): purge_retired_kpis(), Delete DB rows for any KPI id that is no longer in the config., PYT-001: threshold NEVER_TRIGGERS for 7 KPIs, PYT-002: gold_price permanently at DANGER, PYT-003: shiller_cape always at DANGER (likely accurate), PYT-005: housing_starts and housing_affordability share FRED HOUST, AR1-001: orphan fedfunds rows persist after retirement, AR5-004: prior-loop bugs re-confirmed still active (+5 more)

### Community 7 - "Staleness Watchdog & Threshold Bugs"
Cohesion: 0.18
Nodes (15): check_staleness(), Log ERROR for any KPI whose latest DB row is older than its window., _seed(), test_staleness_threshold(), test_manual_csv_skipped(), test_no_data_no_alarm(), test_live_db_no_stale_kpis(), Test for backend.fetcher.check_staleness watchdog.  Seeds a temp DB with KPI row (+7 more)

### Community 6 - "3-Month KPI Forecasting"
Cohesion: 0.22
Nodes (13): _forecast_date(), date, forecast_kpi(), forecast_all_kpis(), compute_forecast_accuracy(), compute_forecast_status(), 3-Month KPI Forecaster.  Uses linear regression (OLS via numpy.polyfit) on the l, Return the target forecast date: exactly 3 months after as_of. (+5 more)

### Community 18 - "Leading Index History & Diffusion"
Cohesion: 0.18
Nodes (12): _kpis_by_timing(), _value_on_or_before(), date, _diffusion(), compute_timing_snapshot(), compute_timing_history(), Last value on or before as_of (binary search), None if too stale/missing., % of KPIs moving in the risk-increasing direction over 3 months. (+4 more)

### Community 21 - "Category API & 404 Contract"
Cohesion: 0.19
Nodes (6): _composite_from_subscores(), Apply the scorer's peak-weighted category methodology to a KPI subset.      valu, TestTimingTags, TestCompositeFromSubscores, Tests for the leading-indicator module and the timing tags in kpi_config., A diffusion index over too few KPIs is noise; require breadth.

### Community 39 - "Score Forecast Endpoint"
Cohesion: 0.29
Nodes (7): forward_label(), 1 if any NBER recession month falls within (month, month + horizon].      Retu, _nber(), date, TestForwardLabel, Unit tests for the multi-horizon ML scorer (forward labels + training)., Build an NBER dict of `months` consecutive months from start.

### Community 69 - "_save_ml_score"
Cohesion: 0.33
Nodes (6): train_logit_model(), Train a statsmodels Logit model on the feature matrix for one label column., _synthetic_matrix(), DataFrame, TestTrainLogit, Feature matrix where financial_stress cleanly drives the label.

### Community 27 - "APScheduler Daily Refresh"
Cohesion: 0.06
Nodes (28): KpiData, Time-series values for every KPI., normalize_kpi(), _latest_value(), _value_as_of(), date, compute_recession_score(), Return a 0.0–1.0 recession risk sub-score for the given KPI value.      0.0 = (+20 more)

### Community 29 - "ML Feature Matrix & Score History"
Cohesion: 0.08
Nodes (47): RecessionScore, KpiSnapshot, Daily computed recession risk scores., Per-KPI values the live score actually used on a given day.      Written along, sample_dates(), date, previous_business_day(), _SeriesIndex (+39 more)

### Community 67 - "references/README.md"
Cohesion: 0.17
Nodes (11): _daily_job(), start_scheduler(), BackgroundScheduler, next_run_time(), APScheduler setup for daily automatic data refresh., Start the APScheduler background scheduler.      Args:         refresh_time: "HH, Daily 07:00 Refresh Schedule, apscheduler.schedulers.background (external) (+3 more)

### Community 20 - "Severity Components & Bands"
Cohesion: 0.19
Nodes (12): component_subscore(), Linear 0-1 interpolation between healthy (0) and extreme (1).      Direction is, TestComponentSubscore, Severity Component: Deflation (weight 0.25), Severity Component: Bank Credit Contraction (weight 0.25), Severity Component: Money Supply Contraction (weight 0.15), Severity Component: Labor Market Depth (weight 0.20), Severity Component: Persistence at CRITICAL (weight 0.15) (+4 more)

### Community 26 - "Threshold Audit Tests"
Cohesion: 0.14
Nodes (11): get_severity_band(), _persistence_months(), date, compute_severity(), Distinct calendar months in the trailing 12 with composite >= CRITICAL., Compute the Depression Severity score for one date., TestSeverityConfig, TestSeverityBands (+3 more)

### Community 11 - "Frontend NPM Dependencies"
Cohesion: 0.08
Nodes (23): name, version, private, scripts, dev, build, preview, dependencies (+15 more)

### Community 23 - "Playwright E2E Suite"
Cohesion: 0.12
Nodes (3): CATEGORIES, ROUTES, playwright-test (external)

### Community 30 - "React App Routing"
Cohesion: 0.18
Nodes (7): TopNav(), SnapshotBanner(), App(), KpiDetailPage(), BS2-009: tautological e2e assertion masked top-nav as_of regression, e.ai.back.up.recession.dashboard.frontend.src.styles.css (external), react-dom-client (external)

### Community 38 - "Recession Gauge Component"
Cohesion: 0.28
Nodes (6): _get(), api, staticKey(), staticDataUrl(), ReadOnlySnapshotError, react (external)

### Community 24 - "Category Page UI"
Cohesion: 0.21
Nodes (9): fmtDate(), AiCommentaryPanel(), CATEGORY_LABELS, STATUS_COLOR, TREND_ICON, fmtVal(), fmtMonthYear(), CategoryPage() (+1 more)

### Community 8 - "Home Dashboard Charts"
Cohesion: 0.12
Nodes (14): AlertBanner(), SparkLine(), BAND_COLOR, RISK_BAND_COLOR, RISK_BAND_BG, fmtMonthYear(), probColor(), EXPLAIN (+6 more)

### Community 53 - "bootstrap_history"
Cohesion: 0.24
Nodes (11): fmtDate(), CustomTooltip(), BAND_LINES, RANGES, fmtDate(), fmtDay(), CustomTooltip(), snapPeriods() (+3 more)

### Community 48 - "Series"
Cohesion: 0.22
Nodes (16): KpiDetailChart(), HomePage(), SettingsPage(), BS2-001: sp500 pct_change was 12 trading days, not YoY, BS2-002: incremental-fetch lookback map missing 'daily' key, BS2-006: missing stale-token guards in CategoryPage / KpiDetailPage / KpiDetailChart, BS2-007: SettingsPage swallowed save and load errors, BS2-008: HomePage had no error state on core fetch failure (+8 more)

### Community 58 - "2026-06-12 bug-sweep session (146 tests passing)"
Cohesion: 0.36
Nodes (7): BAND_COLOR, BAND_INTERP, polarToXY(), arcPath(), RecessionGauge(), RefreshButton(), Step 6 — reading the dashboard UI

### Community 28 - "Frontend API Client"
Cohesion: 0.39
Nodes (6): STATUS_CLASS, fmtDay(), fmtVal(), fmtImpact(), ImpactBar(), ScoreDriversPanel()

### Community 34 - "Model Performance Page"
Cohesion: 0.15
Nodes (13): SIGNAL_COLORS, SHORT_NAMES, DEFAULT_HIDDEN, VALIDATION_STYLE, fmtDate(), fmtNum(), mergeSeries(), SignalTooltip() (+5 more)

### Community 16 - "ML Inference & Persistence"
Cohesion: 0.06
Nodes (47): project_root(), Path, real_db_path(), real_session(), tmp_session(), _frequency_window_days(), staleness_window(), Shared pytest fixtures for the recession-dashboard test suite.  Two DB modes: (+39 more)

### Community 32 - "KPI Config Integrity Tests"
Cohesion: 0.22
Nodes (4): test_unique_kpi_ids(), Catch the 'two KPIs share a FRED series_id' anti-pattern.  CLAUDE.md notes that, KPI ids must be unique., collections (external)

### Community 52 - "typing (external)"
Cohesion: 0.21
Nodes (11): _get_value_range(), date, _classify(), test_threshold_audit_all_kpis(), test_no_inverted_bad_thresholds(), test_no_kpi_always_at_danger_with_recent_data(), Threshold-vs-data sanity sweep against the live DB.  Catches the unit-mismatch b, Return (verdict, reason). verdict ∈ OK | NEVER_TRIGGERS | ALWAYS_TRIGGERS | INVE (+3 more)

### Community 40 - "KPI Timing Tag Tests"
Cohesion: 0.67
Nodes (3): make_handler(), main(), Serve a static snapshot the way GitHub Pages does, for local testing.      pytho

### Community 61 - "os (external)"
Cohesion: 0.18
Nodes (10): Plan — Honest validation, benchmarks, and a static public snapshot, Goals (the four features), Key design decisions, Tasks, Backend, Frontend, Static export + CI, Tests & QA (+2 more)

### Community 0 - "KPI Catalog & Thresholds"
Cohesion: 0.07
Nodes (105): 10Y-2Y Treasury Spread, Daily Federal Funds Rate, 10Y-3M Treasury Spread, 5-Year Breakeven Inflation Rate, 10-Year Breakeven Inflation Rate, 10-Year Real Yield (TIPS), 2-Year Treasury Yield, 10-Year Treasury Yield (+97 more)

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
- **50 isolated node(s):** `build_frontend.sh script`, `name`, `version`, `private`, `dev` (+45 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `README KPI catalog count (57 indicators)` and `H2 cleared: 78 KPIs across 8 categories, status counts agree`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `README KPI catalog count (57 indicators)` and `First-launch 5-year history bootstrap`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `statsmodels>=0.14` and `Project architecture layout`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `compute_recession_score()` connect `APScheduler Daily Refresh` to `ML Feature Matrix & Score History`, `Database Schema & Migrations`?**
  _High betweenness centrality (0.001) - this node is a cross-community bridge._
- **Why does `fetch_kpi()` connect `Score & Analytics API` to `Data Fetching Pipeline`, `Composite Subscore Tests`, `SPA Routing & NBER Shading`?**
  _High betweenness centrality (0.001) - this node is a cross-community bridge._
- **Why does `fetch_all_kpis()` connect `Score & Analytics API` to `fetch_kpi`, `Frontend Rendering Bugs`, `Refresh & ML Admin Endpoints`, `Staleness Watchdog & Threshold Bugs`?**
  _High betweenness centrality (0.001) - this node is a cross-community bridge._
- **What connects `build_frontend.sh script`, `name`, `version` to the rest of the system?**
  _50 weakly-connected nodes found - possible documentation gaps or missing edges._