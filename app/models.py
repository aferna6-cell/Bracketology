"""Data models for Bracketology."""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.config import DATABASE_PATH


@dataclass
class Team:
    id: int
    name: str
    conference: str
    wins: int = 0
    losses: int = 0
    conf_wins: int = 0
    conf_losses: int = 0
    net_ranking: int = 999
    kenpom_ranking: int = 999
    quad1_wins: int = 0
    quad1_losses: int = 0
    quad2_wins: int = 0
    quad2_losses: int = 0
    quad3_losses: int = 0
    quad4_losses: int = 0
    sos_ranking: int = 999
    conference_standing: int = 99
    is_conference_champ: bool = False
    rating: float = 0.0
    # Enhanced fields
    road_wins: int = 0
    road_losses: int = 0
    neutral_wins: int = 0
    neutral_losses: int = 0
    vs_ranked_record: str = ""
    streak: str = ""
    avg_points_for: float = 0.0
    avg_points_against: float = 0.0
    remaining_sos: float = 0.0  # future schedule difficulty

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}"

    @property
    def conf_record(self) -> str:
        return f"{self.conf_wins}-{self.conf_losses}"

    @property
    def win_pct(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.0

    @property
    def is_power_conference(self) -> bool:
        from app.config import POWER_CONFERENCES
        return self.conference in POWER_CONFERENCES

    @property
    def point_diff(self) -> float:
        return self.avg_points_for - self.avg_points_against

    def to_detail_dict(self) -> dict:
        """Full team detail for the team modal."""
        return {
            "id": self.id,
            "name": self.name,
            "conference": self.conference,
            "record": self.record,
            "conf_record": self.conf_record,
            "win_pct": round(self.win_pct, 3),
            "net_ranking": self.net_ranking if self.net_ranking < 999 else None,
            "kenpom_ranking": self.kenpom_ranking if self.kenpom_ranking < 999 else None,
            "sos_ranking": self.sos_ranking if self.sos_ranking < 999 else None,
            "conference_standing": self.conference_standing,
            "is_conference_champ": self.is_conference_champ,
            "rating": round(self.rating, 2),
            "quad1": f"{self.quad1_wins}-{self.quad1_losses}",
            "quad2": f"{self.quad2_wins}-{self.quad2_losses}",
            "quad3": f"W-{self.quad3_losses}L",
            "quad4": f"W-{self.quad4_losses}L",
            "road_record": f"{self.road_wins}-{self.road_losses}",
            "vs_ranked": self.vs_ranked_record or "N/A",
            "streak": self.streak or "N/A",
            "ppg": round(self.avg_points_for, 1) if self.avg_points_for else None,
            "opp_ppg": round(self.avg_points_against, 1) if self.avg_points_against else None,
            "point_diff": round(self.point_diff, 1) if self.avg_points_for else None,
            "is_power_conference": self.is_power_conference,
        }


@dataclass
class BracketEntry:
    """A team's placement in the bracket."""
    team: Team
    seed: int
    region: str
    is_auto_bid: bool
    is_first_four: bool = False
    first_four_opponent: Optional['BracketEntry'] = None
    bid_status: str = ""
    bubble_score: float = 0.0  # 0-100 for bubble meter


@dataclass
class GameResult:
    date: str
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int
    is_neutral: bool = False
    is_conference_tournament: bool = False


@dataclass
class Bracket:
    """Full 68-team bracket projection."""
    timestamp: str
    regions: dict = field(default_factory=dict)
    first_four: list = field(default_factory=list)
    auto_bids: list = field(default_factory=list)
    at_large: list = field(default_factory=list)
    last_four_in: list = field(default_factory=list)
    first_four_out: list = field(default_factory=list)
    next_four_out: list = field(default_factory=list)
    p5_status: dict = field(default_factory=dict)
    conference_breakdown: dict = field(default_factory=dict)
    all_teams: list = field(default_factory=list)  # all rated teams for what-if

    def to_dict(self) -> dict:
        def entry_to_dict(e, include_opponent=True):
            if e is None:
                return None
            d = {
                "team_name": e.team.name,
                "team_id": e.team.id,
                "conference": e.team.conference,
                "seed": e.seed,
                "region": e.region,
                "is_auto_bid": e.is_auto_bid,
                "is_first_four": e.is_first_four,
                "bid_status": e.bid_status,
                "record": e.team.record,
                "conf_record": e.team.conf_record,
                "net_ranking": e.team.net_ranking,
                "rating": round(e.team.rating, 2),
                "bubble_score": round(e.bubble_score, 1),
                "wins": e.team.wins,
                "losses": e.team.losses,
                "streak": e.team.streak,
            }
            if include_opponent and e.first_four_opponent:
                d["first_four_opponent"] = entry_to_dict(e.first_four_opponent, include_opponent=False)
            return d

        regions_dict = {}
        for region, entries in self.regions.items():
            regions_dict[region] = [entry_to_dict(e) for e in entries]

        first_four_dict = []
        for e1, e2 in self.first_four:
            first_four_dict.append({
                "game": [entry_to_dict(e1), entry_to_dict(e2)],
                "seed": e1.seed,
                "region": e1.region,
            })

        return {
            "timestamp": self.timestamp,
            "regions": regions_dict,
            "first_four": first_four_dict,
            "auto_bids": [entry_to_dict(e) for e in self.auto_bids],
            "at_large": [entry_to_dict(e) for e in self.at_large],
            "last_four_in": [entry_to_dict(e) for e in self.last_four_in],
            "first_four_out": [entry_to_dict(e) for e in self.first_four_out],
            "next_four_out": [entry_to_dict(e) for e in self.next_four_out],
            "p5_status": self.p5_status,
            "conference_breakdown": self.conference_breakdown,
        }


def init_db():
    """Initialize the SQLite database."""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            conference TEXT NOT NULL,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            conf_wins INTEGER DEFAULT 0,
            conf_losses INTEGER DEFAULT 0,
            net_ranking INTEGER DEFAULT 999,
            kenpom_ranking INTEGER DEFAULT 999,
            quad1_wins INTEGER DEFAULT 0,
            quad1_losses INTEGER DEFAULT 0,
            quad2_wins INTEGER DEFAULT 0,
            quad2_losses INTEGER DEFAULT 0,
            quad3_losses INTEGER DEFAULT 0,
            quad4_losses INTEGER DEFAULT 0,
            sos_ranking INTEGER DEFAULT 999,
            conference_standing INTEGER DEFAULT 99,
            is_conference_champ INTEGER DEFAULT 0,
            rating REAL DEFAULT 0.0
        )
    """)

    _ensure_team_columns(c)

    c.execute("""
        CREATE TABLE IF NOT EXISTS game_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL,
            home_score INTEGER NOT NULL,
            away_score INTEGER NOT NULL,
            is_neutral INTEGER DEFAULT 0,
            is_conference_tournament INTEGER DEFAULT 0,
            FOREIGN KEY (home_team_id) REFERENCES teams(id),
            FOREIGN KEY (away_team_id) REFERENCES teams(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            bracket_json TEXT NOT NULL,
            changes_json TEXT DEFAULT '[]'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            team_id INTEGER PRIMARY KEY
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
        ON snapshots(timestamp)
    """)

    conn.commit()
    conn.close()


def _ensure_team_columns(cursor: sqlite3.Cursor):
    columns = [
        "road_wins INTEGER DEFAULT 0",
        "road_losses INTEGER DEFAULT 0",
        "vs_ranked_record TEXT DEFAULT ''",
        "streak TEXT DEFAULT ''",
        "avg_points_for REAL DEFAULT 0.0",
        "avg_points_against REAL DEFAULT 0.0",
    ]
    for column in columns:
        try:
            cursor.execute(f"ALTER TABLE teams ADD COLUMN {column}")
        except sqlite3.OperationalError:
            continue


def save_snapshot(bracket: Bracket, changes: list = None):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO snapshots (timestamp, bracket_json, changes_json) VALUES (?, ?, ?)",
        (bracket.timestamp, json.dumps(bracket.to_dict()), json.dumps(changes or []))
    )
    conn.commit()
    conn.close()


def get_latest_snapshot() -> Optional[dict]:
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT bracket_json, changes_json FROM snapshots ORDER BY timestamp DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return {"bracket": json.loads(row[0]), "changes": json.loads(row[1])}
    return None


def get_snapshot_history(limit: int = 30) -> list:
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, timestamp, changes_json FROM snapshots ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "timestamp": r[1], "changes": json.loads(r[2])}
        for r in rows
    ]


def get_snapshot_by_id(snapshot_id: int) -> Optional[dict]:
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT bracket_json, changes_json FROM snapshots WHERE id = ?", (snapshot_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"bracket": json.loads(row[0]), "changes": json.loads(row[1])}
    return None


# Watchlist helpers
def get_watchlist() -> set:
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT team_id FROM watchlist")
    ids = {r[0] for r in c.fetchall()}
    conn.close()
    return ids


def add_to_watchlist(team_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO watchlist (team_id) VALUES (?)", (team_id,))
    conn.commit()
    conn.close()


def remove_from_watchlist(team_id: int):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM watchlist WHERE team_id = ?", (team_id,))
    conn.commit()
    conn.close()
