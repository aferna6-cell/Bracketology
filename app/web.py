"""Flask web application for Bracketology."""

import json
import logging
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, render_template, jsonify, request, Response

from app.models import (
    init_db, get_latest_snapshot, get_snapshot_history, get_snapshot_by_id,
    get_watchlist, add_to_watchlist, remove_from_watchlist,
)
from app.data_ingestion import fetch_scoreboard
from app.update import run_update, get_current_bracket, get_all_teams
from app.scheduler import start_scheduler

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    init_db()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/bracket")
    def api_bracket():
        bracket = get_current_bracket()
        if not bracket:
            return jsonify({"error": "No bracket data yet. Click Update Now or wait for auto-load."}), 404
        return jsonify(bracket)

    @app.route("/api/update", methods=["POST"])
    def api_update():
        result = run_update()
        return jsonify(result)

    @app.route("/api/history")
    def api_history():
        limit = request.args.get("limit", 30, type=int)
        return jsonify(get_snapshot_history(limit))

    @app.route("/api/snapshot/<int:snapshot_id>")
    def api_snapshot(snapshot_id):
        snapshot = get_snapshot_by_id(snapshot_id)
        if snapshot:
            return jsonify(snapshot)
        return jsonify({"error": "Snapshot not found"}), 404

    @app.route("/api/compare")
    def api_compare():
        old_id = request.args.get("old", type=int)
        new_id = request.args.get("new", type=int)
        if not old_id or not new_id:
            return jsonify({"error": "Provide ?old=ID&new=ID"}), 400
        old_snap = get_snapshot_by_id(old_id)
        new_snap = get_snapshot_by_id(new_id)
        if not old_snap or not new_snap:
            return jsonify({"error": "Snapshot not found"}), 404
        return jsonify({"old": old_snap, "new": new_snap})

    @app.route("/api/scoreboard")
    def api_scoreboard():
        date_param = request.args.get("date")
        date_key = date_param or _yesterday_key()
        if date_param and not _valid_scoreboard_date(date_param):
            return jsonify({
                "date": date_key,
                "games": [],
                "error": "Invalid date format. Use YYYYMMDD.",
            })
        try:
            games = fetch_scoreboard(date_key)
            return jsonify({"date": date_key, "games": games})
        except Exception as exc:
            logger.error(f"Scoreboard fetch failed: {exc}")
            return jsonify({
                "date": date_key,
                "games": [],
                "error": "Scoreboard unavailable.",
            }), 200

    # Team detail modal
    @app.route("/api/team/<int:team_id>")
    def api_team_detail(team_id):
        teams = get_all_teams()
        for t in teams:
            if t.id == team_id:
                return jsonify(t.to_detail_dict())
        return jsonify({"error": "Team not found"}), 404

    # Watchlist
    @app.route("/api/watchlist")
    def api_watchlist():
        return jsonify(list(get_watchlist()))

    @app.route("/api/watchlist/<int:team_id>", methods=["POST"])
    def api_watchlist_add(team_id):
        add_to_watchlist(team_id)
        return jsonify({"status": "ok"})

    @app.route("/api/watchlist/<int:team_id>", methods=["DELETE"])
    def api_watchlist_remove(team_id):
        remove_from_watchlist(team_id)
        return jsonify({"status": "ok"})

    # What-if simulator
    @app.route("/api/whatif", methods=["POST"])
    def api_whatif():
        """Simulate bracket changes by modifying a team's wins/losses."""
        data = request.get_json() or {}
        team_id = data.get("team_id")
        add_wins = data.get("add_wins", 0)
        add_losses = data.get("add_losses", 0)

        if not team_id:
            return jsonify({"error": "Provide team_id"}), 400

        import copy
        from app.bracket_generator import build_bracket

        teams = get_all_teams()
        sim_teams = []
        for t in teams:
            st = copy.copy(t)
            if st.id == team_id:
                st.wins += add_wins
                st.losses += add_losses
            sim_teams.append(st)

        bracket = build_bracket(sim_teams)
        return jsonify(bracket.to_dict())

    # RSS/JSON feed
    @app.route("/api/feed.json")
    def api_feed_json():
        history = get_snapshot_history(10)
        feed = {
            "title": "Bracketology - NCAA Tournament Projection",
            "updated": history[0]["timestamp"] if history else "",
            "entries": [],
        }
        for h in history:
            changes = h.get("changes", [])
            feed["entries"].append({
                "id": h["id"],
                "timestamp": h["timestamp"],
                "summary": "; ".join(c.get("message", "") for c in changes[:5]),
                "change_count": len(changes),
            })
        return jsonify(feed)

    @app.route("/api/feed.rss")
    def api_feed_rss():
        history = get_snapshot_history(10)
        items = ""
        for h in history:
            changes = h.get("changes", [])
            desc = "\n".join(c.get("message", "") for c in changes[:10])
            items += f"""<item>
                <title>Bracket Update - {h['timestamp']}</title>
                <description><![CDATA[{desc or 'No changes'}]]></description>
                <pubDate>{h['timestamp']}</pubDate>
                <guid>{h['id']}</guid>
            </item>"""
        rss = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
        <channel>
            <title>Bracketology</title>
            <description>NCAA Tournament Bracket Projections</description>
            {items}
        </channel>
        </rss>"""
        return Response(rss, mimetype="application/rss+xml")

    # Auto-update on startup if no data exists
    @app.before_request
    def _startup_once():
        if not hasattr(app, '_started'):
            app._started = True
            try:
                start_scheduler()
            except Exception as e:
                logger.warning(f"Scheduler start failed: {e}")
            # Auto-fetch data if DB is empty
            if not get_latest_snapshot():
                logger.info("No bracket data found. Running initial update in background...")
                threading.Thread(target=run_update, daemon=True).start()

    return app


def _yesterday_key() -> str:
    now = datetime.now(ZoneInfo("America/New_York"))
    return (now - timedelta(days=1)).strftime("%Y%m%d")


def _valid_scoreboard_date(value: str) -> bool:
    if len(value) != 8 or not value.isdigit():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False
