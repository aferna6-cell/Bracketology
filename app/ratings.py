"""Rating engine for computing team composite ratings."""

import logging

from app.models import Team
from app.rating_config import (
    RATING_WEIGHTS,
    bad_losses_score,
    conf_standing_score,
    conf_strength_score,
    conf_win_pct_score,
    normalize_rank,
    point_diff_score,
    quality_wins_score,
    road_win_pct_score,
    sos_score,
    streak_score,
    vs_ranked_score,
    win_pct_score,
)

logger = logging.getLogger(__name__)


def compute_ratings(teams: list[Team]) -> list[Team]:
    """
    Compute a composite rating for each team.

    The rating combines multiple factors to approximate what the NCAA
    selection committee considers:
    - NET ranking (or AP/BPI proxy)
    - Win-loss record / win percentage
    - Conference strength
    - Quality wins (Q1/Q2)
    - Bad losses (Q3/Q4)
    - Strength of schedule
    - Conference standing

    Returns teams sorted by rating (highest = best).
    """
    if not teams:
        return teams

    max_net = _max_rank(teams, "net_ranking")
    max_kenpom = _max_rank(teams, "kenpom_ranking")
    max_sos = _max_rank(teams, "sos_ranking")

    for team in teams:
        score = 0.0

        component_scores = {
            "net": normalize_rank(team.net_ranking, max_net, team.win_pct, 40),
            "kenpom": normalize_rank(team.kenpom_ranking, max_kenpom, team.win_pct, 30),
            "win_pct": win_pct_score(team.win_pct),
            "quality_wins": quality_wins_score(team),
            "bad_losses": bad_losses_score(team),
            "sos": sos_score(team, max_sos),
            "conf_strength": conf_strength_score(team.conference),
            "conf_standing": conf_standing_score(team.conference_standing),
            "road_win_pct": road_win_pct_score(team),
            "point_diff": point_diff_score(team),
            "vs_ranked": vs_ranked_score(team),
            "streak": streak_score(team),
            "conf_win_pct": conf_win_pct_score(team),
        }

        for key, weight in RATING_WEIGHTS.items():
            score += component_scores.get(key, 0.0) * weight

        team.rating = round(score, 3)

    # Sort by rating descending
    teams.sort(key=lambda t: t.rating, reverse=True)

    return teams


def _max_rank(teams: list[Team], attr: str) -> int:
    valid = [getattr(t, attr) for t in teams if getattr(t, attr) < 999]
    if not valid:
        return 999
    return max(valid)


def assign_seed_line(rank_position: int) -> int:
    """
    Convert an overall ranking position (1-68) into a seed line (1-16).
    Each seed line has 4 teams (one per region).
    """
    if rank_position <= 0:
        return 1
    return min(16, (rank_position - 1) // 4 + 1)


def classify_p5_team(team: Team, at_large_cutoff_rating: float, bubble_threshold: float) -> str:
    """
    Classify a power conference team's tournament status.

    Returns one of:
    - "lock": Safely in the tournament as at-large
    - "safe": Likely in but not a certainty
    - "bubble_in": On the bubble, currently projected in
    - "bubble_out": On the bubble, currently projected out
    - "eliminated": No realistic path to at-large bid
    - "auto_bid": Won their conference tournament
    """
    if team.is_conference_champ:
        return "auto_bid"

    # Use rating relative to the at-large cutoff
    margin = team.rating - at_large_cutoff_rating

    if margin > 8:
        return "lock"
    elif margin > 4:
        return "safe"
    elif margin > 0:
        return "bubble_in"
    elif margin > -4:
        return "bubble_out"
    else:
        # Check if team is truly eliminated (terrible record)
        if team.losses > team.wins or (team.win_pct < 0.45):
            return "eliminated"
        return "bubble_out"
