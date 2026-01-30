"""Data ingestion from ESPN APIs."""

import logging
import sqlite3
from datetime import datetime
from time import monotonic

import csv
import io
import requests

from app.config import (
    DATABASE_PATH,
    ESPN_SCOREBOARD_URL,
    ESPN_TEAMS_URL,
    KENPOM_RANKINGS_URL,
    MASSEY_COMPARE_URL,
    NET_RANKINGS_URL,
    SAGARIN_RANKINGS_URL,
    SCOREBOARD_CACHE_TTL_SECONDS,
    TORVIK_RANKINGS_URL,
)
from app.models import Team

logger = logging.getLogger(__name__)

_scoreboard_cache: dict[str, tuple[float, list[dict]]] = {}

# ESPN conference group IDs (Pac-12 removed - dissolved after 2023-24)
CONFERENCE_IDS = {
    "ACC": 2, "American": 62, "Atlantic 10": 3, "Big 12": 8,
    "Big East": 4, "Big Ten": 7, "Big West": 5, "CAA": 10,
    "C-USA": 11, "Horizon": 45, "Ivy": 12, "MAAC": 13, "MAC": 14,
    "MEAC": 16, "Missouri Valley": 18, "Mountain West": 44, "NEC": 19,
    "OVC": 20, "Patriot": 22, "SEC": 23, "SoCon": 24,
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


def _parse_record(record_str) -> tuple:
    """Parse '20-5' into (20, 5)."""
    if not record_str or not isinstance(record_str, str) or "-" not in record_str:
        return 0, 0
    try:
        parts = record_str.split("-")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 0, 0


def _safe_int(val, default=0):
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def fetch_conference_standings() -> dict:
    """Fetch conference standings for all conferences."""
    standings = {}

    for conf_name, conf_id in CONFERENCE_IDS.items():
        try:
            url = ("https://site.api.espn.com/apis/v2/sports/basketball/"
                   "mens-college-basketball/standings")
            resp = requests.get(url, params={"group": conf_id}, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            entries = data.get("standings", {}).get("entries", [])
            conf_teams = []

            for entry in entries:
                team_info = entry.get("team", {})
                team_id = int(team_info.get("id", 0))
                team_name = team_info.get("displayName",
                    f"{team_info.get('location', '')} {team_info.get('name', '')}".strip())

                stats = entry.get("stats", [])

                wins = _safe_int(_get_stat(stats, "wins", 0))
                losses = _safe_int(_get_stat(stats, "losses", 0))
                standing = _safe_int(_get_stat(stats, "playoffseed", 99))
                conf_pct = _safe_float(_get_stat(stats, "leaguewinpercent", 0))

                # Conference record
                cw_val = _get_stat(stats, "leaguewins", None)
                cl_val = _get_stat(stats, "leaguelosses", None)
                if cw_val is not None and cl_val is not None:
                    cw = _safe_int(cw_val)
                    cl = _safe_int(cl_val)
                else:
                    est_games = max(1, round(wins + losses - 12))
                    cw = round(conf_pct * est_games)
                    cl = est_games - cw

                # Enhanced stats
                rw, rl = _parse_record(str(_get_stat(stats, "road", "0-0")))
                vs_ranked = str(_get_stat(stats, "vsaprankedteams", ""))
                streak = str(_get_stat(stats, "streak", ""))
                ppg_f = _safe_float(_get_stat(stats, "avgpointsfor", 0))
                opp_f = _safe_float(_get_stat(stats, "avgpointsagainst", 0))

                conf_teams.append({
                    "team_id": team_id,
                    "team_name": team_name,
                    "conference": conf_name,
                    "wins": wins, "losses": losses,
                    "conf_wins": cw, "conf_losses": cl,
                    "standing": standing,
                    "road_wins": rw, "road_losses": rl,
                    "vs_ranked": vs_ranked, "streak": streak,
                    "ppg": ppg_f, "opp_ppg": opp_f,
                })

            conf_teams.sort(key=lambda t: t["standing"])
            standings[conf_name] = conf_teams
            logger.info(f"  {conf_name}: {len(conf_teams)} teams")

        except Exception as e:
            logger.warning(f"Could not fetch standings for {conf_name} (group {conf_id}): {e}")

    return standings


def fetch_rankings() -> dict:
    """Fetch AP Top 25 and Coaches Poll rankings."""
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

        logger.info(f"Fetched rankings: {len(rankings)} ranked teams")
    except Exception as e:
        logger.error(f"Error fetching rankings: {e}")
    return rankings


def build_team_database():
    """
    Build comprehensive team database from ESPN data.
    Returns (teams_list, errors_list).
    """
    teams_dict = {}
    errors = []

    # 1. Conference standings
    logger.info("Fetching conference standings...")
    standings = fetch_conference_standings()
    total_teams = 0
    for conf_name, conf_teams in standings.items():
        for ct in conf_teams:
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
                road_wins=ct.get("road_wins", 0),
                road_losses=ct.get("road_losses", 0),
                vs_ranked_record=ct.get("vs_ranked", ""),
                streak=ct.get("streak", ""),
                avg_points_for=ct.get("ppg", 0.0),
                avg_points_against=ct.get("opp_ppg", 0.0),
            )
            total_teams += 1

    logger.info(f"Loaded {total_teams} teams from {len(standings)} conferences")

    if total_teams == 0:
        errors.append("ESPN standings API returned 0 teams. The API may be temporarily unavailable.")
        return [], errors

    # 2. Rankings overlay
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

    # 3. Advanced metrics overlay (NET/KenPom/Torvik/Sagarin)
    _apply_advanced_metrics(teams_dict)

    # 4. Persist
    team_list = list(teams_dict.values())
    save_teams_to_db(team_list)

    return team_list, errors


def save_teams_to_db(teams: list):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    for t in teams:
        c.execute("""
            INSERT OR REPLACE INTO teams
            (id, name, conference, wins, losses, conf_wins, conf_losses,
             net_ranking, kenpom_ranking, quad1_wins, quad1_losses,
             quad2_wins, quad2_losses, quad3_losses, quad4_losses,
             sos_ranking, conference_standing, is_conference_champ, rating,
             road_wins, road_losses, vs_ranked_record, streak,
             avg_points_for, avg_points_against, torvik_ranking, sagarin_ranking)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            t.id, t.name, t.conference, t.wins, t.losses,
            t.conf_wins, t.conf_losses, t.net_ranking, t.kenpom_ranking,
            t.quad1_wins, t.quad1_losses, t.quad2_wins, t.quad2_losses,
            t.quad3_losses, t.quad4_losses, t.sos_ranking,
            t.conference_standing, int(t.is_conference_champ), t.rating,
            t.road_wins, t.road_losses, t.vs_ranked_record, t.streak,
            t.avg_points_for, t.avg_points_against, t.torvik_ranking, t.sagarin_ranking,
        ))
    conn.commit()
    conn.close()


def load_teams_from_db() -> list:
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT
            id, name, conference, wins, losses, conf_wins, conf_losses,
            net_ranking, kenpom_ranking, quad1_wins, quad1_losses,
            quad2_wins, quad2_losses, quad3_losses, quad4_losses,
            sos_ranking, conference_standing, is_conference_champ, rating,
            road_wins, road_losses, vs_ranked_record, streak,
            avg_points_for, avg_points_against, torvik_ranking, sagarin_ranking
        FROM teams
    """)
    rows = c.fetchall()
    conn.close()
    return [Team(
        id=r[0], name=r[1], conference=r[2],
        wins=r[3], losses=r[4], conf_wins=r[5], conf_losses=r[6],
        net_ranking=r[7], kenpom_ranking=r[8],
        quad1_wins=r[9], quad1_losses=r[10],
        quad2_wins=r[11], quad2_losses=r[12],
        quad3_losses=r[13], quad4_losses=r[14],
        sos_ranking=r[15], conference_standing=r[16],
        is_conference_champ=bool(r[17]), rating=r[18],
        road_wins=r[19], road_losses=r[20],
        vs_ranked_record=r[21] or "", streak=r[22] or "",
        avg_points_for=r[23] or 0.0, avg_points_against=r[24] or 0.0,
        torvik_ranking=r[25] or 999, sagarin_ranking=r[26] or 999,
    ) for r in rows]


def _apply_advanced_metrics(teams_dict: dict[int, Team]) -> None:
    sources = {
        "net": NET_RANKINGS_URL,
        "kenpom": KENPOM_RANKINGS_URL,
        "torvik": _resolve_year_url(TORVIK_RANKINGS_URL),
        "sagarin": SAGARIN_RANKINGS_URL,
        "massey": MASSEY_COMPARE_URL,
    }
    name_map = {_normalize_name(t.name): t for t in teams_dict.values()}

    for label, url in sources.items():
        if not url:
            continue
        try:
            if label == "net":
                rankings = _fetch_net_rankings(url)
            elif label == "massey":
                rankings = _fetch_massey_rankings(url)
            else:
                rankings = _fetch_rankings_csv(url)
        except Exception as exc:
            logger.warning(f"Advanced metric fetch failed for {label}: {exc}")
            continue
        applied = 0
        for team_name, rank in rankings.items():
            team = name_map.get(_normalize_name(team_name))
            if not team:
                continue
            if label == "net":
                team.net_ranking = min(team.net_ranking, rank)
            elif label == "kenpom":
                team.kenpom_ranking = min(team.kenpom_ranking, rank)
            elif label == "torvik":
                team.torvik_ranking = min(team.torvik_ranking, rank)
            elif label == "sagarin":
                team.sagarin_ranking = min(team.sagarin_ranking, rank)
            elif label == "massey":
                team.sagarin_ranking = min(team.sagarin_ranking, rank)
            applied += 1
        logger.info(f"Applied {applied} {label} rankings from advanced metrics.")


def _fetch_rankings_csv(url: str) -> dict[str, int]:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    content = resp.text
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise ValueError("CSV missing headers.")
    team_field = _find_field(reader.fieldnames, ("team", "school", "name"))
    rank_field = _find_field(reader.fieldnames, ("rank", "rating_rank", "rk"))
    if not team_field or not rank_field:
        raise ValueError(f"CSV missing team or rank columns: {reader.fieldnames}")
    rankings = {}
    for row in reader:
        team_name = (row.get(team_field) or "").strip()
        if not team_name:
            continue
        rank = _safe_int(row.get(rank_field), default=999)
        if rank <= 0:
            continue
        rankings[team_name] = rank
    return rankings


def _fetch_net_rankings(url: str) -> dict[str, int]:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    rankings = {}
    for entry in data:
        team_name = entry.get("team") or entry.get("name") or ""
        rank = _safe_int(entry.get("rank"), default=999)
        if team_name and rank > 0:
            rankings[team_name] = rank
    return rankings


def _fetch_massey_rankings(url: str) -> dict[str, int]:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    if not reader.fieldnames:
        raise ValueError("Massey CSV missing headers.")
    team_field = _find_field(reader.fieldnames, ("team", "school", "name"))
    sag_field = _find_field(reader.fieldnames, ("sag", "sagarin"))
    if not team_field or not sag_field:
        raise ValueError(f"Massey CSV missing team or SAG columns: {reader.fieldnames}")
    rankings = {}
    for row in reader:
        team_name = (row.get(team_field) or "").strip()
        if not team_name:
            continue
        rank = _safe_int(row.get(sag_field), default=999)
        if rank <= 0:
            continue
        rankings[team_name] = rank
    return rankings


def _find_field(fields: list[str], candidates: tuple[str, ...]) -> str | None:
    for field in fields:
        normalized = field.strip().lower().replace(" ", "").replace("_", "")
        for candidate in candidates:
            if normalized == candidate.replace(" ", "").replace("_", ""):
                return field
    return None


def _normalize_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _resolve_year_url(url: str) -> str:
    if "YYYY" not in url:
        return url
    return url.replace("YYYY", str(_current_season_year()))


def _current_season_year() -> int:
    today = datetime.now()
    return today.year + 1 if today.month >= 7 else today.year


def fetch_scoreboard(date: str) -> list[dict]:
    """Fetch the ESPN scoreboard for a given YYYYMMDD date."""
    cache_entry = _scoreboard_cache.get(date)
    if cache_entry:
        cached_at, cached_games = cache_entry
        if monotonic() - cached_at < SCOREBOARD_CACHE_TTL_SECONDS:
            return cached_games

    games = []
    try:
        resp = requests.get(ESPN_SCOREBOARD_URL, params={"dates": date}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error(f"Error fetching scoreboard for {date}: {exc}")
        return games

    for event in data.get("events", []):
        try:
            competitions = event.get("competitions", [])
            if not competitions:
                continue
            competition = competitions[0]
            competitors = competition.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                logger.warning("Scoreboard event missing home/away data.")
                continue

            start_time = event.get("date") or competition.get("date") or ""
            status = event.get("status", {}).get("type", {})
            state = status.get("state")
            if status.get("completed") or state == "post":
                status_label = "Final"
            elif state == "in":
                status_label = "In Progress"
            else:
                status_label = "Scheduled"

            games.append({
                "id": event.get("id"),
                "date": _format_event_date(start_time),
                "status": status_label,
                "start_time": start_time,
                "home": _parse_competitor(home),
                "away": _parse_competitor(away),
                "conference_game": bool(competition.get("conferenceCompetition")),
                "neutral_site": bool(competition.get("neutralSite")),
            })
        except Exception as exc:
            logger.warning(f"Failed to parse scoreboard event: {exc}")
            continue

    _scoreboard_cache[date] = (monotonic(), games)
    return games


def _parse_competitor(competitor: dict) -> dict:
    team = competitor.get("team", {})
    return {
        "id": _safe_int(team.get("id", 0)),
        "name": team.get("displayName") or team.get("name") or "Unknown",
        "score": _safe_int(competitor.get("score", 0)),
    }


def _format_event_date(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        clean = date_str.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(clean)
        return parsed.date().isoformat()
    except ValueError:
        return date_str.split("T")[0]
