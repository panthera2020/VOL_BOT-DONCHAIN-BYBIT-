import uuid
import json
from datetime import datetime
import database as db
from config import MAX_TRADES_PER_DAY, POSITION_SIZE_USD
import database


class TradeManager:
    """
    Manages active trades in memory + persists to SQLite.
    Acts as single source of truth for what the bot currently holds.
    """

    def __init__(self, bybit_client):
        self.client = bybit_client
        self._open_trades: dict = {}   # trade_id -> trade dict
        self._load_open_trades()

    def _load_open_trades(self):
        """Reload open trades from DB on startup."""
        rows = db.get_open_trades()
        for r in rows:
            self._open_trades[r["trade_id"]] = r
        print(f"[TradeManager] Loaded {len(self._open_trades)} open trades from DB.")

    # ─── CAPACITY CHECKS ───────────────────────────────────────────────────────

    def can_trade(self, symbol: str) -> bool:
        today_count = db.count_today_trades(symbol)
        already_open = any(
            t["symbol"] == symbol for t in self._open_trades.values()
        )
        if already_open:
            db.log_event("INFO", "Already have open position — skipping signal.", symbol)
            return False
        if today_count >= MAX_TRADES_PER_DAY:
            db.log_event("INFO", f"Max {MAX_TRADES_PER_DAY} trades/day reached.", symbol)
            return False
        return True

    # ─── OPEN TRADE ────────────────────────────────────────────────────────────

    def open_trade(self, symbol: str, signal: dict) -> bool:
        side    = "Buy" if signal["signal"] == "long" else "Sell"
        qty     = signal["qty"]
        sl      = signal["sl"]
        tp      = signal["tp"]
        entry   = signal["entry"]

        if qty <= 0:
            db.log_event("ERROR", "Computed qty=0, skipping trade.", symbol)
            return False

        result = self.client.place_market_order(symbol, side, qty, sl, tp)
        if not result:
            db.log_event("ERROR", "Order placement failed, no result returned.", symbol)
            return False

        order_id = result.get("orderId", "")
        trade_id = str(uuid.uuid4())

        trade = {
            "trade_id":      trade_id,
            "symbol":        symbol,
            "side":          signal["signal"],   # 'long' | 'short'
            "status":        "open",
            "entry_price":   entry,
            "sl_price":      sl,
            "tp_price":      tp,
            "qty":           qty,
            "notional_usd":  round(qty * entry, 4),
            "risk_usd":      5.0,
            "open_time":     datetime.utcnow().isoformat(),
            "bybit_order_id": order_id,
            "extra_json":    json.dumps(signal.get("indicators", {})),
        }

        db.insert_trade(trade)
        self._open_trades[trade_id] = trade
        db.log_event("INFO",
            f"Trade OPENED: {signal['signal'].upper()} {qty} @ {entry} | SL={sl} TP={tp}",
            symbol)
        return True

    # ─── SYNC OPEN POSITIONS ───────────────────────────────────────────────────

    def sync_with_exchange(self):
        """
        Checks live positions from Bybit.
        If a trade we think is open no longer has a matching position, mark it closed.
        """
        live_positions = self.client.get_positions()
        live_symbols_with_pos = set()

        for pos in live_positions:
            if float(pos.get("size", 0)) > 0:
                live_symbols_with_pos.add(pos["symbol"])

        closed_ids = []
        for trade_id, trade in self._open_trades.items():
            if trade["symbol"] not in live_symbols_with_pos:
                # Position is gone — closed by SL/TP on exchange
                self._mark_closed_from_exchange(trade_id, trade)
                closed_ids.append(trade_id)

        for tid in closed_ids:
            self._open_trades.pop(tid, None)

    def _mark_closed_from_exchange(self, trade_id: str, trade: dict):
        """Fetch last fill price and compute PnL."""
        ticker = self.client.get_ticker(trade["symbol"])
        exit_price = float(ticker.get("lastPrice", trade["entry_price"]))
        entry = trade["entry_price"]
        qty   = trade["qty"]

        if trade["side"] == "long":
            pnl_usd = (exit_price - entry) * qty
        else:
            pnl_usd = (entry - exit_price) * qty

        pnl_pct = (pnl_usd / (entry * qty)) * 100 if entry and qty else 0

        # Determine close reason
        if exit_price >= trade["tp_price"] * 0.999:
            reason = "tp"
        elif exit_price <= trade["sl_price"] * 1.001:
            reason = "sl"
        else:
            reason = "exchange_closed"

        db.update_trade_closed(trade_id, exit_price, round(pnl_usd, 4),
                               round(pnl_pct, 4), reason)
        db.log_event("INFO",
            f"Trade CLOSED ({reason}): {trade['side'].upper()} {trade['symbol']} "
            f"| Entry={entry} Exit={exit_price} PnL=${pnl_usd:.4f}",
            trade["symbol"])

    # ─── ACCESSORS ─────────────────────────────────────────────────────────────

    def get_open_trades(self) -> list:
        return list(self._open_trades.values())

    def get_open_trade_for_symbol(self, symbol: str):
        for t in self._open_trades.values():
            if t["symbol"] == symbol:
                return t
        return None