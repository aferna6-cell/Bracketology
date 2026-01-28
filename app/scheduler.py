"""
Scheduler for automatic bracket updates.

- Normal season: updates twice daily (every 12 hours)
- March: updates every hour
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import UPDATE_INTERVAL_NORMAL_MINUTES, UPDATE_INTERVAL_MARCH_MINUTES
from app.update import run_update

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def get_update_interval():
    """Return update interval in minutes based on current month."""
    now = datetime.now()
    if now.month == 3:
        return UPDATE_INTERVAL_MARCH_MINUTES
    return UPDATE_INTERVAL_NORMAL_MINUTES


def start_scheduler():
    """Start the background scheduler."""
    interval = get_update_interval()
    logger.info(f"Starting scheduler with {interval}-minute interval")

    scheduler.add_job(
        func=run_update,
        trigger=IntervalTrigger(minutes=interval),
        id="bracket_update",
        name="Update bracket projection",
        replace_existing=True,
    )

    # Also check monthly if we need to change the interval (for March)
    scheduler.add_job(
        func=_check_interval,
        trigger=IntervalTrigger(hours=6),
        id="interval_check",
        name="Check if update interval needs changing",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")


def _check_interval():
    """Adjust update frequency when March starts."""
    new_interval = get_update_interval()
    job = scheduler.get_job("bracket_update")
    if job:
        current_interval = job.trigger.interval.total_seconds() / 60
        if abs(current_interval - new_interval) > 1:
            logger.info(f"Adjusting update interval from {current_interval}m to {new_interval}m")
            scheduler.reschedule_job(
                "bracket_update",
                trigger=IntervalTrigger(minutes=new_interval),
            )


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
