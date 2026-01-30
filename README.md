# Bracketology

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

By default the app runs on `http://127.0.0.1:5000`. You can override settings
with environment variables (see `.env.example` for a template). 

## Rating configuration

The composite rating is built from weighted component scores in
`app/rating_config.py`. Weights in `RATING_WEIGHTS` sum to `1.0`, so the
resulting rating is designed to stay on a roughly 0–100 scale. Adjust the
component helpers in the same module to tune the formula, and keep the
fallback logic intact for missing/NR stats. (See `app/ratings.py` for how
components are assembled.)

## Scoreboard API

`GET /api/scoreboard` returns the prior day's ESPN scoreboard (America/New_York
timezone). You can request a specific date with `GET /api/scoreboard?date=YYYYMMDD`.
The response format is:

```json
{
  "date": "YYYYMMDD",
  "games": [
    {
      "id": "401...",
      "date": "YYYY-MM-DD",
      "status": "Final",
      "start_time": "2024-11-18T02:00Z",
      "home": {"id": 123, "name": "Home", "score": 72},
      "away": {"id": 456, "name": "Away", "score": 68},
      "conference_game": false,
      "neutral_site": false
    }
  ]
}
```

## Deployment readiness

See `DEPLOYMENT.md` for a safe deployment checklist and hardening steps.
