"""Rating engine for computing team composite ratings."""

import logging
from app.models import Team
from app.config import POWER_CONFERENCES

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

    # Normalize rankings: lower rank = better, so invert for scoring
    max_net = max(t.net_ranking for t in teams) + 1
    max_kenpom = max(t.kenpom_ranking for t in teams) + 1
    max_sos = max(t.sos_ranking for t in teams) + 1

    for team in teams:
        score = 0.0

        # 1. NET ranking proxy (35% weight) - most important factor
        if team.net_ranking < 999:
            net_score = (max_net - team.net_ranking) / max_net * 100
        else:
            # Unranked teams get a score based on record
            net_score = team.win_pct * 40
        score += net_score * 0.35

        # 2. KenPom/coaches poll proxy (15% weight)
        if team.kenpom_ranking < 999:
            kp_score = (max_kenpom - team.kenpom_ranking) / max_kenpom * 100
        else:
            kp_score = team.win_pct * 30
        score += kp_score * 0.15

        # 3. Win percentage (15% weight)
        score += team.win_pct * 100 * 0.15

        # 4. Quality wins - Q1 (10% weight)
        q1_bonus = team.quad1_wins * 4 - team.quad1_losses * 1
        score += max(0, min(q1_bonus * 2, 100)) * 0.10

        # 5. Q2 wins and avoiding bad losses (5% weight)
        q2_bonus = team.quad2_wins * 2 - team.quad3_losses * 5 - team.quad4_losses * 10
        score += max(0, min(50 + q2_bonus, 100)) * 0.05

        # 6. Strength of schedule (10% weight)
        if team.sos_ranking < 999:
            sos_score = (max_sos - team.sos_ranking) / max_sos * 100
        else:
            # Power conference teams get SOS bump
            sos_score = 60 if team.is_power_conference else 30
        score += sos_score * 0.10

        # 7. Conference strength bonus (5% weight)
        if team.conference in ("SEC", "Big Ten", "Big 12"):
            score += 80 * 0.05
        elif team.conference in ("ACC", "Big East", "Pac-12"):
            score += 65 * 0.05
        elif team.conference in ("Mountain West", "American", "WCC", "Missouri Valley"):
            score += 45 * 0.05
        else:
            score += 25 * 0.05

        # 8. Conference standing bonus (5% weight)
        if team.conference_standing <= 3:
            standing_score = 90 - (team.conference_standing - 1) * 15
        elif team.conference_standing <= 8:
            standing_score = 50 - (team.conference_standing - 4) * 5
        else:
            standing_score = max(0, 30 - team.conference_standing)
        score += standing_score * 0.05

        team.rating = round(score, 3)

    # Sort by rating descending
    teams.sort(key=lambda t: t.rating, reverse=True)

    return teams


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
