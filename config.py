import os
from dotenv import load_dotenv

load_dotenv()

# ─── API ───────────────────────────────────────────────────────────────────────
BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
TESTNET          = os.getenv("TESTNET", "true").lower() == "true"

# ─── SYMBOLS ───────────────────────────────────────────────────────────────────
SYMBOLS = ["SOLUSDT", "AVAXUSDT", "DOGEUSDT"]   # Linear perpetuals on Bybit
CATEGORY = "linear"                              # Bybit linear perps

# ─── STRATEGY PARAMS ───────────────────────────────────────────────────────────
DONCHIAN_LEN       = 20
RSI_LEN            = 14
ADX_LEN            = 14
RISK_RR            = 1.0          # 1:1 Risk/Reward
SWING_LOOKBACK     = 10
VOLUME_MULTIPLIER  = 1.0
MAX_TRADES_PER_DAY = 20           # Per symbol

# ─── RISK MANAGEMENT ───────────────────────────────────────────────────────────
RISK_PER_TRADE_USD  = 5.0         # $ risk per trade
POSITION_SIZE_USD   = 3000.0      # Open & close position notional

# ─── TIMEFRAME ─────────────────────────────────────────────────────────────────
KLINE_INTERVAL = "15"             # 15-minute candles (string for pybit)
KLINE_LIMIT    = 100              # How many candles to fetch per poll

# ─── WEB SERVER ────────────────────────────────────────────────────────────────
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000

# ─── DATABASE ──────────────────────────────────────────────────────────────────
DB_PATH = "bot_data.db"

# ─── POLLING ───────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 30        # How often the bot checks for signals