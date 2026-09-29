# US Economy KPI Dashboard — Recession Risk Monitor

A local browser-based dashboard that fetches 57 US economic indicators from free
public APIs, stores 5 years of history in SQLite, and computes a daily
**Recession Risk Score (0–100)**. Email alerts fire when the score crosses
configurable thresholds.

---

## Quick Start (≈ 15 minutes)

### 1. Install Python dependencies

```bash
cd recession-dashboard
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` and add your free API keys:

| Key | Get it at |
|-----|-----------|
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html |
| `BLS_API_KEY` | https://data.bls.gov/registrationEngine/registerBLS.htm |
| `EIA_API_KEY` | https://www.eia.gov/opendata/register.php |
| `CENSUS_API_KEY` | https://api.census.gov/data/key_signup.html |
| `BEA_API_KEY` | https://apps.bea.gov/API/signup/index.cfm |

Email alerts (optional — leave blank to disable):
```
ALERT_EMAIL_FROM=you@gmail.com
ALERT_EMAIL_TO=you@gmail.com
ALERT_EMAIL_PASSWORD=your_gmail_app_password
```

### 3. Build the frontend (one time)

```bash
cd frontend
npm install
npm run build
cd ..
```

### 4. Launch

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

On first launch the app downloads **5 years of historical data** for all KPIs
(may take 2–5 minutes). A progress bar is shown in the terminal.

---

## Architecture

```
recession-dashboard/
  app.py                  Flask entry point + all API routes
  kpi_config.yaml         Single source of truth for all 57 KPIs
  requirements.txt
  .env                    API keys (never committed)
  backend/
    models.py             SQLAlchemy ORM (5 tables)
    fetcher.py            FRED / BLS / EIA / yfinance / TSA data fetching
    scorer.py             Weighted recession score computation
    scheduler.py          APScheduler daily 7 AM refresh
    alerter.py            Email alert dispatch
  frontend/
    src/                  React + Vite source
    dist/                 Built SPA (served by Flask)
  data/
    recession_kpi.db      SQLite database (auto-created)
  logs/
    app.log               Rotating log file (auto-created)
```

---

## Recession Risk Score

| Score | Band | Color | Interpretation |
|-------|------|-------|----------------|
| 0–24  | LOW | 🟢 Green | Economy broadly healthy |
| 25–49 | ELEVATED | 🟡 Yellow | 1–2 indicators warning |
| 50–74 | HIGH | 🟠 Orange | Multiple signals; recession historically within 6–12 months |
| 75–100 | CRITICAL | 🔴 Red | Broad-based signals; analogous to 2008/2020 |

Category weights: Yield Curve 20%, Labor Market 20%, Consumer Health 15%,
Housing 12%, Financial Stress 12%, Business Activity 11%, Energy 5%, Automotive 5%.

---

## Manual CSV KPIs

Four KPIs have no free API and require manual monthly uploads via the Settings page:

| KPI | Expected columns |
|-----|-----------------|
| Used Vehicle Price Index (Manheim) | date, value |
| Vehicle Repossession Rate | date, value |
| New Vehicle Inventory (Days Supply) | date, value |
| Hotel Occupancy Rate | date, value |

---

## Scheduler

The dashboard automatically refreshes all data daily at **7:00 AM local time**
(configurable in `kpi_config.yaml` → `refresh_schedule`). Use the
**"Refresh Now"** button in the UI for an immediate manual fetch.
