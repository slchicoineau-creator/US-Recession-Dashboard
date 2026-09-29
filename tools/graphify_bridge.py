"""Post-rebuild repair for the graphify graph: prune noise, bridge config->code.

Run this after EVERY `graphify update` / `/graphify` rebuild on this project.
It restores two invariants that a plain graphify rebuild does not preserve.

WHY THIS EXISTS
---------------
1. CONFIG AND CODE ARE TWO DISCONNECTED ISLANDS.
   graphify builds from two independent passes: AST extraction over the
   .py/.jsx/.ts sources, and semantic extraction over kpi_config.yaml. Neither
   can see the other, because the code never names a KPI id — it reads the YAML
   generically at runtime. So nothing links
   `kpi_config_auto_90d_delinquency` to `compute_recession_score`, and the raw
   graph has *no path between* the 123 config nodes and the code nodes. That
   makes it useless for the question it most needs to answer: "if I change this
   KPI, what breaks?" The BRIDGES table below adds those edges. Every entry
   mirrors a real dependency in the source and records the mechanism it came
   from, so the claim can be re-checked.

2. REBUILDS RE-IMPORT VENDORED NOISE.
   `graphify update` re-extracts everything it can see, including third-party
   skill documentation under .agents/skills/ and .claude/skills/ (which are
   duplicates of each other) and generated build output. That added 223 nodes
   forming isolated communities that dilute community detection and the
   god-node ranking. PRUNE_PREFIXES drops them again.

IDEMPOTENT — safe to re-run. Reports what it changed.

    python tools/graphify_bridge.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

GRAPH = Path(__file__).resolve().parent.parent / "graphify-out" / "graph.json"


def _reexec_with_graphify_interpreter() -> None:
    """Re-run under the interpreter that actually has graphify installed.

    graphify is typically installed via `uv tool`, so the system `python` on
    PATH cannot import it. Without this, `python tools/graphify_bridge.py`
    would repair graph.json but fail to regenerate GRAPH_REPORT.md/graph.html,
    leaving stale outputs behind a warning that is easy to miss.
    """
    try:
        import graphify  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("_GRAPHIFY_BRIDGE_REEXEC"):
        print("WARN graphify still not importable after re-exec; "
              "report/html will not be regenerated.")
        return
    marker = GRAPH.parent / ".graphify_python"
    if not marker.exists():
        print(f"WARN graphify not importable and {marker} missing; "
              "run the /graphify skill once to resolve the interpreter.")
        return
    interp = marker.read_text(encoding="utf-8").strip()
    env = {**os.environ, "_GRAPHIFY_BRIDGE_REEXEC": "1"}
    raise SystemExit(subprocess.call([interp, str(Path(__file__).resolve())], env=env))


_reexec_with_graphify_interpreter()

# Source-file prefixes to drop: vendored third-party docs (duplicated across two
# skill dirs) and generated build artifacts. Neither describes this project.
PRUNE_PREFIXES = (
    ".agents/skills/",
    ".claude/skills/",
    "frontend/dist/",
    "frontend/playwright-report/",
    "graphify-out/",
)

# (source, target, relation, confidence, score, provenance)
#
# EXTRACTED = the dependency is literal in the source (a dispatch branch, a
#             config key read by name). INFERRED = a real data-flow coupling
#             that requires reading two files to see.
BRIDGES: list[tuple[str, str, str, str, float, str]] = [
    # -- source type -> the fetcher it dispatches to -----------------------
    # backend/fetcher.py fetch_kpi(): literal `elif source == "..."` chain.
    ("kpi_config_source_fred", "backend_fetcher_fetch_fred_series",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_yfinance", "backend_fetcher_fetch_yfinance",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_tsa", "backend_fetcher_fetch_tsa_throughput",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_scrape_cape", "backend_fetcher_fetch_shiller_cape",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_scrape_gdpnow", "backend_fetcher_fetch_atlanta_gdpnow",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_scrape_nyfed_auto", "backend_fetcher_fetch_nyfed_auto_delinquency",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_derived_ma", "backend_fetcher_fetch_derived_ma",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_derived_ratio", "backend_fetcher_fetch_derived_ratio",
     "dispatched_to", "EXTRACTED", 1.0, "fetcher.fetch_kpi source dispatch"),
    ("kpi_config_source_manual_csv", "app_api_upload_csv",
     "dispatched_to", "EXTRACTED", 1.0, "fetch_kpi skips manual_csv; /api/upload-csv handles it"),

    # -- category -> composite scoring -------------------------------------
    # backend/scorer.py compute_recession_score() groups KPIs by category and
    # weights each by category_weights.
    *[(f"kpi_config_category_{c}", "backend_scorer_compute_recession_score",
       "consumed_by", "EXTRACTED", 1.0, "scorer.compute_recession_score category weighting")
      for c in ("yield_curve", "labor_market", "consumer_health", "housing",
                "financial_stress", "business_activity", "energy", "automotive")],
    ("kpi_config_category_weights", "backend_scorer_compute_recession_score",
     "consumed_by", "EXTRACTED", 1.0, "scorer reads category_weights"),
    # ML features ARE the 8 per-category scores, so a weight change moves the
    # model inputs too. (build_feature_matrix -> compute_recession_score edge
    # already exists from AST; this records the config-level coupling.)
    ("kpi_config_category_weights", "backend_ml_scorer_build_feature_matrix",
     "consumed_by", "INFERRED", 0.95, "ml_scorer features are per-category scores"),

    # -- thresholds / invert -> normalisation and status --------------------
    ("kpi_config_invert_flag", "backend_scorer_normalize_kpi",
     "consumed_by", "EXTRACTED", 1.0, "normalize_kpi branches on invert"),
    ("kpi_config_invert_flag", "app_compute_kpi_status",
     "consumed_by", "EXTRACTED", 1.0, "_compute_kpi_status branches on invert"),

    # -- timing tags -> leading/coincident/diffusion ------------------------
    *[(f"kpi_config_timing_{t}", "backend_leading_kpis_by_timing",
       "consumed_by", "EXTRACTED", 1.0, "leading._kpis_by_timing groups on timing")
      for t in ("leading", "coincident", "lagging")],
    ("kpi_config_timing_leading", "backend_leading_compute_timing_snapshot",
     "consumed_by", "EXTRACTED", 1.0, "leading index restricted to timing:leading"),
    ("kpi_config_timing_leading", "backend_leading_compute_timing_history",
     "consumed_by", "EXTRACTED", 1.0, "leading history restricted to timing:leading"),

    # -- depression severity ------------------------------------------------
    ("kpi_config_severity_module", "backend_severity_compute_severity",
     "consumed_by", "EXTRACTED", 1.0, "severity.compute_severity reads severity: section"),
    *[(f"kpi_config_severity_{c}", "backend_severity_component_subscore",
       "consumed_by", "EXTRACTED", 1.0, "component_subscore interpolates healthy/extreme bounds")
      for c in ("deflation", "bank_credit_contraction", "money_contraction",
                "labor_depth", "persistence")],

    # -- transforms -> fetch pipeline ---------------------------------------
    # These two keys are also change-detection triggers: editing either one
    # makes clear_and_refetch_changed_series() wipe and re-pull that KPI.
    ("kpi_config_compute_pct_change_periods", "backend_fetcher_fetch_kpi",
     "consumed_by", "EXTRACTED", 1.0, "fetch_kpi applies pct_change(periods=N)"),
    ("kpi_config_compute_diff", "backend_fetcher_fetch_kpi",
     "consumed_by", "EXTRACTED", 1.0, "fetch_kpi applies .diff()"),
    ("kpi_config_compute_pct_change_periods", "backend_fetcher_clear_and_refetch_changed_series",
     "triggers_refetch", "EXTRACTED", 1.0, "change detector keys on pct_change_periods"),
    ("kpi_config_compute_diff", "backend_fetcher_clear_and_refetch_changed_series",
     "triggers_refetch", "EXTRACTED", 1.0, "change detector keys on compute_diff"),
    # Transformed values are range-filtered AFTER the transform, so a transform
    # change that moves units silently drops rows unless the range moves too.
    ("kpi_config_compute_pct_change_periods", "backend_fetcher_is_plausible",
     "consumed_by", "INFERRED", 0.95, "_PLAUSIBLE_RANGES applied post-transform"),

    # -- operational config -------------------------------------------------
    ("kpi_config_staleness_window_days", "backend_fetcher_check_staleness",
     "consumed_by", "EXTRACTED", 1.0, "check_staleness honors per-KPI override"),
    ("kpi_config_staleness_window_days", "app_api_kpis",
     "consumed_by", "EXTRACTED", 1.0, "/api/kpis stale flag honors per-KPI override"),
    ("kpi_config_chart_y_domain", "app_api_kpis",
     "consumed_by", "EXTRACTED", 1.0, "chart_y_min/max passed through /api/kpis"),
    ("kpi_config_refresh_schedule", "backend_scheduler_daily_job",
     "consumed_by", "EXTRACTED", 1.0, "scheduler daily refresh"),
    ("kpi_config_alert_defaults", "backend_alerter_check_and_send_alerts",
     "consumed_by", "EXTRACTED", 1.0, "alerter reads warning/critical/cooldown"),
    ("kpi_config_history_years", "backend_fetcher_bootstrap_history",
     "consumed_by", "EXTRACTED", 1.0, "bootstrap_history history window"),
    ("kpi_config_manual_csv_schema", "app_api_upload_csv",
     "consumed_by", "EXTRACTED", 1.0, "/api/upload-csv column schema"),

    # -- the config file itself is read by every loader ---------------------
    *[("kpi_config_single_source_of_truth", tgt,
       "consumed_by", "EXTRACTED", 1.0, "load_config() reads kpi_config.yaml")
      for tgt in ("backend_fetcher_load_config", "backend_scorer_load_config",
                  "app_load_config")],
]


def _norm(path: str) -> str:
    return (path or "").replace("\\", "/")


PROJECT_PREFIXES = ("backend/", "frontend/src/", "frontend/tests/", "tests/",
                    "tools/", "app.py", "cleanup_db.py")


def prune(g: dict) -> int:
    """Drop vendored/generated nodes and any edge touching them.

    Guarded: if a pruned edge has a SURVIVING project-code endpoint, we would be
    deleting real structure, not noise. That is a bug in PRUNE_PREFIXES, so it
    is reported loudly rather than allowed to erode the graph one rebuild at a
    time. (Currently 0 — the vendored .py files link only to each other.)
    """
    sf = {n["id"]: _norm(n.get("source_file")) for n in g["nodes"]}
    doomed = {i for i, s in sf.items() if s.startswith(PRUNE_PREFIXES)}
    if not doomed:
        return 0

    collateral = [
        e for e in g["links"]
        if (e["source"] in doomed) != (e["target"] in doomed)
        and any(sf.get(end, "").startswith(PROJECT_PREFIXES)
                for end in (e["source"], e["target"]) if end not in doomed)
    ]
    if collateral:
        print(f"  WARN pruning would delete {len(collateral)} edge(s) attached to "
              f"surviving project code - PRUNE_PREFIXES is too broad:")
        for e in collateral[:5]:
            print(f"    [{e.get('_origin','?')}] {e['source']} -> {e['target']}")

    g["nodes"] = [n for n in g["nodes"] if n["id"] not in doomed]
    g["links"] = [
        e for e in g["links"]
        if e["source"] not in doomed and e["target"] not in doomed
    ]
    g["hyperedges"] = [
        h for h in g.get("hyperedges", [])
        if not any(n in doomed for n in h.get("nodes", []))
    ]
    return len(doomed)


def drop_dangling(g: dict) -> int:
    """Remove edges whose endpoints no longer exist (e.g. after a rename)."""
    ids = {n["id"] for n in g["nodes"]}
    before = len(g["links"])
    g["links"] = [e for e in g["links"] if e["source"] in ids and e["target"] in ids]
    return before - len(g["links"])


def main() -> int:
    if not GRAPH.exists():
        print(f"ERROR: {GRAPH} not found - build the graph first.", file=sys.stderr)
        return 1

    g = json.loads(GRAPH.read_text(encoding="utf-8"))
    g.setdefault("hyperedges", [])

    pruned = prune(g)
    if pruned:
        print(f"pruned {pruned} vendored/generated nodes")

    ids = {n["id"] for n in g["nodes"]}
    existing = {(e["source"], e["target"], e.get("relation")) for e in g["links"]}

    added = skipped = missing = 0
    for src, tgt, rel, conf, score, note in BRIDGES:
        if src not in ids or tgt not in ids:
            side = "source" if src not in ids else "target"
            print(f"  WARN missing {side}: {src} -> {tgt}  ({note})")
            missing += 1
            continue
        if (src, tgt, rel) in existing:
            skipped += 1
            continue
        g["links"].append({
            "source": src, "target": tgt, "relation": rel,
            "confidence": conf, "confidence_score": score,
            "source_file": "kpi_config.yaml", "source_location": None,
            "weight": 1.0, "_origin": "bridge", "_note": note,
        })
        existing.add((src, tgt, rel))
        added += 1

    dropped = drop_dangling(g)
    if dropped:
        print(f"dropped {dropped} dangling edges (renamed/removed symbols)")

    GRAPH.write_text(json.dumps(g, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"bridge: +{added} edges, {skipped} already present, {missing} missing endpoints")
    print(f"graph now: {len(g['nodes'])} nodes, {len(g['links'])} edges")
    if missing:
        print("NOTE: missing endpoints mean a rename happened - update BRIDGES above.")

    regenerate_outputs(g)
    return 0


def regenerate_outputs(g: dict) -> None:
    """Rebuild GRAPH_REPORT.md and graph.html from the repaired graph.

    `graphify update` writes both BEFORE this script runs, so without this they
    describe the un-pruned, un-bridged graph. Failures here are non-fatal — the
    graph itself is already saved.
    """
    try:
        import collections
        import networkx as nx
        from graphify.analyze import god_nodes, suggest_questions, surprising_connections
        from graphify.cluster import score_all
        from graphify.detect import detect
        from graphify.export import to_html
        from graphify.report import generate

        root = GRAPH.parent.parent
        G = nx.DiGraph()
        for n in g["nodes"]:
            G.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
        for e in g["links"]:
            G.add_edge(e["source"], e["target"],
                       **{k: v for k, v in e.items() if k not in ("source", "target")})

        communities = collections.defaultdict(list)
        for n in g["nodes"]:
            communities[n.get("community", 0)].append(n["id"])
        communities = dict(communities)

        labels_path = GRAPH.parent / ".graphify_labels.json"
        labels = {}
        if labels_path.exists():
            labels = {int(k): v for k, v in
                      json.loads(labels_path.read_text(encoding="utf-8")).items()}
        for cid in communities:
            labels.setdefault(cid, f"Community {cid}")

        cost_path = GRAPH.parent / "cost.json"
        cost = json.loads(cost_path.read_text(encoding="utf-8")) if cost_path.exists() else {}
        tokens = {"input": cost.get("total_input_tokens", 0),
                  "output": cost.get("total_output_tokens", 0)}

        gods = god_nodes(G)
        surprises = surprising_connections(G, communities)
        report = generate(G, communities, score_all(G, communities), labels, gods,
                          surprises, detect(root), tokens, str(root),
                          suggested_questions=suggest_questions(G, communities, labels))
        (GRAPH.parent / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
        to_html(G, communities, str(GRAPH.parent / "graph.html"), community_labels=labels)
        print("regenerated GRAPH_REPORT.md and graph.html")
    except Exception as exc:  # noqa: BLE001 - graph.json is already safe on disk
        print(f"WARN could not regenerate report/html ({type(exc).__name__}: {exc})")
        print("     graph.json is correct; run `graphify export html` manually.")


if __name__ == "__main__":
    raise SystemExit(main())
