"""
Perp Volume Bot - Donchian Edition
Main entry point. Runs the strategy loop + web server in parallel threads.
"""

import time
import threading
from datetime import datetime

from config import SYMBOLS, KLINE_INTERVAL, KLINE_LIMIT, POLL_INTERVAL_SECONDS
import database as db
from bybit_client import BybitClient
from strategy import evaluate_signal
from trade_manager import TradeManager
from web_app import create_app

# ─── GLOBALS ───────────────────────────────────────────────────────────────────
client       : BybitClient   = None
trade_manager: TradeManager  = None
bot_running  : bool          = False


# ─── STRATEGY LOOP ─────────────────────────────────────────────────────────────

def run_strategy_loop():
    global bot_running

    print("[Bot] Strategy loop started.")
    db.log_event("INFO", "Bot started.", "SYSTEM")

    while bot_running:
        try:
            _tick()
        except Exception as e:
            db.log_event("ERROR", f"Unhandled error in tick: {e}", "SYSTEM")
            print(f"[Bot] Tick error: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)

    print("[Bot] Strategy loop stopped.")
    db.log_event("INFO", "Bot stopped.", "SYSTEM")


def _tick():
    print(f"\n[Tick] {datetime.utcnow().isoformat()} UTC")

    # ── 1. Sync open positions with exchange ──────────────────────────────────
    trade_manager.sync_with_exchange()

    # ── 2. Evaluate each symbol ───────────────────────────────────────────────
    for symbol in SYMBOLS:
        try:
            candles = client.get_klines(symbol, KLINE_INTERVAL, KLINE_LIMIT)
            if len(candles) < 30:
                print(f"  [{symbol}] Not enough candles ({len(candles)}), skipping.")
                continue

            result = evaluate_signal(candles)
            ind    = result.get("indicators", {})

            print(
                f"  [{symbol}] close={ind.get('close')} | "
                f"RSI={ind.get('rsi')} | volSpike={ind.get('vol_spike')} | "
                f"signal={result['signal'].upper()}"
            )

            if result["signal"] in ("long", "short"):
                if trade_manager.can_trade(symbol):
                    print(f"  [{symbol}] >>> Opening {result['signal'].upper()} trade")
                    trade_manager.open_trade(symbol, result)
                else:
                    print(f"  [{symbol}] Signal fired but can_trade=False")

        except Exception as e:
            db.log_event("ERROR", f"Symbol loop error: {e}", symbol)
            print(f"  [{symbol}] Error: {e}")


# ─── BOT CONTROL ───────────────────────────────────────────────────────────────

def start_bot():
    global bot_running, client, trade_manager
    if bot_running:
        print("[Bot] Already running.")
        return

    client        = BybitClient()
    trade_manager = TradeManager(client)
    bot_running   = True

    thread = threading.Thread(target=run_strategy_loop, daemon=True)
    thread.start()
    print("[Bot] Started in background thread.")


def stop_bot():
    global bot_running
    bot_running = False
    print("[Bot] Stop signal sent.")


def get_bot_status() -> dict:
    balance = client.get_wallet_balance() if client else 0.0
    stats   = db.compute_stats(balance)
    open_t  = trade_manager.get_open_trades() if trade_manager else []
    return {
        "running":     bot_running,
        "balance":     balance,
        "open_trades": open_t,
        "stats":       stats,
    }


# ─── ENTRY ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()

    # Initialise client + trade manager so web app has access even before start
    client        = BybitClient()
    trade_manager = TradeManager(client)

    # Create Flask app
    app = create_app(
        start_fn=start_bot,
        stop_fn=stop_bot,
        status_fn=get_bot_status,
        trade_manager_ref=lambda: trade_manager,
        client_ref=lambda: client,
    )

    print(f"[Web] Dashboard → http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)