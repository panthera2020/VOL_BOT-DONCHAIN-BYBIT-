import numpy as np
from config import (
    DONCHIAN_LEN, RSI_LEN, ADX_LEN,
    SWING_LOOKBACK, VOLUME_MULTIPLIER, RISK_RR,
    RISK_PER_TRADE_USD, POSITION_SIZE_USD
)


# ─── INDICATORS ────────────────────────────────────────────────────────────────

def compute_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_adx(highs, lows, closes, period: int = 14) -> dict:
    """Returns dict with adx, di_plus, di_minus."""
    n = len(closes)
    if n < period + 1:
        return {"adx": 0, "di_plus": 0, "di_minus": 0}

    tr_list, plus_dm, minus_dm = [], [], []
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        tr_list.append(tr)
        plus_dm.append(up  if up > down and up > 0   else 0)
        minus_dm.append(down if down > up and down > 0 else 0)

    def smooth(arr, p):
        result = []
        s = sum(arr[:p])
        result.append(s)
        for v in arr[p:]:
            s = s - s / p + v
            result.append(s)
        return result

    str14  = smooth(tr_list,  period)
    pdm14  = smooth(plus_dm,  period)
    mdm14  = smooth(minus_dm, period)

    di_plus  = [100 * p / t if t else 0 for p, t in zip(pdm14, str14)]
    di_minus = [100 * m / t if t else 0 for m, t in zip(mdm14, str14)]
    dx = [abs(p - m) / (p + m) * 100 if (p + m) else 0
          for p, m in zip(di_plus, di_minus)]

    adx = np.mean(dx[-period:]) if len(dx) >= period else 0
    return {
        "adx":      round(adx,      2),
        "di_plus":  round(di_plus[-1],  2),
        "di_minus": round(di_minus[-1], 2),
    }


# ─── SIGNAL EVALUATION ─────────────────────────────────────────────────────────

def evaluate_signal(candles: list) -> dict:
    """
    Evaluates Donchian breakout strategy on candle data.

    Returns:
        {
          "signal":     "long" | "short" | "none",
          "entry":      float,
          "sl":         float,
          "tp":         float,
          "qty":        float,
          "indicators": {...}
        }
    """
    if len(candles) < DONCHIAN_LEN + 5:
        return {"signal": "none"}

    closes  = [c["close"]  for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    volumes = [c["volume"] for c in candles]

    # ── Donchian Channel (current bar, previous bar for breakout check) ──
    upper_dc = max(highs[-DONCHIAN_LEN:])
    lower_dc = min(lows[-DONCHIAN_LEN:])
    mid_dc   = (upper_dc + lower_dc) / 2

    # Previous bar's channel (shift by 1)
    upper_dc_prev = max(highs[-(DONCHIAN_LEN + 1):-1])
    lower_dc_prev = min(lows[-(DONCHIAN_LEN + 1):-1])

    # ── RSI ──
    rsi = compute_rsi(closes, RSI_LEN)

    # ── ADX / DI ──
    adx_data = compute_adx(highs, lows, closes, ADX_LEN)

    # ── Volume Spike ──
    vol_ma    = np.mean(volumes[-20:])
    vol_spike = volumes[-1] > vol_ma * VOLUME_MULTIPLIER

    # ── Swing SL levels ──
    swing_low  = min(lows[-SWING_LOOKBACK:])
    swing_high = max(highs[-SWING_LOOKBACK:])

    # ── Trend ──
    current_close = closes[-1]
    bull_trend = current_close > mid_dc
    bear_trend = current_close < mid_dc

    # ── Entry Conditions (mirror Pine Script exactly) ──
    long_cond  = (bull_trend
                  and current_close > upper_dc_prev
                  and rsi > 40
                  and vol_spike)

    short_cond = (bear_trend
                  and current_close < lower_dc_prev
                  and rsi < 60
                  and vol_spike)

    indicators = {
        "upper_dc":    round(upper_dc, 6),
        "lower_dc":    round(lower_dc, 6),
        "mid_dc":      round(mid_dc,   6),
        "rsi":         round(rsi, 2),
        "adx":         adx_data["adx"],
        "di_plus":     adx_data["di_plus"],
        "di_minus":    adx_data["di_minus"],
        "vol_ma":      round(vol_ma, 2),
        "volume":      round(volumes[-1], 2),
        "vol_spike":   vol_spike,
        "bull_trend":  bull_trend,
        "bear_trend":  bear_trend,
        "close":       current_close,
    }

    if long_cond:
        sl = swing_low
        tp = current_close + (current_close - sl) * RISK_RR
        qty = _compute_qty(current_close, sl)
        return {"signal": "long",  "entry": current_close,
                "sl": sl, "tp": tp, "qty": qty, "indicators": indicators}

    if short_cond:
        sl = swing_high
        tp = current_close - (sl - current_close) * RISK_RR
        qty = _compute_qty(current_close, sl)
        return {"signal": "short", "entry": current_close,
                "sl": sl, "tp": tp, "qty": qty, "indicators": indicators}

    return {"signal": "none", "indicators": indicators}


def _compute_qty(entry: float, sl: float) -> float:
    """
    qty = risk_per_trade / abs(entry - sl)
    Then check it doesn't exceed POSITION_SIZE_USD / entry.
    """
    risk_distance = abs(entry - sl)
    if risk_distance == 0:
        return 0.0

    qty_by_risk = RISK_PER_TRADE_USD / risk_distance
    qty_by_size = POSITION_SIZE_USD / entry

    return round(min(qty_by_risk, qty_by_size), 6)