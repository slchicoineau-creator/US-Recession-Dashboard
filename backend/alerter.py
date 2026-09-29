"""
Email alert dispatch for the Recession Risk Dashboard.

Sends emails via SMTP/STARTTLS (e.g. Gmail App Password) when the
Recession Risk Score crosses configurable thresholds.
"""

import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from backend.models import AlertLog, AppConfig, get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_config(key: str, default: str) -> str:
    session = get_session()
    try:
        row = session.get(AppConfig, key)
        return row.value if row else default
    finally:
        session.close()


def get_warning_threshold() -> float:
    return float(_get_config("warning_threshold", "50"))


def get_critical_threshold() -> float:
    return float(_get_config("critical_threshold", "75"))


def alerts_enabled() -> bool:
    return _get_config("alerts_enabled", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Cooldown check
# ---------------------------------------------------------------------------

def _last_alert_time(alert_type: str) -> Optional[datetime]:
    session = get_session()
    try:
        row = (
            session.query(AlertLog)
            .filter_by(alert_type=alert_type)
            .order_by(AlertLog.sent_at.desc())
            .first()
        )
        return row.sent_at if row else None
    finally:
        session.close()


def _in_cooldown(alert_type: str, cooldown_hours: int = 24) -> bool:
    last = _last_alert_time(alert_type)
    if last is None:
        return False
    return datetime.utcnow() - last < timedelta(hours=cooldown_hours)


def _log_alert(alert_type: str, score: float) -> None:
    session = get_session()
    try:
        session.add(AlertLog(alert_type=alert_type, score=score, sent_at=datetime.utcnow()))
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Failed to log alert: %s", exc)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Email builder & sender
# ---------------------------------------------------------------------------

def _build_email_body(score: float, band: str, top_kpis: list[dict]) -> str:
    kpi_rows = ""
    for k in top_kpis[:3]:
        kpi_rows += (
            f"  • {k['name']}: {k['value']:.2f} "
            f"(contribution: {k['weighted_contribution']:.1f} pts)\n"
        )
    band_color = {"LOW": "green", "ELEVATED": "goldenrod",
                  "HIGH": "darkorange", "CRITICAL": "crimson"}.get(band, "black")

    html = f"""
<html><body style="font-family: Arial, sans-serif; color: #222;">
<h2>US Economy Recession Risk Alert</h2>
<p>The Recession Risk Score has entered the
<strong style="color:{band_color};">{band}</strong> zone.</p>

<table style="border-collapse:collapse; width:320px;">
  <tr>
    <td style="padding:8px; background:#f5f5f5; font-weight:bold;">Current Score</td>
    <td style="padding:8px; font-size:1.5em; color:{band_color};"><strong>{score:.1f} / 100</strong></td>
  </tr>
  <tr>
    <td style="padding:8px; background:#f5f5f5; font-weight:bold;">Risk Band</td>
    <td style="padding:8px; color:{band_color};"><strong>{band}</strong></td>
  </tr>
</table>

<h3>Top Contributing Indicators</h3>
<ul>
{''.join(f"<li><b>{k['name']}</b>: {k['value']:.2f} ({k['weighted_contribution']:.1f} pts)</li>" for k in top_kpis[:3])}
</ul>

<p>
  <a href="http://localhost:5000" style="background:#1a73e8; color:#fff;
     padding:10px 18px; text-decoration:none; border-radius:4px;">
    Open Dashboard
  </a>
</p>
<hr/>
<small>This alert was sent by your local US Economy KPI Dashboard.<br/>
Alerts have a 24-hour cooldown to prevent alert fatigue.</small>
</body></html>
"""
    return html


def send_alert(score: float, band: str, alert_type: str, top_kpis: list[dict]) -> bool:
    """Send an alert email. Returns True if sent successfully."""
    email_from = os.getenv("ALERT_EMAIL_FROM", "")
    email_to = os.getenv("ALERT_EMAIL_TO", "")
    email_password = os.getenv("ALERT_EMAIL_PASSWORD", "")

    if not all([email_from, email_to, email_password]):
        logger.warning("Email credentials not configured — skipping alert")
        return False

    subject = f"[Recession Alert] Risk Score {score:.1f} — {band}"
    body_html = _build_email_body(score, band, top_kpis)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(email_from, email_password)
            smtp.sendmail(email_from, email_to, msg.as_string())
        logger.info("Alert email sent: %s (score=%.1f)", alert_type, score)
        return True
    except Exception as exc:
        logger.error("Failed to send alert email: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def check_and_send_alerts(score: float, band: str, top_kpis: list[dict] | None = None) -> None:
    """
    Evaluate thresholds and send alerts if warranted.
    Called after every score computation.
    """
    if not alerts_enabled():
        return

    if top_kpis is None:
        top_kpis = []

    warn_thresh = get_warning_threshold()
    crit_thresh = get_critical_threshold()

    if score >= crit_thresh and not _in_cooldown("critical"):
        sent = send_alert(score, band, "critical", top_kpis)
        if sent:
            _log_alert("critical", score)

    elif score >= warn_thresh and not _in_cooldown("warning"):
        sent = send_alert(score, band, "warning", top_kpis)
        if sent:
            _log_alert("warning", score)
