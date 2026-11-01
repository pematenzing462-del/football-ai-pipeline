import sqlite3

DB_NAME = "trades.db"

def init_db():
    """Initializes the database schema and migrates columns if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Create baseline table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            match_name TEXT,
            market_type TEXT,
            selection TEXT,
            bookmaker TEXT,
            market_odds REAL,
            fair_odds REAL,
            edge_percent REAL,
            stake_inr REAL,
            closing_odds REAL DEFAULT NULL,
            clv_percent REAL DEFAULT NULL,
            status TEXT DEFAULT 'PENDING',
            score TEXT DEFAULT NULL,
            pnl_inr REAL DEFAULT 0.0
        )
    """)
    conn.commit()

    # Safely migrate existing databases if columns are missing
    cursor.execute("PRAGMA table_info(trades)")
    columns = [col[1] for col in cursor.fetchall()]

    if "closing_odds" not in columns:
        cursor.execute("ALTER TABLE trades ADD COLUMN closing_odds REAL DEFAULT NULL")
    if "clv_percent" not in columns:
        cursor.execute("ALTER TABLE trades ADD COLUMN clv_percent REAL DEFAULT NULL")

    conn.commit()
    conn.close()

def log_trade(match_name, market_type, selection, bookmaker, market_odds, fair_odds, edge_percent, stake_inr):
    """Logs a trade if it hasn't been logged in the past 24 hours (deduplication)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id FROM trades 
        WHERE match_name = ? AND market_type = ? AND selection = ? AND bookmaker = ?
        AND timestamp >= datetime('now', '-24 hours')
    """, (match_name, market_type, selection, bookmaker))
    
    existing = cursor.fetchone()

    if existing:
        conn.close()
        return False  # Duplicate signal

    cursor.execute("""
        INSERT INTO trades (
            match_name, market_type, selection, bookmaker,
            market_odds, fair_odds, edge_percent, stake_inr, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
    """, (match_name, market_type, selection, bookmaker, market_odds, fair_odds, edge_percent, stake_inr))

    conn.commit()
    conn.close()
    return True

def get_pending_trades():
    """Fetches all unsettled trades for matching against final scores and closing lines."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM trades 
        WHERE status = 'PENDING'
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def update_trade_result(trade_id, status, score, pnl_inr, closing_odds=None, clv_percent=None):
    """Updates match result, realized P&L, and closing line value metrics."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE trades 
        SET status = ?, score = ?, pnl_inr = ?, closing_odds = ?, clv_percent = ?
        WHERE id = ?
    """, (status, score, pnl_inr, closing_odds, clv_percent, trade_id))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database trades.db initialized with CLV columns successfully.")