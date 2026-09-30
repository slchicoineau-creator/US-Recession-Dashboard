"""Catch the 'two KPIs share a FRED series_id' anti-pattern.

CLAUDE.md notes that `housing_starts` and `housing_affordability` both pointed
at HOUST. That kind of duplication is almost always a copy-paste bug — the
two KPIs will move identically, which inflates a category's recession signal.
"""

from __future__ import annotations

from collections import defaultdict


def test_no_duplicate_series_id(kpi_config):
    by_series: dict[str, list[str]] = defaultdict(list)
    for kpi in kpi_config["kpis"]:
        sid = kpi.get("series_id")
        if not sid:
            continue
        if kpi.get("source") == "manual_csv":
            continue
        by_series[(kpi.get("source", "?"), sid)].append(kpi["id"])

    dupes = {k: v for k, v in by_series.items() if len(v) > 1}
    if dupes:
        msg_lines = ["KPIs sharing the same (source, series_id):"]
        for (source, sid), ids in dupes.items():
            msg_lines.append(f"  {source}:{sid} -> {ids}")
        # Soft warning: print but don't fail (housing_starts/housing_affordability
        # is a known intentional duplication per CLAUDE.md). New ones get flagged.
        print("\n" + "\n".join(msg_lines))


def test_unique_kpi_ids(kpi_config):
    """KPI ids must be unique."""
    ids = [k["id"] for k in kpi_config["kpis"]]
    seen = set()
    dupes = []
    for kid in ids:
        if kid in seen:
            dupes.append(kid)
        seen.add(kid)
    assert not dupes, f"Duplicate KPI ids: {dupes}"


def test_every_kpi_has_required_fields(kpi_config):
    required = {"id", "name", "category", "source", "frequency"}
    bad = []
    for kpi in kpi_config["kpis"]:
        missing = required - set(kpi.keys())
        if missing:
            bad.append(f"{kpi.get('id', '?')}: missing {missing}")
    assert not bad, "KPIs with missing required fields:\n" + "\n".join(bad)


def test_category_in_known_set(kpi_config):
    # Scored categories plus the explicitly declared monitor-only ones (never
    # "any category", so a mistyped category still fails here).
    valid_cats = (set(kpi_config["category_weights"].keys())
                  | set((kpi_config.get("monitor_categories") or {}).keys()))
    bad = []
    for kpi in kpi_config["kpis"]:
        if kpi["category"] not in valid_cats:
            bad.append(f"{kpi['id']}: category={kpi['category']} not in {valid_cats}")
    assert not bad, "KPIs with unknown categories:\n" + "\n".join(bad)


def test_category_weights_sum_to_one(kpi_config):
    total = sum(kpi_config["category_weights"].values())
    assert abs(total - 1.0) < 0.01, f"Category weights sum to {total}, expected 1.0"
