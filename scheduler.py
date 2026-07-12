"""
Wraps APScheduler so app.py can start/stop background updates with a
single call. Kept separate from app.py so the scraping cadence can be
reasoned about (and tested) independently of Flask routing.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler

import config
import scraper

logger = logging.getLogger("scheduler")

_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        scraper.run_scraper,
        "interval",
        minutes=config.UPDATE_INTERVAL_MINUTES,
        id="outage_scraper",
        next_run_time=None,  # first run is triggered manually at startup, see app.py
    )
    _scheduler.start()
    logger.info(
        f"Scheduler started -- scraping every {config.UPDATE_INTERVAL_MINUTES} minutes"
    )
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
