from pybit.unified_trading import HTTP
from config import BYBIT_API_KEY, BYBIT_API_SECRET, TESTNET, CATEGORY
import database as db


class BybitClient:
    def __init__(self):
        self.session = HTTP(
            testnet=TESTNET,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET,
        )
        print(f"[Bybit] Connected. Testnet={TESTNET}")

    # ─── MARKET DATA ───────────────────────────────────────────────────────────

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> list:
        """
        Returns list of dicts: open, high, low, close, volume (newest last).
        """
        try:
            resp = self.session.get_kline(
                category=CATEGORY,
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
            raw = resp["result"]["list"]
            # Bybit returns newest first — reverse so oldest is index 0
            raw = list(reversed(raw))
            candles = []
            for c in raw:
                candles.append({
                    "ts":     int(c[0]),
                    "open":   float(c[1]),
                    "high":   float(c[2]),
                    "low":    float(c[3]),
                    "close":  float(c[4]),
                    "volume": float(c[5]),
                })
            return candles
        except Exception as e:
            db.log_event("ERROR", f"get_klines failed: {e}", symbol)
            return []

    def get_ticker(self, symbol: str) -> dict:
        try:
            resp = self.session.get_tickers(category=CATEGORY, symbol=symbol)
            return resp["result"]["list"][0]
        except Exception as e:
            db.log_event("ERROR", f"get_ticker failed: {e}", symbol)
            return {}

    # ─── ACCOUNT ───────────────────────────────────────────────────────────────

    def get_wallet_balance(self) -> float:
        try:
            resp = self.session.get_wallet_balance(accountType="UNIFIED")
            coins = resp["result"]["list"][0]["coin"]
            for coin in coins:
                if coin["coin"] == "USDT":
                    return float(coin["walletBalance"])
            return 0.0
        except Exception as e:
            db.log_event("ERROR", f"get_wallet_balance failed: {e}")
            return 0.0

    def get_positions(self, symbol: str = "") -> list:
        try:
            kwargs = {"category": CATEGORY, "settleCoin": "USDT"}
            if symbol:
                kwargs["symbol"] = symbol
            resp = self.session.get_positions(**kwargs)
            return resp["result"]["list"]
        except Exception as e:
            db.log_event("ERROR", f"get_positions failed: {e}", symbol)
            return []

    # ─── INSTRUMENT INFO (for qty precision) ───────────────────────────────────

    def get_instrument_info(self, symbol: str) -> dict:
        try:
            resp = self.session.get_instruments_info(
                category=CATEGORY, symbol=symbol
            )
            return resp["result"]["list"][0]
        except Exception as e:
            db.log_event("ERROR", f"get_instrument_info failed: {e}", symbol)
            return {}

    def get_qty_precision(self, symbol: str) -> dict:
        """Returns min_qty, qty_step, price_scale."""
        info = self.get_instrument_info(symbol)
        lot  = info.get("lotSizeFilter", {})
        price = info.get("priceFilter", {})
        return {
            "min_qty":     float(lot.get("minOrderQty", 0.01)),
            "qty_step":    float(lot.get("qtyStep", 0.01)),
            "min_notional":float(lot.get("minNotionalValue", 1)),
            "tick_size":   float(price.get("tickSize", 0.01)),
        }

    def round_qty(self, qty: float, step: float) -> float:
        import math
        factor = 1 / step
        return math.floor(qty * factor) / factor

    def round_price(self, price: float, tick: float) -> float:
        import math
        factor = 1 / tick
        return math.floor(price * factor) / factor

    # ─── ORDERS ────────────────────────────────────────────────────────────────

    def place_market_order(self, symbol: str, side: str, qty: float,
                           sl: float, tp: float) -> dict:
        """
        side: 'Buy' | 'Sell'
        sl/tp: float prices
        """
        try:
            precision = self.get_qty_precision(symbol)
            qty = self.round_qty(qty, precision["qty_step"])
            sl  = self.round_price(sl,  precision["tick_size"])
            tp  = self.round_price(tp,  precision["tick_size"])

            resp = self.session.place_order(
                category=CATEGORY,
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                stopLoss=str(sl),
                takeProfit=str(tp),
                slTriggerBy="MarkPrice",
                tpTriggerBy="MarkPrice",
                timeInForce="IOC",
                reduceOnly=False,
            )
            db.log_event("INFO", f"Order placed: {side} {qty} {symbol} SL={sl} TP={tp}", symbol)
            return resp["result"]
        except Exception as e:
            db.log_event("ERROR", f"place_market_order failed: {e}", symbol)
            return {}

    def close_position(self, symbol: str, side: str, qty: float) -> dict:
        """Close an open position (opposite side market order, reduceOnly=True)."""
        close_side = "Sell" if side.lower() == "long" else "Buy"
        try:
            precision = self.get_qty_precision(symbol)
            qty = self.round_qty(qty, precision["qty_step"])
            resp = self.session.place_order(
                category=CATEGORY,
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=str(qty),
                timeInForce="IOC",
                reduceOnly=True,
            )
            db.log_event("INFO", f"Position closed: {close_side} {qty} {symbol}", symbol)
            return resp["result"]
        except Exception as e:
            db.log_event("ERROR", f"close_position failed: {e}", symbol)
            return {}

    def cancel_all_orders(self, symbol: str):
        try:
            self.session.cancel_all_orders(category=CATEGORY, symbol=symbol)
        except Exception as e:
            db.log_event("ERROR", f"cancel_all_orders failed: {e}", symbol)