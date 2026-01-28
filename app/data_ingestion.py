"""Data ingestion from ESPN APIs."""

import logging
import sqlite3
from datetime import datetime

import requests

from app.config import (
    DATABASE_PATH,
    ESPN_SCOREBOARD_URL,
    ESPN_TEAMS_URL,
)
from app.models import Team

logger = logging.getLogger(__name__)


# ESPN conference group IDs
CONFERENCE_IDS = {
    "ACC": 2, "American": 62, "Atlantic 10": 3, "Big 12": 8,
    "Big East": 4, "Big Ten": 7, "Big West": 5, "CAA": 10,
    "C-USA": 11, "Horizon": 45, "Ivy": 12, "MAAC": 13, "MAC": 14,
    "MEAC": 16, "Missouri Valley": 18, "Mountain West": 44, "NEC": 19,
    "OVC": 20, "Pac-12": 21, "Patriot": 22, "SEC": 23, "SoCon": 24,
    "Southland": 25, "SWAC": 26, "Summit": 49, "Sun Belt": 27,
    "WAC": 30, "WCC": 29, "America East": 1, "ASUN": 46,
    "Big Sky": 6, "Big South": 9,
}


def _get_stat(stats_list: list, stat_type: str, default=None):
    """Extract a stat value from ESPN's stats array by its 'type' field."""
    for s in stats_list:
        if s.get("type") == stat_type:
            return s.get("displayValue", s.get("value", default))
    return default


def _parse_record(record_str: str) -> tuple[int, int]:
    """Parse a record string like '20-5' into (wins, losses)."""
    if not record_str or not isinstance(record_str, str) or "-" not in record_str:
        return 0, 0
    try:
        parts = record_str.split("-")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 0, 0


