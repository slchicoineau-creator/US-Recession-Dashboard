# US Economy KPI Dashboard — Setup Guide

Follow these steps in order. Each step only needs to be done once.

---

## Step 1 — Check that Python is installed

Open CMD (press **Win + R**, type `cmd`, press Enter) and run:

```
python --version
```

You should see something like `Python 3.11.x`. If you get an error, download
Python from https://www.python.org/downloads/ and check "Add Python to PATH"
during install.

---

## Step 2 — Get a free FRED API key (required)

1. Go to https://fred.stlouisfed.org/docs/api/api_key.html
2. Click **"Request API Key"** and create a free account
3. Copy the key — it looks like `abcdef1234567890abcdef1234567890`

The other API keys (BLS, EIA, Census, BEA) are optional. The dashboard works
with only the FRED key; some KPIs will be skipped if their key is missing.

---

## Step 3 — Create the .env file

1. Open the folder `e:\AI Back up\recession-dashboard\` in File Explorer
2. Find the file named `.env.example`
3. Make a copy of it and rename the copy to `.env`
   - (It is normal for Windows to ask "are you sure?" — click Yes)
4. Open `.env` with Notepad
5. Replace `your_fred_api_key_here` with the key you got in Step 2
6. Save and close

Your `.env` should look like this (only FRED is required):

```
FRED_API_KEY=abcdef1234567890abcdef1234567890
BLS_API_KEY=
EIA_API_KEY=
CENSUS_API_KEY=
BEA_API_KEY=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=
ALERT_EMAIL_PASSWORD=
```

---

## Step 4 — Install Python packages (one time only)

Open CMD and run these two commands **one at a time**:

```
cd "e:\AI Back up\recession-dashboard"
```

> **Note:** After typing `cd`, CMD will appear to do nothing and just show a new
> prompt — that is correct. It silently changed to that folder.

Then run:

```
pip install -r requirements.txt
```

Wait for it to finish (about 1–2 minutes). You will see a list of packages being
installed.

---

## Step 5 — Launch the dashboard

**Option A — Double-click (easiest):**

Find `launch.bat` in `e:\AI Back up\recession-dashboard\` and double-click it.
A black CMD window will open and the dashboard will start. Your browser will
open automatically to http://localhost:5000.

**Option B — From CMD:**

```
cd "e:\AI Back up\recession-dashboard"
python app.py
```

Then open your browser and go to **http://localhost:5000**

---

## What happens on first launch

The first time you start the app, it will download **5 years of historical data**
for all KPIs from FRED and other sources. This takes approximately **2–5 minutes**
and shows a progress bar in the CMD window:

```
Bootstrapping 5-year history for 45 KPIs (this may take a few minutes)…

[████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 14/45  t10y2y
```

Do not close the CMD window while this is running. Once it finishes, the
dashboard opens automatically.

On all future launches, it only fetches new data (incremental refresh) which
takes a few seconds.

---

## Step 6 — Using the dashboard

| What you see | What it means |
|---|---|
| **Gauge at top** | Recession Risk Score 0–100 (green=safe, red=critical) |
| **Category cards** | Click any card to see all KPIs in that category |
| **KPI table rows** | Click any row to see the 5-year chart for that indicator |
| **Refresh Now button** | Fetches the latest data immediately |
| **Settings page** | Change alert thresholds; upload manual CSV data |

---

## Keeping it running

The CMD window must stay open for the dashboard to work. Closing it shuts down
the server. To stop, just close the CMD window or press **Ctrl + C** inside it.

The dashboard automatically refreshes data every day at **7:00 AM** as long as
it is running.

---

## Troubleshooting

**"cd did nothing" in CMD**
That is normal. `cd` silently changes your current folder. The next command you
type will run inside that folder.

**"python is not recognized"**
Python is not installed or not in your PATH. Download from python.org and make
sure to check "Add Python to PATH" during setup.

**"No module named flask" or similar**
You need to run Step 4 (pip install). Make sure you ran it from inside the
`recession-dashboard` folder.

**Dashboard loads but shows "—" everywhere**
The bootstrap is still running, or your FRED API key is missing/wrong.
Check the CMD window for error messages.

**Browser does not open automatically**
Manually go to http://localhost:5000 in your browser while the CMD window is open.

**Error: address already in use**
Another instance is already running. Close all CMD windows and try again.
