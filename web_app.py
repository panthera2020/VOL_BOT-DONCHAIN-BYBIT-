from flask import Flask, render_template, jsonify, request
import database as db
from config import SYMBOLS, TESTNET


def create_app(start_fn, stop_fn, status_fn, trade_manager_ref, client_ref):
    app = Flask(__name__)

    # ─── PAGES ─────────────────────────────────────────────────────────────────

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html",
                               symbols=SYMBOLS,
                               testnet=TESTNET)

    # ─── API ───────────────────────────────────────────────────────────────────

    @app.route("/api/status")
    def api_status():
        return jsonify(status_fn())

    @app.route("/api/stats")
    def api_stats():
        client = client_ref()
        balance = client.get_wallet_balance() if client else 0.0
        return jsonify(db.compute_stats(balance))

    @app.route("/api/trades/open")
    def api_open_trades():
        return jsonify(db.get_open_trades())

    @app.route("/api/trades/closed")
    def api_closed_trades():
        limit = int(request.args.get("limit", 200))
        return jsonify(db.get_closed_trades(limit))

    @app.route("/api/trades/all")
    def api_all_trades():
        limit = int(request.args.get("limit", 200))
        return jsonify(db.get_all_trades(limit))

    @app.route("/api/logs")
    def api_logs():
        limit = int(request.args.get("limit", 100))
        return jsonify(db.get_recent_logs(limit))

    @app.route("/api/positions")
    def api_positions():
        client = client_ref()
        if not client:
            return jsonify([])
        positions = client.get_positions()
        return jsonify(positions)

    @app.route("/api/bot/start", methods=["POST"])
    def api_start():
        start_fn()
        return jsonify({"ok": True, "message": "Bot started."})

    @app.route("/api/bot/stop", methods=["POST"])
    def api_stop():
        stop_fn()
        return jsonify({"ok": True, "message": "Bot stopped."})

    return app