def fetch_conference_standings() -> dict:
    """
    Fetch conference standings for all conferences.
    Returns dict of conference_name -> list of team dicts sorted by standing.
    """
    standings = {}

    for conf_name, conf_id in CONFERENCE_IDS.items():
        try:
            url = (
                "https://site.api.espn.com/apis/v2/sports/basketball/"
                "mens-college-basketball/standings"
            )
            resp = requests.get(url, params={"group": conf_id}, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            # Standings entries are at data.standings.entries[]
            entries = data.get("standings", {}).get("entries", [])

            conf_teams = []
            for entry in entries:
                team_info = entry.get("team", {})
                team_id = int(team_info.get("id", 0))
                team_name = team_info.get("displayName",
                            f"{team_info.get('location', '')} {team_info.get('name', '')}".strip())

                stats = entry.get("stats", [])

                # Extract key stats by 'type' field
                overall_record = _get_stat(stats, "total", "0-0")
                wins_val = _get_stat(stats, "wins", 0)
                losses_val = _get_stat(stats, "losses", 0)
                playoff_seed = _get_stat(stats, "playoffseed", 99)
                conf_win_pct = _get_stat(stats, "leaguewinpercent", 0)

                # Parse wins/losses - prefer numeric stats, fall back to record string
                try:
                    wins = int(float(wins_val))
                    losses = int(float(losses_val))
                except (ValueError, TypeError):
                    wins, losses = _parse_record(str(overall_record))

                try:
                    standing = int(float(playoff_seed))
                except (ValueError, TypeError):
                    standing = 99

                # Get conference record from the "vsconf_*" stats or compute from pct
                try:
                    conf_pct = float(conf_win_pct)
                except (ValueError, TypeError):
                    conf_pct = 0.0

                # Try to get explicit conference wins/losses
                cw_val = _get_stat(stats, "leaguewins", None)
                cl_val = _get_stat(stats, "leaguelosses", None)
                if cw_val is not None and cl_val is not None:
                    try:
                        cw = int(float(cw_val))
                        cl = int(float(cl_val))
                    except (ValueError, TypeError):
                        cw, cl = 0, 0
                else:
                    # Estimate from win pct and total conf games played
                    # (rough estimate: assume ~18 conference games)
                    est_games = max(1, round(wins + losses - 12))  # non-conf ~ 12
                    cw = round(conf_pct * est_games)
                    cl = est_games - cw

                conf_teams.append({
                    "team_id": team_id,
                    "team_name": team_name,
                    "conference": conf_name,
                    "wins": wins,
                    "losses": losses,
                    "conf_wins": cw,
                    "conf_losses": cl,
                    "standing": standing,
                })

            # Sort by standing (playoffseed)
            conf_teams.sort(key=lambda t: t["standing"])
            standings[conf_name] = conf_teams
            logger.info(f"  {conf_name}: {len(conf_teams)} teams")

        except Exception as e:
            logger.warning(f"Could not fetch standings for {conf_name} (group {conf_id}): {e}")

    return standings


def fetch_rankings() -> dict:
    """
    Fetch AP Top 25 and Coaches Poll rankings.
    Returns dict of team_id -> {poll_name: rank, "record": str, "name": str}
    """
    rankings = {}
    try:
        resp = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/"
            "mens-college-basketball/rankings",
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        for ranking_set in data.get("rankings", []):
            poll_name = ranking_set.get("name", "")
            for entry in ranking_set.get("ranks", []):
                team = entry.get("team", {})
                team_id = int(team.get("id", 0))
                rank = entry.get("current", 999)
                record_str = entry.get("recordSummary", "0-0")
                team_name = f"{team.get('location', '')} {team.get('name', '')}".strip()

                if team_id not in rankings:
                    rankings[team_id] = {}
                rankings[team_id][poll_name] = rank
                rankings[team_id]["record"] = record_str
                rankings[team_id]["name"] = team_name

        logger.info(f"Fetched rankings: {len(rankings)} teams across polls")
    except Exception as e:
        logger.error(f"Error fetching rankings: {e}")
    return rankings


def build_team_database() -> list[Team]:
    """
    Build a comprehensive team database by combining ESPN data sources.
    Returns a list of Team objects with ratings and records populated.
    """
    teams_dict = {}

    # 1. Get conference standings (primary source for records + conf membership)
    logger.info("Fetching conference standings...")
    standings = fetch_conference_standings()
    total_teams = 0
    for conf_name, conf_teams in standings.items():
        for i, ct in enumerate(conf_teams):
            tid = ct["team_id"]
            teams_dict[tid] = Team(
                id=tid,
                name=ct["team_name"],
                conference=conf_name,
                wins=ct["wins"],
                losses=ct["losses"],
                conf_wins=ct["conf_wins"],
                conf_losses=ct["conf_losses"],
                conference_standing=ct["standing"],
                is_conference_champ=(ct["standing"] == 1),
            )
            total_teams += 1

    logger.info(f"Loaded {total_teams} teams from {len(standings)} conferences")

    if total_teams == 0:
        logger.error("No teams loaded from standings! API may be down.")
        return []

    # 2. Overlay rankings data (AP + Coaches)
    logger.info("Fetching rankings...")
    rankings = fetch_rankings()
    ranked_count = 0
    for tid, rank_data in rankings.items():
        if tid in teams_dict:
            for poll_name, rank_val in rank_data.items():
                if poll_name in ("record", "name"):
                    continue
                if not isinstance(rank_val, (int, float)):
                    continue
                if "AP" in poll_name:
                    teams_dict[tid].net_ranking = min(teams_dict[tid].net_ranking, int(rank_val))
                    ranked_count += 1
                elif "Coaches" in poll_name:
                    teams_dict[tid].kenpom_ranking = min(teams_dict[tid].kenpom_ranking, int(rank_val))

    logger.info(f"Applied rankings to {ranked_count} teams")

    # 3. Persist to DB
    team_list = list(teams_dict.values())
    save_teams_to_db(team_list)

    return team_list


def save_teams_to_db(teams: list[Team]):
    """Save team data to SQLite."""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()

    for t in teams:
        c.execute("""
            INSERT OR REPLACE INTO teams
            (id, name, conference, wins, losses, conf_wins, conf_losses,
             net_ranking, kenpom_ranking, quad1_wins, quad1_losses,
             quad2_wins, quad2_losses, quad3_losses, quad4_losses,
             sos_ranking, conference_standing, is_conference_champ, rating)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            t.id, t.name, t.conference, t.wins, t.losses,
            t.conf_wins, t.conf_losses, t.net_ranking, t.kenpom_ranking,
            t.quad1_wins, t.quad1_losses, t.quad2_wins, t.quad2_losses,
            t.quad3_losses, t.quad4_losses, t.sos_ranking,
            t.conference_standing, int(t.is_conference_champ), t.rating,
        ))

    conn.commit()
    conn.close()


def load_teams_from_db() -> list[Team]:
    """Load all teams from SQLite."""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM teams")
    rows = c.fetchall()
    conn.close()

    teams = []
    for r in rows:
        teams.append(Team(
            id=r[0], name=r[1], conference=r[2],
            wins=r[3], losses=r[4], conf_wins=r[5], conf_losses=r[6],
            net_ranking=r[7], kenpom_ranking=r[8],
            quad1_wins=r[9], quad1_losses=r[10],
            quad2_wins=r[11], quad2_losses=r[12],
            quad3_losses=r[13], quad4_losses=r[14],
            sos_ranking=r[15], conference_standing=r[16],
            is_conference_champ=bool(r[17]), rating=r[18],
        ))
    return teams
