"""Data ingestion from ESPN APIs and web sources."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from app.config import (
    DATABASE_PATH,
    ESPN_SCOREBOARD_URL,
    ESPN_TEAMS_URL,
    ALL_CONFERENCES,
    POWER_CONFERENCES,
)
from app.models import Team, GameResult

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


def fetch_espn_teams() -> list[Team]:
    """Fetch all D1 teams from ESPN API."""
    teams = []
    try:
        # Fetch teams page by page
        page = 1
        while True:
            resp = requests.get(
                ESPN_TEAMS_URL,
                params={"limit": 100, "page": page},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            sports = data.get("sports", [{}])
            if not sports:
                break
            leagues = sports[0].get("leagues", [{}])
            if not leagues:
                break
            league_teams = leagues[0].get("teams", [])

            if not league_teams:
                break

            for entry in league_teams:
                t = entry.get("team", {})
                team_id = int(t.get("id", 0))
                name = t.get("displayName", t.get("name", "Unknown"))
                # Conference info may need separate lookup
                teams.append(Team(
                    id=team_id,
                    name=name,
                    conference="Unknown",
                ))

            # Check if there are more pages
            total = data.get("count", 0)
            if page * 100 >= total:
                break
            page += 1

    except Exception as e:
        logger.error(f"Error fetching ESPN teams: {e}")

    return teams


def fetch_team_details_from_espn(team_id: int) -> dict:
    """Fetch detailed info for a single team."""
    try:
        url = f"{ESPN_TEAMS_URL}/{team_id}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching team {team_id}: {e}")
        return {}


def fetch_scoreboard(date_str: str = None) -> list[dict]:
    """Fetch game scores for a given date (YYYYMMDD format)."""
    params = {}
    if date_str:
        params["dates"] = date_str
    params["limit"] = 200
    params["groups"] = 50  # D1 men's basketball

    try:
        resp = requests.get(ESPN_SCOREBOARD_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events", [])
        games = []
        for event in events:
            competitions = event.get("competitions", [{}])
            for comp in competitions:
                competitors = comp.get("competitors", [])
                if len(competitors) < 2:
                    continue
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

                status = comp.get("status", {}).get("type", {}).get("name", "")

                games.append({
                    "date": event.get("date", ""),
                    "home_team_id": int(home.get("id", 0)),
                    "home_team_name": home.get("team", {}).get("displayName", ""),
                    "away_team_id": int(away.get("id", 0)),
                    "away_team_name": away.get("team", {}).get("displayName", ""),
                    "home_score": int(home.get("score", 0)),
                    "away_score": int(away.get("score", 0)),
                    "status": status,
                    "is_neutral": comp.get("neutralSite", False),
                    "is_conference": comp.get("conferenceCompetition", False),
                })
        return games
    except Exception as e:
        logger.error(f"Error fetching scoreboard: {e}")
        return []


def fetch_rankings() -> dict:
    """Fetch current rankings (AP, NET-like proxy via ESPN BPI)."""
    rankings = {}
    try:
        resp = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings",
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
                if team_id not in rankings:
                    rankings[team_id] = {}
                rankings[team_id][poll_name] = rank
                rankings[team_id]["record"] = record_str
                rankings[team_id]["name"] = team.get("displayName", "")
    except Exception as e:
        logger.error(f"Error fetching rankings: {e}")
    return rankings


def fetch_conference_standings() -> dict:
    """Fetch conference standings to determine projected auto-bids."""
    standings = {}
    for conf_name, conf_id in CONFERENCE_IDS.items():
        try:
            url = (
                "https://site.api.espn.com/apis/v2/sports/basketball/"
                "mens-college-basketball/standings"
            )
            resp = requests.get(
                url,
                params={"group": conf_id},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            conf_standings = []
            for child in data.get("children", []):
                for entry in child.get("standings", {}).get("entries", []):
                    team_info = entry.get("team", {})
                    team_id = int(team_info.get("id", 0))
                    stats = {s["name"]: s["value"] for s in entry.get("stats", [])}

                    overall_record = stats.get("overall", "0-0")
                    conf_record = stats.get("vs. Conf.", "0-0")

                    wins, losses = 0, 0
                    if isinstance(overall_record, str) and "-" in overall_record:
                        parts = overall_record.split("-")
                        wins, losses = int(parts[0]), int(parts[1])

                    cw, cl = 0, 0
                    if isinstance(conf_record, str) and "-" in conf_record:
                        parts = conf_record.split("-")
                        cw, cl = int(parts[0]), int(parts[1])

                    conf_standings.append({
                        "team_id": team_id,
                        "team_name": team_info.get("displayName", ""),
                        "conference": conf_name,
                        "wins": wins,
                        "losses": losses,
                        "conf_wins": cw,
                        "conf_losses": cl,
                        "standing": len(conf_standings) + 1,
                    })

            standings[conf_name] = conf_standings
        except Exception as e:
            logger.warning(f"Could not fetch standings for {conf_name}: {e}")

    return standings


def fetch_bpi_rankings() -> list[dict]:
    """Fetch ESPN BPI rankings as a proxy for NET rankings."""
    teams = []
    try:
        resp = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/"
            "mens-college-basketball/rankings",
            params={"type": 2},  # BPI
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for ranking_set in data.get("rankings", []):
            for entry in ranking_set.get("ranks", []):
                team = entry.get("team", {})
                teams.append({
                    "team_id": int(team.get("id", 0)),
                    "name": team.get("displayName", ""),
                    "ranking": entry.get("current", 999),
                    "record": entry.get("recordSummary", "0-0"),
                })
    except Exception as e:
        logger.error(f"Error fetching BPI: {e}")
    return teams


def build_team_database() -> list[Team]:
    """
    Build a comprehensive team database by combining multiple data sources.
    Returns a list of Team objects with ratings and records populated.
    """
    teams_dict = {}

    # 1. Get conference standings (primary source for records + conf membership)
    logger.info("Fetching conference standings...")
    standings = fetch_conference_standings()
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
                is_conference_champ=(i == 0),  # #1 in standings = projected champ
            )

    # 2. Overlay rankings data
    logger.info("Fetching rankings...")
    rankings = fetch_rankings()
    for tid, rank_data in rankings.items():
        if tid in teams_dict:
            # Use AP poll ranking as a proxy; real system would use NET
            for poll_name, rank_val in rank_data.items():
                if poll_name in ("AP Top 25", "AP Poll"):
                    teams_dict[tid].net_ranking = min(teams_dict[tid].net_ranking, rank_val)
                if poll_name in ("Coaches Poll",):
                    teams_dict[tid].kenpom_ranking = min(teams_dict[tid].kenpom_ranking, rank_val)

    # 3. Overlay BPI data
    logger.info("Fetching BPI rankings...")
    bpi = fetch_bpi_rankings()
    for entry in bpi:
        tid = entry["team_id"]
        if tid in teams_dict:
            # Use BPI ranking as another signal
            teams_dict[tid].sos_ranking = entry["ranking"]

    # 4. Persist to DB
    save_teams_to_db(list(teams_dict.values()))

    return list(teams_dict.values())


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
