"""Configuration constants for Bracketology."""

import os

DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bracketology.db")

# NCAA Tournament structure
TOURNAMENT_FIELD_SIZE = 68
NUM_AUTO_BIDS = 32
NUM_AT_LARGE = 36
NUM_FIRST_FOUR = 8  # 4 games = 8 teams
FIRST_FOUR_AT_LARGE = 4  # last 4 at-large teams
FIRST_FOUR_AUTO_BID = 4  # last 4 auto-bid teams

REGIONS = ["South", "East", "West", "Midwest"]
SEED_LINES = list(range(1, 17))

# Power conferences (P5 / P6 in modern era)
POWER_CONFERENCES = [
    "ACC", "Big 12", "Big Ten", "SEC", "Big East", "Pac-12"
]

# All D1 conferences
ALL_CONFERENCES = [
    "ACC", "American", "Atlantic 10", "Big 12", "Big East", "Big Ten",
    "Big West", "CAA", "C-USA", "Horizon", "Ivy", "MAAC", "MAC",
    "MEAC", "Missouri Valley", "Mountain West", "NEC", "OVC",
    "Pac-12", "Patriot", "SEC", "SoCon", "Southland", "SWAC",
    "Summit", "Sun Belt", "WAC", "WCC", "America East", "ASUN",
    "Big Sky", "Big South"
]

# ESPN API endpoints
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
ESPN_RANKINGS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings"
ESPN_STANDINGS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/standings"
ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams"

# Update schedule
# Normal: daily at 8am (handled by CronTrigger in scheduler.py)
# March: hourly (handled by IntervalTrigger in scheduler.py)

# Lock/Bubble thresholds (ranking position)
LOCK_THRESHOLD = 30       # top 30 in NET = likely locked
BUBBLE_UPPER = 45         # 31-45 = bubble
BUBBLE_LOWER = 60         # 46-60 = on the outside looking in
