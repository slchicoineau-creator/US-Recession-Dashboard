"""
Export a read-only static snapshot of the dashboard (e.g. for GitHub Pages).

    python tools/export_static.py [--refresh] [--out site] [--base /]
                                  [--repo-url URL] [--skip-build]

Steps:
  1. (--refresh) fetch data incrementally, persist today's live score, and make
     sure the ML models exist. Deliberately does NOT send alert emails and does
     NOT call the Anthropic API (the snapshot must be free and side-effect-free).
  2. Build the SPA in static mode (VITE_STATIC=1) into --out, with --base as the
     public path ("/" locally, "/<repo>/" on GitHub Pages), and copy index.html
     to 404.html so deep links work on GitHub Pages.
  3. Call every live-mode GET endpoint the SPA uses through Flask's test client
     and write each response to <out>/data/<static_key>.json, plus meta.json.

Only an explicit ALLOWLIST of read-only endpoints is exported. /api/config
(alert email settings) and /api/refresh/status are never exported, and the
export aborts if any configured secret value appears in the output.

static_key() MUST stay identical to staticKey() in frontend/src/staticMode.js.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qsl

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

SECRET_ENV_VARS = (
    "FRED_API_KEY", "BLS_API_KEY", "EIA_API_KEY", "CENSUS_API_KEY", "BEA_API_KEY",
    "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO", "ALERT_EMAIL_PASSWORD", "ANTHROPIC_API_KEY",
)


def static_key(path: str) -> str:
    """'/score/history?resolution=5y&include_ml=true'
    -> 'score__history--include_ml=true--resolution=5y.json'"""
    raw_path, _, query = path.partition("?")
    params = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k != "as_of"]
    params.sort(key=lambda kv: kv[0])
    key = raw_path.lstrip("/").replace("/", "__")
    if params:
        key += "--" + "--".join(f"{k}={v}" for k, v in params)
    return re.sub(r"[^A-Za-z0-9_.=-]", "_", key) + ".json"


def endpoint_allowlist(config: dict, category_ids: list) -> list:
    """Every GET path the SPA issues in live mode, spelled exactly as api.js does."""
    paths = [
        "/score",
        "/categories",
        "/kpis",
        "/nber-shading",
        "/score/history?from_date=2007-01-01&include_ml=true",
        "/score/history?resolution=5y&include_ml=true",
        "/score/history?resolution=2y&include_ml=true",
        "/score/history?resolution=1y&include_ml=true",
        "/score/forecast",
        "/score/drivers",
        "/leading",
        "/severity",
        "/benchmarks",
        "/ml/status",
        "/backtest",
        "/commentary/global",
    ]
    paths += [f"/commentary/category/{c}" for c in category_ids]
    paths += [f"/kpis/{k['id']}/history" for k in config.get("kpis", [])]
    return paths


def refresh_data() -> None:
    """Fetch + persist today's live score. No alerts, no AI commentary."""
    from backend.fetcher import bootstrap_history, clear_and_refetch_changed_series, fetch_all_kpis
    from backend.ml_scorer import get_or_train_model
    from backend.models import KpiData, get_session
    from backend.scorer import compute_recession_score

    # Same startup sequence as app.py: an empty DB (first CI run, or an expired
    # cache) is bootstrapped in full; otherwise changed series are re-fetched.
    session = get_session()
    try:
        empty = session.query(KpiData.id).first() is None
    finally:
        session.close()
    if empty:
        import app as app_module
        bootstrap_history()
        app_module._set_appconfig("history_years", str(app_module.HISTORY_YEARS))
    else:
        clear_and_refetch_changed_series()
    fetch_all_kpis(incremental=True)          # also refreshes NBER + reference series
    result = compute_recession_score()        # live call persists today's row + snapshot
    print(f"  live score {result['score']:.1f} ({result['band']})")
    if get_or_train_model() is None:
        print("  WARNING: ML models unavailable — probability tiles will be empty")


def build_spa(out_dir: str, base: str) -> None:
    env = dict(os.environ, VITE_STATIC="1", VITE_BASE=base, VITE_OUT_DIR=out_dir)
    npm = "npm.cmd" if os.name == "nt" else "npm"
    subprocess.run([npm, "run", "build"], cwd=os.path.join(ROOT, "frontend"), env=env, check=True)
    shutil.copyfile(os.path.join(out_dir, "index.html"), os.path.join(out_dir, "404.html"))


