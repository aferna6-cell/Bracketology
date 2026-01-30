#!/usr/bin/env python3
"""Quick synthetic check for compute_ratings ordering."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.models import Team
from app.ratings import compute_ratings


def main() -> None:
    teams = [
        Team(
            id=1,
            name="Alpha",
            conference="SEC",
            wins=20,
            losses=3,
            conf_wins=10,
            conf_losses=1,
            net_ranking=5,
            kenpom_ranking=8,
            torvik_ranking=6,
            sagarin_ranking=7,
            quad1_wins=6,
            quad1_losses=2,
            quad2_wins=5,
            quad2_losses=1,
            quad3_losses=0,
            quad4_losses=0,
            sos_ranking=10,
            conference_standing=1,
            road_wins=6,
            road_losses=1,
            vs_ranked_record="4-1",
            streak="W5",
            avg_points_for=82.0,
            avg_points_against=70.0,
        ),
        Team(
            id=2,
            name="Bravo",
            conference="Big East",
            wins=18,
            losses=6,
            conf_wins=9,
            conf_losses=4,
            net_ranking=20,
            kenpom_ranking=25,
            torvik_ranking=18,
            sagarin_ranking=22,
            quad1_wins=3,
            quad1_losses=4,
            quad2_wins=4,
            quad2_losses=2,
            quad3_losses=1,
            quad4_losses=0,
            sos_ranking=35,
            conference_standing=4,
            road_wins=4,
            road_losses=4,
            vs_ranked_record="2-3",
            streak="L1",
            avg_points_for=76.5,
            avg_points_against=72.5,
        ),
        Team(
            id=3,
            name="Charlie",
            conference="WAC",
            wins=14,
            losses=10,
            conf_wins=6,
            conf_losses=6,
            net_ranking=120,
            kenpom_ranking=140,
            torvik_ranking=130,
            sagarin_ranking=150,
            quad1_wins=1,
            quad1_losses=5,
            quad2_wins=2,
            quad2_losses=4,
            quad3_losses=2,
            quad4_losses=1,
            sos_ranking=160,
            conference_standing=7,
            road_wins=3,
            road_losses=6,
            vs_ranked_record="0-2",
            streak="W1",
            avg_points_for=71.0,
            avg_points_against=74.5,
        ),
    ]

    rated = compute_ratings(teams)
    order = [t.name for t in rated]
    assert order == ["Alpha", "Bravo", "Charlie"], f"Unexpected order: {order}"
    print("Ratings OK:", [(t.name, t.rating) for t in rated])


if __name__ == "__main__":
    main()
