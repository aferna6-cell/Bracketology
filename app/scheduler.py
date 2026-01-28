"""
Scheduler for automatic bracket updates.

- Normal season: once daily at 8:00 AM
- March: every hour
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.update import run_update

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def start_scheduler():
    """Start the background scheduler."""
    now = datetime.now()

    if now.month == 3:
        # March: update every hour
        logger.info("March mode: scheduling updates every hour")
        scheduler.add_job(
            func=run_update,
            trigger=IntervalTrigger(hours=1),
            id="bracket_update",
            name="Update bracket projection (hourly)",
            replace_existing=True,
        )
    else:
        # Normal season: once daily at 8:00 AM
        logger.info("Normal mode: scheduling daily update at 8:00 AM")
        scheduler.add_job(
            func=run_update,
            trigger=CronTrigger(hour=8, minute=0),
            id="bracket_update",
            name="Update bracket projection (daily 8am)",
            replace_existing=True,
        )

    # Check on the 1st of each month if we need to switch modes
    scheduler.add_job(
        func=_check_mode,
        trigger=CronTrigger(day=1, hour=0, minute=5),
        id="mode_check",
        name="Check if schedule mode needs changing",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")


def _check_mode():
    """Switch between daily and hourly mode when March starts/ends."""
    now = datetime.now()
    job = scheduler.get_job("bracket_update")
    if not job:
        return

    if now.month == 3:
        logger.info("Switching to March hourly mode")
        scheduler.reschedule_job(
            "bracket_update",
            trigger=IntervalTrigger(hours=1),
        )
    else:
        logger.info("Switching to daily 8am mode")
        scheduler.reschedule_job(
            "bracket_update",
            trigger=CronTrigger(hour=8, minute=0),
        )


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