def write_route_shells(out_dir: str, config: dict, category_ids: list) -> int:
    """Copy index.html to <route>/index.html for every known SPA route.

    404.html alone makes deep links RENDER on GitHub Pages, but with HTTP 404,
    which crawlers, link unfurlers and uptime checks treat as missing. With a
    real file per route, Pages redirects /x -> /x/ and serves it with 200.
    """
    routes = ["performance", "settings"]
    routes += [f"category/{c}" for c in category_ids]
    routes += [f"kpi/{k['id']}" for k in config.get("kpis", [])]
    src = os.path.join(out_dir, "index.html")
    for r in routes:
        dst_dir = os.path.join(out_dir, *r.split("/"))
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copyfile(src, os.path.join(dst_dir, "index.html"))
    return len(routes)


def export_data(out_dir: str, repo_url: str) -> int:
    import app as app_module

    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    config = app_module._load_config()
    paths = endpoint_allowlist(config, list(app_module._CATEGORY_INFO))
    secrets = [v for v in (os.getenv(n, "") for n in SECRET_ENV_VARS) if v and len(v) >= 6]

    failures = []
    written = {}
    with app_module.app.test_client() as client:
        for path in paths:
            resp = client.get("/api" + path)
            if resp.status_code != 200:
                failures.append(f"{path} -> HTTP {resp.status_code}")
                continue
            body = resp.get_data(as_text=True)
            leaked = [s for s in secrets if s in body]
            if leaked:
                raise SystemExit(f"ABORT: a configured secret appeared in {path}")
            json.loads(body)  # must be valid JSON
            key = static_key(path)
            with open(os.path.join(data_dir, key), "w", encoding="utf-8") as f:
                f.write(body)
            written[path] = key
            print(f"  {path:<55} -> data/{key}")

    score = json.load(open(os.path.join(data_dir, static_key("/score")), encoding="utf-8"))
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "score_date": score.get("date"),
        "repo_url": repo_url or None,
        "files": written,
    }
    with open(os.path.join(data_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)

    if failures:
        print("\nEndpoints that failed (not exported):")
        for f_ in failures:
            print("  " + f_)
    return len(failures)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "site"))
    ap.add_argument("--base", default="/", help='public path, e.g. "/recession-dashboard/"')
    ap.add_argument("--repo-url", default=os.getenv("SNAPSHOT_REPO_URL", ""))
    ap.add_argument("--refresh", action="store_true", help="fetch fresh data first")
    ap.add_argument("--skip-build", action="store_true", help="only (re)export the JSON data")
    args = ap.parse_args()

    base = args.base if args.base.endswith("/") else args.base + "/"
    if not base.startswith("/"):
        base = "/" + base
    if ":" in base or " " in base:
        # Git Bash on Windows rewrites "/repo/" into "C:/Program Files/Git/repo/".
        raise SystemExit(
            f"--base looks like a filesystem path ({base!r}), not a URL path. "
            "In Git Bash, prefix the command with MSYS_NO_PATHCONV=1."
        )
    out_dir = os.path.abspath(args.out)

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from backend.models import init_db
    init_db()

    if args.refresh:
        print("Refreshing data…")
        refresh_data()
    repo_url = args.repo_url.strip()
    if re.search(r"github\.com/(example|your-?name|user)/", repo_url):
        print(f"  WARNING: ignoring placeholder --repo-url {repo_url!r}")
        repo_url = ""
    if not args.skip_build:
        print(f"Building static SPA into {out_dir} (base {base})…")
        build_spa(out_dir, base)
        import app as app_module
        n = write_route_shells(out_dir, app_module._load_config(), list(app_module._CATEGORY_INFO))
        print(f"  wrote {n} route shells (deep links return 200)")
    print("Exporting API responses…")
    n_failed = export_data(out_dir, repo_url)
    print(f"\nDone: {out_dir}" + (f" — {n_failed} endpoint(s) failed" if n_failed else ""))
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
