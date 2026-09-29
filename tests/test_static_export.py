"""Static snapshot export: path->file contract and endpoint allowlist.

The SPA (frontend/src/staticMode.js staticKey) and the exporter
(tools/export_static.py static_key) must map every API path to the same file
name, or the static site 404s. This test runs both implementations.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.export_static import endpoint_allowlist, static_key

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SAMPLE_PATHS = [
    "/score",
    "/score/history?from_date=2007-01-01&include_ml=true",
    "/score/history?include_ml=true&from_date=2007-01-01",     # order-independent
    "/score/history?resolution=5y&include_ml=true&as_of=2008-09-15",  # as_of dropped
    "/kpis/t10y2y/history",
    "/commentary/category/yield_curve",
]


def test_static_key_examples():
    assert static_key("/score") == "score.json"
    assert static_key("/kpis/t10y2y/history") == "kpis__t10y2y__history.json"
    assert (static_key("/score/history?resolution=5y&include_ml=true")
            == "score__history--include_ml=true--resolution=5y.json")
    assert static_key("/score?as_of=2008-09-15") == "score.json"
    assert (static_key("/score/history?from_date=2007-01-01&include_ml=true")
            == static_key("/score/history?include_ml=true&from_date=2007-01-01"))


def test_js_and_python_keys_match():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    module_url = (PROJECT_ROOT / "frontend" / "src" / "staticMode.js").as_uri()
    script = (
        f"const m = await import({json.dumps(module_url)});"
        f"console.log(JSON.stringify({json.dumps(SAMPLE_PATHS)}.map(m.staticKey)));"
    )
    out = subprocess.run([node, "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [static_key(p) for p in SAMPLE_PATHS]


def test_allowlist_is_read_only(kpi_config):
    paths = endpoint_allowlist(kpi_config, ["yield_curve"])
    assert "/config" not in paths and not any(p.startswith("/config") for p in paths)
    assert not any("refresh" in p or "upload" in p or "admin" in p or "train" in p for p in paths)
    assert f"/kpis/{kpi_config['kpis'][0]['id']}/history" in paths
    assert "/benchmarks" in paths and "/backtest" in paths
    assert len(paths) == len(set(paths))
