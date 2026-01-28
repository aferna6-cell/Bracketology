"""Data models for Bracketology."""

import json
import sqlite3
from dataclasses import dataclass, field, asdict
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
    sos_ranking: int = 999  # strength of schedule
    conference_standing: int = 99  # position in conference
    is_conference_champ: bool = False
    rating: float = 0.0  # composite rating used for seeding

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


@dataclass
class BracketEntry:
    """A team's placement in the bracket."""
    team: Team
    seed: int
    region: str
    is_auto_bid: bool
    is_first_four: bool = False
    first_four_opponent: Optional['BracketEntry'] = None
    bid_status: str = ""  # "lock", "safe", "bubble_in", "bubble_out", "eliminated"


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
    regions: dict = field(default_factory=dict)  # region -> list of BracketEntry
    first_four: list = field(default_factory=list)  # list of (BracketEntry, BracketEntry) tuples
    auto_bids: list = field(default_factory=list)
    at_large: list = field(default_factory=list)
    last_four_in: list = field(default_factory=list)
    first_four_out: list = field(default_factory=list)
    next_four_out: list = field(default_factory=list)
    p5_status: dict = field(default_factory=dict)  # team_name -> status string

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
                "net_ranking": e.team.net_ranking,
                "rating": round(e.team.rating, 2),
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
        CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
        ON snapshots(timestamp)
    """)

    conn.commit()
    conn.close()


def save_snapshot(bracket: Bracket, changes: list = None):
    """Save a bracket snapshot to the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO snapshots (timestamp, bracket_json, changes_json) VALUES (?, ?, ?)",
        (bracket.timestamp, json.dumps(bracket.to_dict()), json.dumps(changes or []))
    )
    conn.commit()
    conn.close()


def get_latest_snapshot() -> Optional[dict]:
    """Get the most recent bracket snapshot."""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT bracket_json, changes_json FROM snapshots ORDER BY timestamp DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return {"bracket": json.loads(row[0]), "changes": json.loads(row[1])}
    return None


def get_snapshot_history(limit: int = 30) -> list:
    """Get recent snapshot summaries."""
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
    """Get a specific snapshot by ID."""
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("SELECT bracket_json, changes_json FROM snapshots WHERE id = ?", (snapshot_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"bracket": json.loads(row[0]), "changes": json.loads(row[1])}
    return None
