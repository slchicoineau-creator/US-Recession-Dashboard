# Plan — Honest validation, benchmarks, and a static public snapshot

Date: 2026-09-26. Source: comparison against open-source recession dashboards
(SecondOrderEdge/Macro-Dashboard, recessionrisk.com, Comeon2022, macro-regime-radar).

## Goals (the four features)

1. **Walk-forward (out-of-sample) backtest + Brier score + calibration chart.**
   Today `ml_12m`/`ml_6m` are trained once on all data and then backtested on
   that same data, so AUROC 0.834 is in-sample.
2. **Yield-curve probit benchmark** (NY Fed / Estrella–Mishkin method): P(recession
   within 12 months) = Φ(a + b · spread), spread = 10y − 3m bill, fitted on 1959+
   (9 recessions vs. the ML model's 2).
3. **Chauvet–Piger smoothed recession probability** (FRED `RECPROUSM156N`) as a
   published coincident cross-check.
4. **Static read-only public snapshot**: export API responses to JSON, build the
   SPA in "static mode", deploy nightly via GitHub Actions to GitHub Pages.

## Key design decisions

- **Benchmarks are NOT KPIs.** Adding GS10/TB3MS/RECPROUSM156N as KPIs would
  change the composite score, category weights and the ML feature matrix
  (domino effect per CLAUDE.md). They go in a new `reference_series:` section of
  `kpi_config.yaml` (config stays single source of truth) and a new
  `reference_series` DB table.
- **Long NBER history goes in `reference_series` too (USRECM 1959+), not
  `nber_recessions`.** The graph shows `NberRecession` feeds `/api/nber-shading`,
  which every chart draws with `ifOverflow="extendDomain"` — extending it to
  1959 would stretch every chart's x-axis back to 1959.
- **Walk-forward label availability.** A training row for month *m* at horizon
  *h* is usable at time *t* only if `m + h + NBER_LAG <= t`. `NBER_LAG = 12`
  months (NBER dated the Dec-2007 peak in Dec-2008). Consequence: the ML models
  can't make any out-of-sample prediction for 2008 (the feature history starts
  2007-01), so 2008 shows as "no model yet". That is the honest result, and the
  page says so.
- **The live ML models are unchanged.** Walk-forward is used only for
  evaluation, so no retrain, no `ML_MODEL_VERSION` bump, and no cache
  invalidation.
- **In-sample rows are kept and labelled** ("in-sample") next to the new
  walk-forward rows, so the gap is visible.
- **Static mode is a build flag** (`VITE_STATIC=1`). `api.js` maps each GET to a
  JSON file; mutations throw. The UI hides Refresh, Time Machine, Settings, the
  commentary "Generate" buttons and ML Train. `?as_of=` in the URL shows a notice
  instead of breaking.

## Tasks

### Backend
1. `kpi_config.yaml`: new top-level `reference_series:` list — `usrecm_long`
   (USRECM), `gs10` (GS10), `tb3ms` (TB3MS), `chauvet_piger` (RECPROUSM156N), each
   with `series_id`, `start`, `description`.
2. `backend/models.py`: `ReferenceSeries(series_key, date, value)` with a unique
   (series_key, date) constraint. `init_db` creates it (create_all).
3. `backend/fetcher.py`: `fetch_reference_series()` — full refetch each call
   (tiny monthly series, and revisions get picked up for free). Called from
   `fetch_all_kpis` and `bootstrap_history`, and at startup when the table is empty.
4. New `backend/benchmarks.py`:
   - `load_reference(key)`, `spread_series()` (GS10 − TB3MS converted to
     bond-equivalent yield, as the NY Fed does)
   - `fit_probit(until)`, `yield_curve_prob(month, as_of=None)`, and
     `yield_curve_walkforward(from, to)` (refit yearly for speed)
   - `chauvet_piger_series()`, `current_benchmarks(as_of=None)`
