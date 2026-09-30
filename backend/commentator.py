"""AI-powered commentary generator for KPI categories and global outlook.

Uses the Anthropic Claude API to produce concise, analyst-style narratives
based on current KPI values, statuses, trends, and cross-category dynamics.
"""

import os
import logging
from datetime import date as date_type
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client initialisation (lazy, so missing key is a soft failure at import)
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment.")
        try:
            import anthropic
            _client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise RuntimeError(
                "The 'anthropic' package is not installed. "
                "Run: pip install anthropic"
            )
    return _client


def is_available() -> bool:
    """Return True if the Anthropic API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_model() -> str:
    return os.environ.get("ANTHROPIC_AI_MODEL", "claude-sonnet-4-6")


# ---------------------------------------------------------------------------
# Band helper
# ---------------------------------------------------------------------------

def _band(score: float) -> str:
    if score >= 75:
        return "CRITICAL"
    if score >= 50:
        return "HIGH"
    if score >= 25:
        return "ELEVATED"
    return "LOW"


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_CATEGORY_LABELS = {
    "yield_curve": "Yield Curve & Rates",
    "labor_market": "Labor Market",
    "consumer_health": "Consumer Health",
    "housing": "Housing Market",
    "financial_stress": "Financial Stress",
    "business_activity": "Business Activity",
    "energy": "Energy Market",
    "automotive": "Automotive Market",
    "global": "Global Outlook",
}


def _status_emoji(status: str) -> str:
    return {"OK": "🟢", "WARNING": "🟡", "DANGER": "🔴", "NO_DATA": "⚪"}.get(status, "⚪")


def build_category_prompt(
    category_id: str,
    kpis: list,
    category_score: float,
    all_category_scores: dict,
    as_of_date: date_type,
    monitor_only: bool = False,
    label: Optional[str] = None,
) -> str:
    """Build the prompt for a single-category AI commentary.

    monitor_only: the category is shown on the dashboard but is NOT part of the
    Recession Risk Score (kpi_config `monitor_categories:`), so it has no
    category score and the prompt must not present one.
    """
    label = label or _CATEGORY_LABELS.get(category_id, category_id)
    band = _band(category_score)
    score_line = (
        "Category Risk Score: none. This is a monitor-only category and is NOT part of the "
        "Recession Risk Score; it tracks AI-bubble exposure and whether that bubble is breaking. "
        "Do not describe these indicators as driving the recession score."
        if monitor_only else
        f"Category Risk Score: {category_score:.0f}/100 ({band})"
    )

    # KPI rows for this category
    cat_kpis = [k for k in kpis if k.get("category") == category_id]
    # Sort by sub_score descending so the most concerning are first
    cat_kpis.sort(key=lambda k: k.get("sub_score") or 0, reverse=True)

    kpi_rows = []
    for k in cat_kpis:
        val = k.get("latest_value")
        val_str = f"{val:.3g}" if val is not None else "N/A"
        unit = k.get("unit", "")
        status = k.get("status", "NO_DATA")
        chg_abs = k.get("change_abs")
        chg_pct = k.get("change_pct")
        chg_str = ""
        if chg_abs is not None:
            sign = "+" if chg_abs >= 0 else ""
            chg_str = f"{sign}{chg_abs:.3g}"
            if chg_pct is not None:
                chg_str += f" ({sign}{chg_pct:.2f}%)"
        fcast_status = k.get("forecast_status", "")
        fcast_str = fcast_status if fcast_status and fcast_status != "NO_DATA" else ""
        kpi_rows.append(
            f"  {_status_emoji(status)} {k['name']}: {val_str} {unit} "
            f"| chg {chg_str or 'N/A'} | 3M forecast: {fcast_str or 'N/A'}"
        )

    kpi_section = "\n".join(kpi_rows) if kpi_rows else "  (no data available)"

    # Cross-category context — other elevated/danger categories
    other_alerts = []
    for cat_id, score in sorted(all_category_scores.items(), key=lambda x: -x[1]):
        if cat_id == category_id:
            continue
        b = _band(score)
        if b in ("HIGH", "CRITICAL", "ELEVATED"):
            other_alerts.append(f"  - {_CATEGORY_LABELS.get(cat_id, cat_id)}: {score:.0f}/100 ({b})")
    cross_section = "\n".join(other_alerts) if other_alerts else "  (all other categories in LOW band)"

    return f"""You are a senior US macroeconomic analyst writing a brief dashboard commentary for a recession risk monitoring tool.

