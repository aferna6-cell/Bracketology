"""
Bracket generation engine.

Builds the full 68-team NCAA tournament bracket including:
- Auto-bid selection (32 conference champions)
- At-large selection (36 teams)
- Seed line assignment (1-16)
- S-curve placement across 4 regions
- First Four matchups (last 4 at-large + last 4 auto-bids)
- Conference matchup avoidance in early rounds
"""

import logging
from datetime import datetime
from typing import Optional

from app.models import Team, BracketEntry, Bracket
from app.config import (
    REGIONS, ALL_CONFERENCES, POWER_CONFERENCES,
    TOURNAMENT_FIELD_SIZE, NUM_AUTO_BIDS, NUM_AT_LARGE,
    FIRST_FOUR_AT_LARGE, FIRST_FOUR_AUTO_BID,
)
from app.ratings import compute_ratings, assign_seed_line, classify_p5_team

logger = logging.getLogger(__name__)


def select_auto_bids(teams: list[Team]) -> list[Team]:
    """
    Select one auto-bid per conference.
    The auto-bid is the #1 team in conference standings (projected champ),
    or the conference tournament winner if available.
    """
    auto_bids = {}
    for team in teams:
        conf = team.conference
        if conf == "Unknown":
            continue
        if team.is_conference_champ:
            auto_bids[conf] = team
        elif conf not in auto_bids:
            # Fallback: take the team with the best conference standing
            if team.conference_standing == 1:
                auto_bids[conf] = team

    # If we still don't have a champ for some conferences, take the best-rated team
    conferences_seen = set(auto_bids.keys())
    for team in teams:
        conf = team.conference
        if conf not in conferences_seen and conf != "Unknown":
            auto_bids[conf] = team
            conferences_seen.add(conf)

    result = list(auto_bids.values())
    # Sort by rating descending
    result.sort(key=lambda t: t.rating, reverse=True)
    return result


def select_at_large(teams: list[Team], auto_bid_ids: set[int]) -> list[Team]:
    """
    Select the best remaining teams for at-large bids.
    Teams already with auto-bids are excluded.
    """
    candidates = [t for t in teams if t.id not in auto_bid_ids]
    # Already sorted by rating from compute_ratings
    candidates.sort(key=lambda t: t.rating, reverse=True)
    return candidates[:NUM_AT_LARGE]