5. `backend/ml_scorer.py`: `walk_forward_ml(horizon, from, to, refit_every=12)` —
   expanding-window Logit on the cached feature matrix. Returns
   {month: prob or None}. Needs ≥ 36 training rows with ≥ 1 positive and ≥ 1
   negative, otherwise None.
6. `backend/backtester.py`:
   - new signals `ml_12m_wf`, `ml_6m_wf`, `yield_curve`, `chauvet_piger`;
     existing ML rows renamed "(in-sample)"
   - `brier`, `brier_skill` (vs a constant base rate) and `calibration` (10 bins:
     mean predicted, observed rate, n) for probability signals, each scored
     against its own horizon's label (12m, 6m, or coincident for Chauvet–Piger)
   - `kind: "score" | "probability"` and `validation: "in-sample" |
     "walk-forward" | "published"` per signal; an updated caveat
7. `app.py`: `GET /api/benchmarks[?as_of=]`. In the Time Machine the yield-curve
   probit uses the walk-forward fit for `as_of`; Chauvet–Piger uses the latest
   value ≤ as_of.

### Frontend
8. `ModelPerformancePage.jsx`: metrics table with Validation/Brier/BSS columns,
   a calibration (reliability) chart, the new signal lines, and explainer text.
9. `HomePage.jsx` ProbabilityPanel: a "Benchmarks" line (yield-curve model X% /
   12 mo, Chauvet–Piger Y% now, with month). Shown in the Time Machine too.
10. Static mode: `api.js` path→file mapping, `import.meta.env.BASE_URL`
    router basename, hide the mutation UI, and a snapshot banner showing the date.

### Static export + CI
11. `tools/export_static.py`: runs the Flask `test_client` over every live GET
    endpoint and writes `site/data/*.json` plus `meta.json`, builds the SPA with
    `VITE_STATIC=1`, copies `index.html` to `404.html` (deep links on Pages),
    and optionally runs a refresh first (`--refresh`).
12. `.github/workflows/publish-static.yml`: nightly cron + manual dispatch; DB
    kept in the actions cache; FRED/BLS/EIA keys from secrets; deploy to Pages.
    **Cannot be tested here (not a git repo)**, so it is validated only by
    running the same commands locally.

### Tests & QA
13. pytest: walk-forward label-availability (no leakage), probit sanity (the
    coefficient on the spread is negative), Brier/calibration maths, the
    benchmarks endpoint, reference-series config, and static path mapping (Python
    and JS use the same key function).
14. Playwright specs: update `performance.spec.ts` and `api_contracts.spec.ts`,
    and add `static.spec.ts` against the static build served by `http.server`.
15. Playwright CLI QA + critic subagents (the Performance page, the Home
    benchmarks line, the static site), then fix their findings.
16. Rebuild the frontend, run graphify update + bridge, and update CLAUDE.md.

## Out of scope
Uncertainty bands, and changing the live ML model or the composite score.

## As built (differences from the plan above)

- Lead / false-alarm windows are **horizon + 6 months** per signal (18 for
  12-month signals and scores, 12 for 6-month models), not a fixed 24 / 18.
  Leads that start in the first data month carry `lead_censored` ("≥").
- Yield-curve fits require **≥ 3 recessions** in the public training window
  and a negative spread slope (`MIN_TRAIN_RECESSIONS`); otherwise n/a.
- The walk-forward ML refits **monthly** (not yearly) using a Newton solver
  (`safe_fit`); refits that separate are counted and shown on the page.
- The common window **excludes** signals with no recession in their coverage
  (ml_12m_wf), instead of intersecting everything.
- Static export also writes **route shells** (`<route>/index.html`) so deep
  links return HTTP 200, not only the 404.html fallback.
- Timestamps from `utcnow()` are serialised with `+00:00` (`app._utc_iso`) —
  a pre-existing "Last updated" timezone bug found during QA.
- `requirements.txt` gained `openpyxl` and `tzlocal` (used but undeclared).
- Results and test totals: see CLAUDE.md, "Honest Validation, Benchmarks +
  Static Snapshot (September 2026)".
