import sqlite3
from datetime import datetime

DB_NAME = "trades.db"

def init_db():
    """Initializes the SQLite database and adds settlement columns if missing."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            match_name TEXT,
            market_type TEXT,
            selection TEXT,
            bookmaker TEXT,
            market_odds REAL,
            fair_odds REAL,
            edge_percent REAL,
            stake_inr REAL,
            status TEXT DEFAULT 'PENDING',
            result_score TEXT,
            pnl_inr REAL DEFAULT 0.0
        )
    """)

    # Graceful migration for existing tables created without settlement columns
    cursor.execute("PRAGMA table_info(signals)")
    cols = [row[1] for row in cursor.fetchall()]
    if "status" not in cols:
        cursor.execute("ALTER TABLE signals ADD COLUMN status TEXT DEFAULT 'PENDING'")
    if "result_score" not in cols:
        cursor.execute("ALTER TABLE signals ADD COLUMN result_score TEXT")
    if "pnl_inr" not in cols:
        cursor.execute("ALTER TABLE signals ADD COLUMN pnl_inr REAL DEFAULT 0.0")

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_lookup 
        ON signals (match_name, selection, bookmaker, timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_status 
        ON signals (status)
    """)
    
    conn.commit()
    conn.close()

def log_trade(match_name, market_type, selection, bookmaker, market_odds, fair_odds, edge_percent, stake_inr):
    """Saves an identified +EV signal if not logged in the last 24 hours at the same odds."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT market_odds FROM signals
        WHERE match_name = ? 
          AND selection = ? 
          AND bookmaker = ?
          AND datetime(timestamp) >= datetime('now', '-24 hours')
        ORDER BY id DESC
        LIMIT 1
    """, (match_name, selection, bookmaker))
    
    existing = cursor.fetchone()
    if existing and existing[0] == market_odds:
        conn.close()
        return False
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO signals (
            timestamp, match_name, market_type, selection, 
            bookmaker, market_odds, fair_odds, edge_percent, stake_inr, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
    """, (
        current_time, match_name, market_type, selection,
        bookmaker, market_odds, fair_odds, edge_percent, stake_inr
    ))
    
    conn.commit()
    conn.close()
    return True

def get_pending_trades():
    """Retrieves all trades awaiting settlement."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, match_name, market_type, selection, market_odds, stake_inr
        FROM signals
        WHERE status = 'PENDING'
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_trade_result(trade_id, status, result_score, pnl_inr):
    """Updates a trade row with settlement outcome and profit/loss."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE signals
        SET status = ?, result_score = ?, pnl_inr = ?
        WHERE id = ?
    """, (status, result_score, pnl_inr, trade_id))
    conn.commit()
    conn.close()