def build_bracket(teams: list[Team]) -> Bracket:
    """
    Build a complete 68-team bracket projection.

    Steps:
    1. Compute ratings for all teams
    2. Select auto-bids (32 conference champs)
    3. Select at-large bids (top 36 remaining)
    4. Combine and rank all 68 teams
    5. Assign seed lines
    6. Identify First Four teams
    7. S-curve across regions
    8. Apply conference separation rules
    9. Label P5 team status
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Step 1: Rate all teams
    teams = compute_ratings(teams)

    if len(teams) == 0:
        return Bracket(timestamp=timestamp)

    # Step 2: Auto-bids
    auto_bid_teams = select_auto_bids(teams)
    auto_bid_ids = {t.id for t in auto_bid_teams}
    logger.info(f"Selected {len(auto_bid_teams)} auto-bids")

    # Step 3: At-large
    at_large_teams = select_at_large(teams, auto_bid_ids)
    at_large_ids = {t.id for t in at_large_teams}
    logger.info(f"Selected {len(at_large_teams)} at-large bids")

    # Step 4: Combine all tournament teams, sorted by rating
    all_tournament = []
    for t in auto_bid_teams:
        all_tournament.append((t, True))  # (team, is_auto_bid)
    for t in at_large_teams:
        all_tournament.append((t, False))
    all_tournament.sort(key=lambda x: x[0].rating, reverse=True)

    # Step 5: Identify First Four teams
    # Last 4 auto-bids play in First Four
    auto_bid_sorted = sorted(auto_bid_teams, key=lambda t: t.rating)
    first_four_auto = auto_bid_sorted[:FIRST_FOUR_AUTO_BID]
    first_four_auto_ids = {t.id for t in first_four_auto}

    # Last 4 at-large play in First Four
    at_large_sorted = sorted(at_large_teams, key=lambda t: t.rating)
    first_four_at_large = at_large_sorted[:FIRST_FOUR_AT_LARGE]
    first_four_at_large_ids = {t.id for t in first_four_at_large}

    all_first_four_ids = first_four_auto_ids | first_four_at_large_ids

    # Step 6: Build seed list (excluding First Four initially, they get placed at seeds 11 and 16)
    main_bracket_teams = [
        (t, is_auto) for t, is_auto in all_tournament
        if t.id not in all_first_four_ids
    ]

    # We need 60 teams in the main bracket (64 - 4 First Four winners)
    # Plus the 4 First Four game "winner slots"
    # Total unique seed positions = 64

    # Step 7: Assign seeds via S-curve
    bracket = Bracket(timestamp=timestamp)
    bracket.auto_bids = []
    bracket.at_large = []

    # Create entries for all 68 teams
    all_entries = []
    rank = 1
    for team, is_auto in main_bracket_teams:
        seed = assign_seed_line(rank)
        entry = BracketEntry(
            team=team,
            seed=seed,
            region="",  # assigned during S-curve
            is_auto_bid=is_auto,
            is_first_four=False,
        )
        all_entries.append(entry)
        if is_auto:
            bracket.auto_bids.append(entry)
        else:
            bracket.at_large.append(entry)
        rank += 1

    # Create First Four entries
    first_four_entries = []

    # Auto-bid First Four games: paired by rating (best vs worst of the 4), seed 16
    ff_auto_sorted = sorted(first_four_auto, key=lambda t: t.rating, reverse=True)
    for i in range(0, len(ff_auto_sorted), 2):
        if i + 1 < len(ff_auto_sorted):
            e1 = BracketEntry(
                team=ff_auto_sorted[i], seed=16, region="",
                is_auto_bid=True, is_first_four=True,
            )
            e2 = BracketEntry(
                team=ff_auto_sorted[i + 1], seed=16, region="",
                is_auto_bid=True, is_first_four=True,
            )
            e1.first_four_opponent = e2
            e2.first_four_opponent = e1
            first_four_entries.extend([e1, e2])
            bracket.auto_bids.extend([e1, e2])

    # At-large First Four games: paired similarly, seed 11
    ff_al_sorted = sorted(first_four_at_large, key=lambda t: t.rating, reverse=True)
    for i in range(0, len(ff_al_sorted), 2):
        if i + 1 < len(ff_al_sorted):
            e1 = BracketEntry(
                team=ff_al_sorted[i], seed=11, region="",
                is_auto_bid=False, is_first_four=True,
            )
            e2 = BracketEntry(
                team=ff_al_sorted[i + 1], seed=11, region="",
                is_auto_bid=False, is_first_four=True,
            )
            e1.first_four_opponent = e2
            e2.first_four_opponent = e1
            first_four_entries.extend([e1, e2])
            bracket.at_large.extend([e1, e2])

    # Step 8: S-curve across regions
    # Group main bracket entries by seed line
    seed_groups = {}
    for entry in all_entries:
        seed_groups.setdefault(entry.seed, []).append(entry)

    # Initialize regions
    for region in REGIONS:
        bracket.regions[region] = []

    # S-curve: for each seed line, distribute teams across regions
    for seed in range(1, 17):
        group = seed_groups.get(seed, [])
        # S-curve pattern: 1,2,3,4 then 4,3,2,1 alternating
        if seed % 2 == 1:
            region_order = REGIONS  # South, East, West, Midwest
        else:
            region_order = list(reversed(REGIONS))  # Midwest, West, East, South

        for i, entry in enumerate(group[:4]):
            region = region_order[i % 4]
            entry.region = region
            bracket.regions[region].append(entry)

    # Place First Four winners into appropriate seed slots
    ff_game_pairs = []
    processed = set()
    for entry in first_four_entries:
        if entry.team.id in processed:
            continue
        if entry.first_four_opponent:
            ff_game_pairs.append((entry, entry.first_four_opponent))
            processed.add(entry.team.id)
            processed.add(entry.first_four_opponent.team.id)

    # Assign First Four games to regions that need them
    ff_16_games = [(e1, e2) for e1, e2 in ff_game_pairs if e1.seed == 16]
    ff_11_games = [(e1, e2) for e1, e2 in ff_game_pairs if e1.seed == 11]

    # Apply conference separation for First Four games
    # Assign 16-seed First Four to last two regions
    for i, (e1, e2) in enumerate(ff_16_games):
        region = REGIONS[2 + i] if (2 + i) < len(REGIONS) else REGIONS[i]
        e1.region = region
        e2.region = region

    for i, (e1, e2) in enumerate(ff_11_games):
        region = REGIONS[i] if i < len(REGIONS) else REGIONS[0]
        e1.region = region
        e2.region = region

    bracket.first_four = ff_game_pairs

    # Step 9: Conference separation check (optional improvement)
    _apply_conference_separation(bracket)

    # Step 10: Identify bubble teams
    # The last 4 at-large teams in are "Last Four In"
    at_large_by_rating = sorted(
        [e for e in bracket.at_large if not e.is_first_four],
        key=lambda e: e.team.rating
    )
    bracket.last_four_in = at_large_by_rating[:4] if len(at_large_by_rating) >= 4 else at_large_by_rating

    # "First Four Out" and "Next Four Out" - teams just outside the bracket
    all_tourney_ids = {t.id for t, _ in all_tournament}
    remaining = [t for t in teams if t.id not in all_tourney_ids]
    remaining.sort(key=lambda t: t.rating, reverse=True)

    bracket.first_four_out = [
        BracketEntry(team=t, seed=0, region="", is_auto_bid=False, bid_status="first_four_out")
        for t in remaining[:4]
    ]
    bracket.next_four_out = [
        BracketEntry(team=t, seed=0, region="", is_auto_bid=False, bid_status="next_four_out")
        for t in remaining[4:8]
    ]

    # Step 11: P5 status labels
    at_large_cutoff = 0.0
    if bracket.last_four_in:
        at_large_cutoff = min(e.team.rating for e in bracket.last_four_in)

    p5_teams = [t for t in teams if t.is_power_conference]
    for t in p5_teams:
        status = classify_p5_team(t, at_large_cutoff, at_large_cutoff - 4)
        bracket.p5_status[t.name] = status

    # Set bid_status on entries
    for entry_list in [bracket.auto_bids, bracket.at_large]:
        for entry in entry_list:
            if entry.bid_status:
                continue
            name = entry.team.name
            if name in bracket.p5_status:
                entry.bid_status = bracket.p5_status[name]
            elif entry.is_auto_bid:
                entry.bid_status = "auto_bid"
            else:
                entry.bid_status = classify_p5_team(entry.team, at_large_cutoff, at_large_cutoff - 4)

    return bracket


def _apply_conference_separation(bracket: Bracket):
    """
    Try to avoid same-conference matchups in the first two rounds.
    This is a simplified version that swaps teams within the same seed line
    to different regions if a conference conflict is detected.
    """
    for seed in range(1, 17):
        # Check for 1v16, 2v15, etc. matchups within each region
        partner_seed = 17 - seed  # first round opponent's seed

        for region in REGIONS:
            region_entries = bracket.regions.get(region, [])
            team_at_seed = None
            team_at_partner = None

            for entry in region_entries:
                if entry.seed == seed:
                    team_at_seed = entry
                if entry.seed == partner_seed:
                    team_at_partner = entry

            if team_at_seed and team_at_partner:
                if team_at_seed.team.conference == team_at_partner.team.conference:
                    # Try to swap with another region
                    _try_swap(bracket, region, team_at_seed, seed)


def _try_swap(bracket: Bracket, current_region: str, entry: BracketEntry, seed: int):
    """Attempt to swap a team to a different region to avoid conference conflict."""
    partner_seed = 17 - seed

    for other_region in REGIONS:
        if other_region == current_region:
            continue

        other_entries = bracket.regions.get(other_region, [])
        other_at_seed = None
        other_at_partner = None

        for e in other_entries:
            if e.seed == seed:
                other_at_seed = e
            if e.seed == partner_seed:
                other_at_partner = e

        if other_at_seed and other_at_partner:
            # Check if swapping would fix the conflict without creating a new one
            if (entry.team.conference != other_at_partner.team.conference and
                    other_at_seed.team.conference != _get_partner_conf(bracket, current_region, partner_seed)):
                # Perform swap
                bracket.regions[current_region].remove(entry)
                bracket.regions[other_region].remove(other_at_seed)

                entry.region = other_region
                other_at_seed.region = current_region

                bracket.regions[other_region].append(entry)
                bracket.regions[current_region].append(other_at_seed)
                return True

    return False


def _get_partner_conf(bracket: Bracket, region: str, partner_seed: int) -> Optional[str]:
    """Get the conference of the team at a given seed in a region."""
    for entry in bracket.regions.get(region, []):
        if entry.seed == partner_seed:
            return entry.team.conference
    return None


def compute_changes(old_bracket: Optional[dict], new_bracket: Bracket) -> list[dict]:
    """
    Compare two bracket snapshots and identify changes.
    Returns a list of change descriptions.
    """
    if old_bracket is None:
        return [{"type": "initial", "message": "Initial bracket projection generated"}]

    changes = []
    old_data = old_bracket.get("bracket", {})
    new_data = new_bracket.to_dict()

    # Compare team lists
    old_teams = set()
    new_teams = set()
    old_seeds = {}
    new_seeds = {}

    for region_entries in old_data.get("regions", {}).values():
        for entry in region_entries:
            name = entry.get("team_name", "")
            old_teams.add(name)
            old_seeds[name] = entry.get("seed", 0)

    for ff in old_data.get("first_four", []):
        for entry in ff.get("game", []):
            name = entry.get("team_name", "")
            old_teams.add(name)
            old_seeds[name] = entry.get("seed", 0)

    for region_entries in new_data.get("regions", {}).values():
        for entry in region_entries:
            name = entry.get("team_name", "")
            new_teams.add(name)
            new_seeds[name] = entry.get("seed", 0)

    for ff in new_data.get("first_four", []):
        for entry in ff.get("game", []):
            name = entry.get("team_name", "")
            new_teams.add(name)
            new_seeds[name] = entry.get("seed", 0)

    # Teams added to bracket
    added = new_teams - old_teams
    for name in sorted(added):
        changes.append({
            "type": "added",
            "team": name,
            "message": f"{name} added to bracket (Seed {new_seeds.get(name, '?')})",
        })

    # Teams removed from bracket
    removed = old_teams - new_teams
    for name in sorted(removed):
        changes.append({
            "type": "removed",
            "team": name,
            "message": f"{name} removed from bracket",
        })

    # Seed changes for teams still in
    for name in sorted(old_teams & new_teams):
        old_s = old_seeds.get(name, 0)
        new_s = new_seeds.get(name, 0)
        if old_s != new_s:
            direction = "up" if new_s < old_s else "down"
            changes.append({
                "type": "seed_change",
                "team": name,
                "old_seed": old_s,
                "new_seed": new_s,
                "message": f"{name} moved {direction}: Seed {old_s} -> Seed {new_s}",
            })

    return changes
