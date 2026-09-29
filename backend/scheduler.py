"""APScheduler setup for daily automatic data refresh."""

import logging
import os

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _daily_job():
    from backend.fetcher import fetch_all_kpis
    from backend.scorer import compute_recession_score
    from backend.alerter import check_and_send_alerts

    logger.info("Scheduler: starting daily refresh")
    fetch_all_kpis(incremental=True)
    result = compute_recession_score()
    check_and_send_alerts(result["score"], result["band"])
    logger.info("Scheduler: daily refresh complete — score=%.1f (%s)",
                result["score"], result["band"])


def start_scheduler(refresh_time: str = "07:00") -> BackgroundScheduler:
    """
    Start the APScheduler background scheduler.

    Args:
        refresh_time: "HH:MM" local time for daily refresh (default "07:00")
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    hour, minute = refresh_time.split(":")
    from tzlocal import get_localzone
    _scheduler = BackgroundScheduler(timezone=get_localzone())
    _scheduler.add_job(
        _daily_job,
        trigger=CronTrigger(hour=int(hour), minute=int(minute)),
        id="daily_refresh",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info("Scheduler started — daily refresh at %s local time", refresh_time)
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def next_run_time() -> str:
    global _scheduler
    if _scheduler:
        job = _scheduler.get_job("daily_refresh")
        if job and job.next_run_time:
            return job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")
    return "unknown"
