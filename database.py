import sqlite3
from datetime import datetime

DB_NAME = "trades.db"

def init_db():
    """Initializes the SQLite database and creates the signals table if not existing."""
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
    conn.commit()
    conn.close()

def log_trade(match_name, market_type, selection, bookmaker, market_odds, fair_odds, edge_percent, stake_inr):
    """Saves an identified +EV signal into the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
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