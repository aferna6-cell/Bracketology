"""Flask web application for Bracketology."""

import logging
from flask import Flask, render_template, jsonify, request

from app.models import init_db, get_latest_snapshot, get_snapshot_history, get_snapshot_by_id
from app.update import run_update, get_current_bracket
from app.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__,
                template_folder="templates",
                static_folder="static")

    # Initialize database
    init_db()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/bracket")
    def api_bracket():
        """Get the current bracket projection."""
        bracket = get_current_bracket()
        if not bracket:
            return jsonify({"error": "No bracket data available. Trigger an update first."}), 404
        return jsonify(bracket)

    @app.route("/api/update", methods=["POST"])
    def api_update():
        """Trigger a manual bracket update."""
        result = run_update()
        if result:
            return jsonify({"status": "ok", "changes": result.get("changes", [])})
        return jsonify({"status": "error", "message": "Update failed"}), 500

    @app.route("/api/history")
    def api_history():
        """Get snapshot history."""
        limit = request.args.get("limit", 30, type=int)
        history = get_snapshot_history(limit)
        return jsonify(history)

    @app.route("/api/snapshot/<int:snapshot_id>")
    def api_snapshot(snapshot_id):
        """Get a specific historical snapshot."""
        snapshot = get_snapshot_by_id(snapshot_id)
        if snapshot:
            return jsonify(snapshot)
        return jsonify({"error": "Snapshot not found"}), 404

    @app.route("/api/compare")
    def api_compare():
        """Compare two snapshots."""
        old_id = request.args.get("old", type=int)
        new_id = request.args.get("new", type=int)
        if not old_id or not new_id:
            return jsonify({"error": "Provide ?old=ID&new=ID"}), 400

        old_snap = get_snapshot_by_id(old_id)
        new_snap = get_snapshot_by_id(new_id)
        if not old_snap or not new_snap:
            return jsonify({"error": "Snapshot not found"}), 404

        return jsonify({
            "old": old_snap,
            "new": new_snap,
        })

    # Start scheduler on first request
    @app.before_request
    def _start_scheduler_once():
        if not hasattr(app, '_scheduler_started'):
            app._scheduler_started = True
            try:
                start_scheduler()
            except Exception as e:
                logger.warning(f"Scheduler start failed: {e}")

    return app