Date: {as_of_date.strftime('%B %d, %Y')}
Category: {label}
{score_line}

Current indicator readings:
{kpi_section}

Other categories showing stress:
{cross_section}

Write a concise analyst commentary (150–200 words) for this category. Your commentary must:
1. Summarise the current state of this economic segment in plain English.
2. Identify which 1–3 indicators are most concerning and explain why they matter.
3. Note how indicators within this category are confirming or contradicting each other.
4. Call out any cross-category dynamics — e.g. how stress here might amplify or be amplified by other categories.
5. End with one specific thing to watch in the next 1–3 months.

Tone: professional, direct, data-grounded. Do not use bullet points — write flowing prose.
Do not repeat the category name or score in the opening sentence."""


def build_global_prompt(
    all_kpis: list,
    category_scores: dict,
    overall_score: float,
    band: str,
    as_of_date: date_type,
) -> str:
    """Build the prompt for the global market outlook commentary."""
    # Category summary sorted worst → best
    cat_rows = []
    for cat_id, score in sorted(category_scores.items(), key=lambda x: -x[1]):
        b = _band(score)
        cat_rows.append(f"  {_status_emoji(b.replace('LOW','OK').replace('ELEVATED','WARNING').replace('HIGH','WARNING').replace('CRITICAL','DANGER'))} "
                        f"{_CATEGORY_LABELS.get(cat_id, cat_id)}: {score:.0f}/100 ({b})")
    cat_section = "\n".join(cat_rows)

    # Top 6 highest-risk KPIs
    # Monitor-only KPIs (ai_bubble) are not recession-score drivers — keep them out.
    flagged = [k for k in all_kpis if k.get("sub_score") is not None and k.get("status") != "NO_DATA"
               and k.get("in_composite", True)]
    flagged.sort(key=lambda k: k.get("sub_score") or 0, reverse=True)
    top_kpis = flagged[:6]
    kpi_rows = []
    for k in top_kpis:
        val = k.get("latest_value")
        val_str = f"{val:.3g}" if val is not None else "N/A"
        status = k.get("status", "NO_DATA")
        kpi_rows.append(
            f"  {_status_emoji(status)} {k['name']} ({k.get('category','')}): "
            f"{val_str} {k.get('unit','')} — sub-score {(k.get('sub_score') or 0)*100:.0f}/100"
        )
    top_section = "\n".join(kpi_rows) if kpi_rows else "  (insufficient data)"

    return f"""You are a senior US macroeconomic strategist writing the headline market outlook commentary for a recession risk dashboard.

Date: {as_of_date.strftime('%B %d, %Y')}
Overall Recession Risk Score: {overall_score:.0f}/100 ({band})

Category breakdown (worst to best):
{cat_section}

Top risk signals across all categories:
{top_section}

Write a comprehensive market outlook commentary (250–300 words). Your commentary must:
1. Open with a clear, direct assessment of the current US macro environment.
2. Identify the 2–3 most important inter-category dynamics (e.g. how yield curve inversion is feeding into credit spreads, or how labour weakness is compounding consumer spending risk).
3. Explain what the current score level historically implies about recession probability over the next 6–12 months.
4. Highlight any conflicting signals — indicators that are surprisingly resilient despite broader stress, or vice versa.
5. Close with 2–3 specific things investors and analysts should monitor closely in the next quarter.
6. After the main commentary, add a short section titled "Personal Finance Outlook" with exactly 2 concise, actionable tips (1–2 sentences each): one specifically for 401(k) positioning and one for employee stock options — both grounded in the current economic environment above. Keep this section brief and practical.

Tone: authoritative, clear, suitable for a senior analyst audience. Write flowing prose paragraphs for the main commentary — no bullet points or headers.
Do not start with "As of" or "The overall recession risk score is"."""


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def call_claude(prompt: str) -> str:
    """Send prompt to Claude and return the text response."""
    client = _get_client()
    model = _get_model()
    logger.info("Calling Claude model %s for AI commentary (prompt len=%d)", model, len(prompt))

    message = client.messages.create(
        model=model,
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    logger.info("Claude commentary generated (%d chars)", len(text))
    return text
