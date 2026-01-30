"""
Bracket generation engine.

Builds the full 68-team NCAA tournament bracket including:
- Auto-bid selection (conference champions)
- At-large selection
- Seed line assignment (1-16)
- S-curve placement across 4 regions
- First Four matchups
- Conference matchup avoidance
- Conference breakdown
- Bubble scores
"""

import logging
from datetime import datetime
from typing import Optional

from app.models import Team, BracketEntry, Bracket
from app.config import (
    REGIONS, POWER_CONFERENCES, TOURNAMENT_FIELD_SIZE,
    FIRST_FOUR_AT_LARGE, FIRST_FOUR_AUTO_BID,
    MAX_NON_P5_AT_LARGE,
)
from app.ratings import compute_ratings, assign_seed_line, classify_p5_team

logger = logging.getLogger(__name__)


def select_auto_bids(teams: list) -> list:
    """Select one auto-bid per conference (#1 in standings = projected champ)."""
    auto_bids = {}
    for team in teams:
        conf = team.conference
        if conf == "Unknown":
            continue
        if team.is_conference_champ:
            auto_bids[conf] = team
        elif conf not in auto_bids and team.conference_standing == 1:
            auto_bids[conf] = team

    conferences_seen = set(auto_bids.keys())
    for team in teams:
        conf = team.conference
        if conf not in conferences_seen and conf != "Unknown":
            auto_bids[conf] = team
            conferences_seen.add(conf)

    result = list(auto_bids.values())
    result.sort(key=lambda t: t.rating, reverse=True)
    return result


def select_at_large(teams: list, auto_bid_ids: set, num_auto_bids: int) -> list:
    num_at_large = TOURNAMENT_FIELD_SIZE - num_auto_bids
    candidates = [t for t in teams if t.id not in auto_bid_ids]
    p5_candidates = [t for t in candidates if t.is_power_conference]
    non_p5_candidates = [t for t in candidates if not t.is_power_conference]

    p5_candidates.sort(key=lambda t: t.rating, reverse=True)
    non_p5_candidates.sort(key=lambda t: t.rating, reverse=True)

    max_non_p5 = min(MAX_NON_P5_AT_LARGE, num_at_large)
    p5_target = max(0, num_at_large - max_non_p5)

    selected = p5_candidates[:p5_target]

    remaining = [t for t in p5_candidates[p5_target:]] + non_p5_candidates
    remaining.sort(key=lambda t: t.rating, reverse=True)
    selected.extend(remaining[: num_at_large - len(selected)])
    return selected


def build_conference_breakdown(teams: list, auto_bid_ids: set, at_large_ids: set,
                                at_large_cutoff: float) -> dict:
    """Build conference breakdown: auto-bid, at-large teams, bubble status per conference."""
    breakdown = {}
    by_conf = {}
    for t in teams:
        by_conf.setdefault(t.conference, []).append(t)

    for conf, conf_teams in sorted(by_conf.items()):
        conf_teams.sort(key=lambda t: t.rating, reverse=True)
        auto_bid_team = None
        at_large_teams_list = []
        bubble_teams = []
        other_teams = []

        for t in conf_teams:
            if t.id in auto_bid_ids and t.is_conference_champ:
                auto_bid_team = {
                    "name": t.name, "id": t.id, "record": t.record,
                    "conf_record": t.conf_record, "rating": round(t.rating, 2),
                    "standing": t.conference_standing,
                }
            elif t.id in at_large_ids:
                at_large_teams_list.append({
                    "name": t.name, "id": t.id, "record": t.record,
                    "rating": round(t.rating, 2),
                })
            elif t.rating > at_large_cutoff - 6:
                bubble_teams.append({
                    "name": t.name, "id": t.id, "record": t.record,
                    "rating": round(t.rating, 2),
                    "status": classify_p5_team(t, at_large_cutoff, at_large_cutoff - 4),
                })
            else:
                other_teams.append({
                    "name": t.name, "id": t.id, "record": t.record,
                })

        breakdown[conf] = {
            "auto_bid": auto_bid_team,
            "at_large": at_large_teams_list,
            "bubble": bubble_teams,
            "others_count": len(other_teams),
            "total": len(conf_teams),
            "is_power": conf in POWER_CONFERENCES,
        }

    return breakdown


