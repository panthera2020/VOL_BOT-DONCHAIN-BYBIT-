import sqlite3
import json
from datetime import datetime
from config import DB_PATH


def get_conn():
    # Give SQLite time to wait on busy writes instead of failing immediately.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id        TEXT UNIQUE,
            symbol          TEXT NOT NULL,
            side            TEXT NOT NULL,          -- 'long' | 'short'
            status          TEXT NOT NULL,          -- 'open' | 'closed'
            entry_price     REAL,
            exit_price      REAL,
            sl_price        REAL,
            tp_price        REAL,
            qty             REAL,
            notional_usd    REAL,
            risk_usd        REAL,
            pnl_usd         REAL,
            pnl_pct         REAL,
            open_time       TEXT,
            close_time      TEXT,
            close_reason    TEXT,                   -- 'tp' | 'sl' | 'manual'
            bybit_order_id  TEXT,
            extra_json      TEXT
        );

        CREATE TABLE IF NOT EXISTS bot_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at     TEXT NOT NULL,
            total_trades    INTEGER,
            winning_trades  INTEGER,
            losing_trades   INTEGER,
            total_pnl       REAL,
            win_rate        REAL,
            volume_usd      REAL,
            balance_usd     REAL
        );

        CREATE TABLE IF NOT EXISTS bot_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at   TEXT NOT NULL,
            level       TEXT,
            symbol      TEXT,
            message     TEXT
        );
    """)

    conn.commit()
    conn.close()
    print("[DB] Initialized.")


# ─── TRADE CRUD ────────────────────────────────────────────────────────────────

def insert_trade(trade: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO trades
        (trade_id, symbol, side, status, entry_price, sl_price, tp_price,
         qty, notional_usd, risk_usd, open_time, bybit_order_id, extra_json)
        VALUES (:trade_id, :symbol, :side, :status, :entry_price, :sl_price,
                :tp_price, :qty, :notional_usd, :risk_usd, :open_time,
                :bybit_order_id, :extra_json)
    """, trade)
    conn.commit()
    conn.close()


def update_trade_closed(trade_id: str, exit_price: float, pnl_usd: float,
                        pnl_pct: float, close_reason: str):
    conn = get_conn()
    conn.execute("""
        UPDATE trades
        SET status='closed', exit_price=?, pnl_usd=?, pnl_pct=?,
            close_time=?, close_reason=?
        WHERE trade_id=?
    """, (exit_price, pnl_usd, pnl_pct,
          datetime.utcnow().isoformat(), close_reason, trade_id))
    conn.commit()
    conn.close()


def get_open_trades():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_trades(limit=200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_closed_trades(limit=200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE status='closed' ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_today_trades(symbol: str) -> int:
    conn = get_conn()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    count = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE symbol=? AND open_time LIKE ?",
        (symbol, f"{today}%")
    ).fetchone()[0]
    conn.close()
    return count


# ─── STATS ─────────────────────────────────────────────────────────────────────

def compute_stats(balance_usd: float = 0.0) -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT pnl_usd, notional_usd FROM trades WHERE status='closed'"
    ).fetchall()
    conn.close()

    total   = len(rows)
    winners = sum(1 for r in rows if (r["pnl_usd"] or 0) > 0)
    losers  = sum(1 for r in rows if (r["pnl_usd"] or 0) <= 0)
    total_pnl   = sum(r["pnl_usd"] or 0 for r in rows)
    volume  = sum(r["notional_usd"] or 0 for r in rows)
    win_rate = (winners / total * 100) if total else 0

    return {
        "total_trades":   total,
        "winning_trades": winners,
        "losing_trades":  losers,
        "total_pnl":      round(total_pnl, 4),
        "win_rate":       round(win_rate, 2),
        "volume_usd":     round(volume, 2),
        "balance_usd":    round(balance_usd, 4),
    }


# ─── LOGS ──────────────────────────────────────────────────────────────────────

def log_event(level: str, message: str, symbol: str = ""):
    conn = None
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO bot_log (logged_at, level, symbol, message) VALUES (?,?,?,?)",
            (datetime.utcnow().isoformat(), level, symbol, message)
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        # Never let logging crash request handlers/strategy loop.
        print(f"[DB][WARN] log_event skipped due to DB lock: {e}")
    finally:
        if conn:
            conn.close()


def get_recent_logs(limit=100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bot_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]