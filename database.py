import sqlite3
from datetime import datetime

DB_NAME = "trades.db"

def init_db():
    """Initializes the SQLite database and ensures required tables and indexes exist."""
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
            stake_inr REAL
        )
    """)
    
    # Create an index to keep lookup checks fast as the table grows
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_signal_lookup 
        ON signals (match_name, selection, bookmaker, timestamp)
    """)
    
    conn.commit()
    conn.close()

def log_trade(match_name, market_type, selection, bookmaker, market_odds, fair_odds, edge_percent, stake_inr):
    """
    Saves an identified +EV signal into the database ONLY if a duplicate 
    has not already been logged within the last 24 hours at the same odds.
    Returns True if logged, False if skipped as a duplicate.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Check if this exact bet was logged within the last 24 hours
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
    
    # If already logged at identical odds, skip it
    if existing and existing[0] == market_odds:
        conn.close()
        return False
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO signals (
            timestamp, match_name, market_type, selection, 
            bookmaker, market_odds, fair_odds, edge_percent, stake_inr
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        current_time, match_name, market_type, selection,
        bookmaker, market_odds, fair_odds, edge_percent, stake_inr
    ))
    
    conn.commit()
    conn.close()
    return True