def build_bracket(teams: list) -> Bracket:
    """Build a complete 68-team bracket projection."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    teams = compute_ratings(teams)
    if not teams:
        return Bracket(timestamp=timestamp)

    # Auto-bids
    auto_bid_teams = select_auto_bids(teams)
    auto_bid_ids = {t.id for t in auto_bid_teams}
    logger.info(f"Selected {len(auto_bid_teams)} auto-bids")

    # At-large (dynamic count based on actual auto-bids)
    at_large_teams = select_at_large(teams, auto_bid_ids, len(auto_bid_teams))
    at_large_ids = {t.id for t in at_large_teams}
    logger.info(f"Selected {len(at_large_teams)} at-large bids")

    # Combine
    all_tournament = []
    for t in auto_bid_teams:
        all_tournament.append((t, True))
    for t in at_large_teams:
        all_tournament.append((t, False))
    all_tournament.sort(key=lambda x: x[0].rating, reverse=True)

    # First Four
    auto_bid_sorted = sorted(auto_bid_teams, key=lambda t: t.rating)
    first_four_auto = auto_bid_sorted[:FIRST_FOUR_AUTO_BID]
    first_four_auto_ids = {t.id for t in first_four_auto}

    at_large_sorted = sorted(at_large_teams, key=lambda t: t.rating)
    first_four_at_large = at_large_sorted[:FIRST_FOUR_AT_LARGE]
    first_four_at_large_ids = {t.id for t in first_four_at_large}

    all_first_four_ids = first_four_auto_ids | first_four_at_large_ids

    main_bracket_teams = [
        (t, is_auto) for t, is_auto in all_tournament
        if t.id not in all_first_four_ids
    ]

    bracket = Bracket(timestamp=timestamp)
    bracket.auto_bids = []
    bracket.at_large = []
    bracket.all_teams = teams

    # Create main bracket entries
    all_entries = []
    rank = 1
    for team, is_auto in main_bracket_teams:
        seed = assign_seed_line(rank)
        entry = BracketEntry(team=team, seed=seed, region="", is_auto_bid=is_auto)
        all_entries.append(entry)
        if is_auto:
            bracket.auto_bids.append(entry)
        else:
            bracket.at_large.append(entry)
        rank += 1

    # First Four entries
    first_four_entries = []

    ff_auto_sorted = sorted(first_four_auto, key=lambda t: t.rating, reverse=True)
    for i in range(0, len(ff_auto_sorted), 2):
        if i + 1 < len(ff_auto_sorted):
            e1 = BracketEntry(team=ff_auto_sorted[i], seed=16, region="",
                              is_auto_bid=True, is_first_four=True)
            e2 = BracketEntry(team=ff_auto_sorted[i + 1], seed=16, region="",
                              is_auto_bid=True, is_first_four=True)
            e1.first_four_opponent = e2
            e2.first_four_opponent = e1
            first_four_entries.extend([e1, e2])
            bracket.auto_bids.extend([e1, e2])

    ff_al_sorted = sorted(first_four_at_large, key=lambda t: t.rating, reverse=True)
    for i in range(0, len(ff_al_sorted), 2):
        if i + 1 < len(ff_al_sorted):
            e1 = BracketEntry(team=ff_al_sorted[i], seed=11, region="",
                              is_auto_bid=False, is_first_four=True)
            e2 = BracketEntry(team=ff_al_sorted[i + 1], seed=11, region="",
                              is_auto_bid=False, is_first_four=True)
            e1.first_four_opponent = e2
            e2.first_four_opponent = e1
            first_four_entries.extend([e1, e2])
            bracket.at_large.extend([e1, e2])

    # S-curve across regions
    seed_groups = {}
    for entry in all_entries:
        seed_groups.setdefault(entry.seed, []).append(entry)

    for region in REGIONS:
        bracket.regions[region] = []

    for seed in range(1, 17):
        group = seed_groups.get(seed, [])
        if seed % 2 == 1:
            region_order = REGIONS
        else:
            region_order = list(reversed(REGIONS))
        for i, entry in enumerate(group[:4]):
            region = region_order[i % 4]
            entry.region = region
            bracket.regions[region].append(entry)

    # First Four game pairs
    ff_game_pairs = []
    processed = set()
    for entry in first_four_entries:
        if entry.team.id in processed:
            continue
        if entry.first_four_opponent:
            ff_game_pairs.append((entry, entry.first_four_opponent))
            processed.add(entry.team.id)
            processed.add(entry.first_four_opponent.team.id)

    ff_16_games = [(e1, e2) for e1, e2 in ff_game_pairs if e1.seed == 16]
    ff_11_games = [(e1, e2) for e1, e2 in ff_game_pairs if e1.seed == 11]

    for i, (e1, e2) in enumerate(ff_16_games):
        region = REGIONS[2 + i] if (2 + i) < len(REGIONS) else REGIONS[i]
        e1.region = region
        e2.region = region

    for i, (e1, e2) in enumerate(ff_11_games):
        region = REGIONS[i] if i < len(REGIONS) else REGIONS[0]
        e1.region = region
        e2.region = region

    bracket.first_four = ff_game_pairs

    # Conference separation
    _apply_conference_separation(bracket)

    # Bubble teams
    at_large_by_rating = sorted(
        [e for e in bracket.at_large if not e.is_first_four],
        key=lambda e: e.team.rating
    )
    bracket.last_four_in = at_large_by_rating[:4] if len(at_large_by_rating) >= 4 else at_large_by_rating

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

    # At-large cutoff for P5 status + bubble scores
    at_large_cutoff = 0.0
    if bracket.last_four_in:
        at_large_cutoff = min(e.team.rating for e in bracket.last_four_in)

    # P5 status
    p5_teams = [t for t in teams if t.is_power_conference]
    for t in p5_teams:
        status = classify_p5_team(t, at_large_cutoff, at_large_cutoff - 4)
        bracket.p5_status[t.name] = status

    # Bid status + bubble scores
    for entry_list in [bracket.auto_bids, bracket.at_large]:
        for entry in entry_list:
            if not entry.bid_status:
                name = entry.team.name
                if name in bracket.p5_status:
                    entry.bid_status = bracket.p5_status[name]
                elif entry.is_auto_bid:
                    entry.bid_status = "auto_bid"
                else:
                    entry.bid_status = classify_p5_team(entry.team, at_large_cutoff, at_large_cutoff - 4)
            # Bubble score: 0 = out, 50 = cut line, 100 = lock
            margin = entry.team.rating - at_large_cutoff
            entry.bubble_score = max(0, min(100, 50 + margin * 4))

    for entry in bracket.first_four_out + bracket.next_four_out:
        margin = entry.team.rating - at_large_cutoff
        entry.bubble_score = max(0, min(100, 50 + margin * 4))

    # Conference breakdown
    bracket.conference_breakdown = build_conference_breakdown(
        teams, auto_bid_ids, at_large_ids, at_large_cutoff
    )

    return bracket


def _apply_conference_separation(bracket):
    for seed in range(1, 17):
        partner_seed = 17 - seed
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
                    _try_swap(bracket, region, team_at_seed, seed)


def _try_swap(bracket, current_region, entry, seed):
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
            if (entry.team.conference != other_at_partner.team.conference and
                    other_at_seed.team.conference != _get_partner_conf(bracket, current_region, partner_seed)):
                bracket.regions[current_region].remove(entry)
                bracket.regions[other_region].remove(other_at_seed)
                entry.region = other_region
                other_at_seed.region = current_region
                bracket.regions[other_region].append(entry)
                bracket.regions[current_region].append(other_at_seed)
                return True
    return False


def _get_partner_conf(bracket, region, partner_seed):
    for entry in bracket.regions.get(region, []):
        if entry.seed == partner_seed:
            return entry.team.conference
    return None


def compute_changes(old_bracket, new_bracket):
    if old_bracket is None:
        return [{"type": "initial", "message": "Initial bracket projection generated"}]

    changes = []
    old_data = old_bracket.get("bracket", {})
    new_data = new_bracket.to_dict()

    old_teams, new_teams = set(), set()
    old_seeds, new_seeds = {}, {}

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

    for name in sorted(new_teams - old_teams):
        changes.append({"type": "added", "team": name,
                        "message": f"{name} added to bracket (Seed {new_seeds.get(name, '?')})"})
    for name in sorted(old_teams - new_teams):
        changes.append({"type": "removed", "team": name,
                        "message": f"{name} removed from bracket"})
    for name in sorted(old_teams & new_teams):
        old_s = old_seeds.get(name, 0)
        new_s = new_seeds.get(name, 0)
        if old_s != new_s:
            direction = "up" if new_s < old_s else "down"
            changes.append({"type": "seed_change", "team": name,
                            "old_seed": old_s, "new_seed": new_s,
                            "message": f"{name} moved {direction}: Seed {old_s} -> Seed {new_s}"})

    return changes
