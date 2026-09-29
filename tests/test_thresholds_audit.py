"""Threshold-vs-data sanity sweep against the live DB.

Catches the unit-mismatch bug class CLAUDE.md repeatedly documents:
  - jolts: thresholds were 7.0/5.5 (millions) when FRED returns thousands
  - t10y2y: thresholds were 0/-50 when FRED returns ppt
  - ig_spread / hy_spread: thresholds in bps but FRED returns %
  - vehicle_days_supply: catching all post-COVID values

Logic per KPI: query the last 5 years of values; if min/max never crosses
the threshold, OR the threshold is so low that values always cross it,
the threshold is suspect. We mark these as warnings (not failures) so the
test acts as a continuous audit.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pytest

from backend.models import KpiData


def _get_value_range(session, kpi_id: str, since: date) -> tuple[Optional[float], Optional[float], int]:
    rows = (
        session.query(KpiData.value)
        .filter(KpiData.kpi_id == kpi_id, KpiData.date >= since, KpiData.value.isnot(None))
        .all()
    )
    if not rows:
        return None, None, 0
    vals = [r[0] for r in rows]
    return min(vals), max(vals), len(vals)


def _classify(kpi: dict, vmin: float, vmax: float) -> tuple[str, str]:
    """Return (verdict, reason). verdict ∈ OK | NEVER_TRIGGERS | ALWAYS_TRIGGERS | INVERTED_BAD."""
    warn = kpi.get("warning_threshold")
    danger = kpi.get("danger_threshold")
    invert = kpi.get("invert", False)
    if warn is None or danger is None:
        return "OK", "no thresholds (context only)"

    if invert:
        # warn > danger; lower value = worse
        if vmin > warn:
            return "NEVER_TRIGGERS", f"min({vmin:.4g}) > warn({warn}) — never even WARNING"
        if vmax < danger:
            return "ALWAYS_TRIGGERS", f"max({vmax:.4g}) < danger({danger}) — always DANGER"
        if warn < danger:
            return "INVERTED_BAD", f"warn({warn}) must be > danger({danger}) for invert"
    else:
        if vmax < warn:
            return "NEVER_TRIGGERS", f"max({vmax:.4g}) < warn({warn}) — never even WARNING"
        if vmin > danger:
            return "ALWAYS_TRIGGERS", f"min({vmin:.4g}) > danger({danger}) — always DANGER"
        if warn > danger:
            return "INVERTED_BAD", f"warn({warn}) must be < danger({danger}) for non-invert"
    return "OK", ""


def test_threshold_audit_all_kpis(real_session, kpi_config, tmp_path):
    """Audit every KPI; produce a markdown report. Test PASSES even if there are
    findings — the report is the deliverable. A separate test below FAILS on
    INVERTED_BAD only (which is unambiguously wrong)."""
    since = date.today() - timedelta(days=5 * 365)
    findings = []
    skipped = 0

    for kpi in kpi_config["kpis"]:
        kid = kpi["id"]
        if kpi.get("source") == "manual_csv":
            skipped += 1
            continue
        vmin, vmax, n = _get_value_range(real_session, kid, since)
        if n == 0:
            findings.append((kid, "NO_DATA_5Y", f"0 rows in last 5y", kpi))
            continue
        if vmin is None:
            continue
        verdict, reason = _classify(kpi, vmin, vmax)
        if verdict != "OK":
            findings.append((kid, verdict, f"n={n} {reason}", kpi))

    report = ["# Threshold Audit Report", "", f"Generated: {date.today()}", ""]
    report.append(f"Total KPIs audited: {len(kpi_config['kpis']) - skipped} (skipped {skipped} manual_csv)")
    report.append(f"Findings: {len(findings)}")
    report.append("")
    if findings:
        report.append("| KPI | Verdict | Detail | warn | danger | invert |")
        report.append("|-----|---------|--------|------|--------|--------|")
        for kid, verdict, detail, kpi in findings:
            report.append(
                f"| {kid} | {verdict} | {detail} | "
                f"{kpi.get('warning_threshold')} | {kpi.get('danger_threshold')} | "
                f"{kpi.get('invert', False)} |"
            )
    report_path = tmp_path / "threshold_audit.md"
    report_path.write_text("\n".join(report), encoding="utf-8")
    print(f"\n\nThreshold audit report:\n{chr(10).join(report)}\n")


def test_no_inverted_bad_thresholds(real_session, kpi_config):
    """Hard fail: thresholds must be ordered correctly per `invert` flag."""
    bad = []
    for kpi in kpi_config["kpis"]:
        warn = kpi.get("warning_threshold")
        danger = kpi.get("danger_threshold")
        if warn is None or danger is None:
            continue
        if kpi.get("invert", False):
            if warn <= danger:
                bad.append(f"{kpi['id']}: invert=True but warn({warn}) <= danger({danger})")
        else:
            if warn >= danger:
                bad.append(f"{kpi['id']}: invert=False but warn({warn}) >= danger({danger})")
    assert not bad, "Threshold ordering violations:\n" + "\n".join(bad)


def test_no_kpi_always_at_danger_with_recent_data(real_session, kpi_config):
    """Soft check: if a KPI has 12+ months of data and is ALWAYS in DANGER, the
    threshold is almost certainly miscalibrated. This is the smoke alarm class."""
    one_year_ago = date.today() - timedelta(days=365)
    suspect = []
    for kpi in kpi_config["kpis"]:
        if kpi.get("source") == "manual_csv":
            continue
        kid = kpi["id"]
        warn = kpi.get("warning_threshold")
        danger = kpi.get("danger_threshold")
        if warn is None or danger is None:
            continue
        vmin, vmax, n = _get_value_range(real_session, kid, one_year_ago)
        if n < 12:
            continue
        invert = kpi.get("invert", False)
        if invert:
            if vmax < danger:
                suspect.append(f"{kid}: max({vmax}) < danger({danger}) over last year (n={n})")
        else:
            if vmin > danger:
                suspect.append(f"{kid}: min({vmin}) > danger({danger}) over last year (n={n})")
    if suspect:
        # Don't fail — just print loudly so it shows in the report
        print("\nKPIs always in DANGER over past year (review thresholds):")
        for s in suspect:
            print(f"  {s}")
