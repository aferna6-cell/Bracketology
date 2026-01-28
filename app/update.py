"""
Core update loop that pulls data, recomputes ratings, and generates a new bracket.
"""

import logging
from datetime import datetime

from app.data_ingestion import build_team_database, load_teams_from_db
from app.bracket_generator import build_bracket, compute_changes
from app.models import save_snapshot, get_latest_snapshot

logger = logging.getLogger(__name__)

# Module-level cache of the latest bracket dict
_latest_bracket = None


def run_update() -> dict:
    """
    Execute the full update pipeline:
    1. Pull scores + update team results
    2. Recompute ratings
    3. Refresh bracket projection + lock/bubble labels
    4. Save snapshot with change diff
    """
    global _latest_bracket

    logger.info(f"Starting bracket update at {datetime.now()}")

    try:
        # Step 1 + 2: Pull data and compute ratings (done inside build_team_database)
        teams = build_team_database()
        logger.info(f"Loaded {len(teams)} teams")

        if not teams:
            logger.warning("No teams loaded, attempting to use cached data")
            teams = load_teams_from_db()

        if not teams:
            logger.error("No team data available")
            return {}

        # Step 3: Generate bracket
        bracket = build_bracket(teams)

        # Step 4: Compute changes from previous snapshot
        old_snapshot = get_latest_snapshot()
        changes = compute_changes(old_snapshot, bracket)

        # Step 5: Save snapshot
        save_snapshot(bracket, changes)

        _latest_bracket = bracket.to_dict()
        _latest_bracket["changes"] = changes

        change_count = len(changes)
        logger.info(f"Bracket update complete. {change_count} changes detected.")

        return _latest_bracket

    except Exception as e:
        logger.error(f"Error during bracket update: {e}", exc_info=True)
        return {}


def get_current_bracket() -> dict:
    """Get the current bracket (from cache or DB)."""
    global _latest_bracket

    if _latest_bracket:
        return _latest_bracket

    snapshot = get_latest_snapshot()
    if snapshot:
        _latest_bracket = snapshot["bracket"]
        _latest_bracket["changes"] = snapshot["changes"]
        return _latest_bracket

    return {}
