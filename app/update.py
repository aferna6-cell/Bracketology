"""Core update loop that pulls data, recomputes ratings, and generates a new bracket."""

import logging
import traceback
from datetime import datetime

from app.data_ingestion import build_team_database, load_teams_from_db
from app.bracket_generator import build_bracket, compute_changes
from app.models import save_snapshot, get_latest_snapshot

logger = logging.getLogger(__name__)

_latest_bracket = None
_all_teams_cache = []  # cached for what-if and team detail lookups


def run_update() -> dict:
    """
    Execute the full update pipeline.
    Returns dict with bracket data, changes, and any errors.
    """
    global _latest_bracket, _all_teams_cache

    logger.info(f"Starting bracket update at {datetime.now()}")
    errors = []

    try:
        result = build_team_database()
        if isinstance(result, tuple):
            teams, build_errors = result
            errors.extend(build_errors)
        else:
            teams = result

        logger.info(f"Loaded {len(teams)} teams")

        if not teams:
            logger.warning("No teams loaded, attempting to use cached data")
            teams = load_teams_from_db()

        if not teams:
            errors.append("No team data available from ESPN or cache.")
            return {"status": "error", "errors": errors}

        _all_teams_cache = teams

        bracket = build_bracket(teams)

        old_snapshot = get_latest_snapshot()
        changes = compute_changes(old_snapshot, bracket)

        save_snapshot(bracket, changes)

        _latest_bracket = bracket.to_dict()
        _latest_bracket["changes"] = changes

        logger.info(f"Bracket update complete. {len(changes)} changes detected.")

        return {"status": "ok", "bracket": _latest_bracket, "changes": changes, "errors": errors}

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Error during bracket update: {e}\n{tb}")
        errors.append(f"Internal error: {str(e)}")
        return {"status": "error", "errors": errors}


def get_current_bracket() -> dict:
    global _latest_bracket
    if _latest_bracket:
        return _latest_bracket
    snapshot = get_latest_snapshot()
    if snapshot:
        _latest_bracket = snapshot["bracket"]
        _latest_bracket["changes"] = snapshot["changes"]
        return _latest_bracket
    return {}


def get_all_teams() -> list:
    """Get all teams (for team detail lookups and what-if)."""
    global _all_teams_cache
    if _all_teams_cache:
        return _all_teams_cache
    _all_teams_cache = load_teams_from_db()
    return _all_teams_cache
