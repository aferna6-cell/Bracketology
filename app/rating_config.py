"""Configuration and scoring helpers for team ratings."""

from __future__ import annotations

import math
import re

from app.models import Team

RATING_SCALE = 100.0

# Component weights should sum to 1.0 for a 0-100 scale.
RATING_WEIGHTS = {
    "net": 0.28,
    "kenpom": 0.12,
    "win_pct": 0.12,
    "quality_wins": 0.08,
    "bad_losses": 0.05,
    "sos": 0.08,
    "conf_strength": 0.05,
    "conf_standing": 0.05,
    "road_win_pct": 0.04,
    "point_diff": 0.05,
    "vs_ranked": 0.03,
    "streak": 0.02,
    "conf_win_pct": 0.03,
}

POINT_DIFF_RANGE = (-15.0, 15.0)
STREAK_BONUS_PER_GAME = 2.0
STREAK_MAX_BONUS = 10.0

CONF_TIER_SCORES = {
    "elite": 80,
    "strong": 65,
    "solid": 45,
    "default": 25,
}


def clamp(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def normalize_rank(rank: int, max_rank: int, fallback_win_pct: float, fallback_scale: float) -> float:
    if rank < 999:
        denom = max_rank + 1
        return clamp((denom - rank) / denom * RATING_SCALE)
    return clamp(fallback_win_pct * fallback_scale)


def win_pct_score(win_pct: float) -> float:
    return clamp(win_pct * RATING_SCALE)


def quality_wins_score(team: Team) -> float:
    q1_bonus = team.quad1_wins * 4 - team.quad1_losses * 1
    return clamp(q1_bonus * 2)


def bad_losses_score(team: Team) -> float:
    q2_bonus = team.quad2_wins * 2 - team.quad3_losses * 5 - team.quad4_losses * 10
    return clamp(50 + q2_bonus)


def sos_score(team: Team, max_sos: int) -> float:
    if team.sos_ranking < 999:
        denom = max_sos + 1
        return clamp((denom - team.sos_ranking) / denom * RATING_SCALE)
    return 60 if team.is_power_conference else 30


def conf_strength_score(conference: str) -> float:
    if conference in ("SEC", "Big Ten", "Big 12"):
        return CONF_TIER_SCORES["elite"]
    if conference in ("ACC", "Big East", "Pac-12"):
        return CONF_TIER_SCORES["strong"]
    if conference in ("Mountain West", "American", "WCC", "Missouri Valley"):
        return CONF_TIER_SCORES["solid"]
    return CONF_TIER_SCORES["default"]


def conf_standing_score(standing: int) -> float:
    if standing <= 3:
        return clamp(90 - (standing - 1) * 15)
    if standing <= 8:
        return clamp(50 - (standing - 4) * 5)
    return clamp(30 - standing)


def road_win_pct_score(team: Team) -> float:
    total = team.road_wins + team.road_losses
    win_pct = team.road_wins / total if total > 0 else team.win_pct
    return win_pct_score(win_pct)


def conf_win_pct_score(team: Team) -> float:
    total = team.conf_wins + team.conf_losses
    win_pct = team.conf_wins / total if total > 0 else team.win_pct
    return win_pct_score(win_pct)


def point_diff_score(team: Team) -> float:
    low, high = POINT_DIFF_RANGE
    diff = team.point_diff
    if math.isfinite(diff):
        diff = max(low, min(high, diff))
        return clamp((diff - low) / (high - low) * RATING_SCALE)
    return 50.0


def vs_ranked_score(team: Team) -> float:
    record = (team.vs_ranked_record or "").strip()
    wins, losses = _parse_record(record)
    total = wins + losses
    win_pct = wins / total if total > 0 else team.win_pct
    return win_pct_score(win_pct)


def streak_score(team: Team) -> float:
    record = (team.streak or "").strip()
    match = re.search(r"([WL])\s*(\d+)", record, re.IGNORECASE)
    if not match:
        return 50.0
    direction = match.group(1).upper()
    length = int(match.group(2))
    bonus = min(STREAK_MAX_BONUS, length * STREAK_BONUS_PER_GAME)
    if direction == "L":
        bonus *= -1
    return clamp(50.0 + bonus)


def _parse_record(record_str: str) -> tuple[int, int]:
    if "-" not in record_str:
        return 0, 0
    try:
        wins_str, losses_str = record_str.split("-", 1)
        return int(wins_str), int(losses_str)
    except ValueError:
        return 0, 0
