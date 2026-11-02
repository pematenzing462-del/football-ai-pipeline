"""
database.py
SQLite persistence layer for tracking trade lifecycle,
historical odds snapshots, execution parameters, and realized P&L.
"""

import sqlite3
import os
from datetime import datetime, timedelta

DB_NAME = "trades.db"

def get_connection():
    """Returns a SQLite connection instance."""
    return sqlite3.connect(DB_NAME)

def initialize_database():
    """
    Initializes the SQLite database and sets up tables:
    1. trades: stores executed trade tickets
    2. odds_snapshots: stores timestamped odds across books for velocity tracking
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                commence_time TEXT NOT NULL,
                selection TEXT NOT NULL,
                odds REAL NOT NULL,
                fair_odds REAL NOT NULL,
                stake REAL NOT NULL,
                edge_pct REAL NOT NULL,
                status TEXT DEFAULT 'PENDING',
                closing_odds REAL,
                clv_pct REAL,
                final_score TEXT,
                pnl REAL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                settled_at TEXT,
                UNIQUE(match_id, selection)
            )
        """)

        # Odds snapshots table for steam move / velocity detection
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                bookmaker TEXT NOT NULL,
                selection TEXT NOT NULL,
                odds REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        # Index for rapid lookups on match + selection + time
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_lookup 
            ON odds_snapshots (match_id, bookmaker, selection, timestamp)
        """)

        conn.commit()

def log_odds_snapshot(match_id: str, bookmaker: str, selection: str, odds: float):
    """Logs a single bookmaker price observation with a timestamp."""
    if odds <= 1.0:
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO odds_snapshots (match_id, bookmaker, selection, odds, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (match_id, bookmaker.lower(), selection, odds, now_str))
        conn.commit()

def get_recent_pinnacle_odds(match_id: str, selection: str, lookback_minutes: int = 60):
    """
    Retrieves the oldest recorded Pinnacle odds for a match/selection 
    within the lookback window to calculate delta velocity.
    """
    cutoff_time = (datetime.now() - timedelta(minutes=lookback_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT odds, timestamp FROM odds_snapshots
            WHERE match_id = ? 
              AND bookmaker = 'pinnacle'
              AND selection = ?
              AND timestamp >= ?
            ORDER BY timestamp ASC
            LIMIT 1
        """, (match_id, selection, cutoff_time))
        row = cursor.fetchone()
        if row:
            return float(row[0]), row[1]
    return None, None

def log_executed_trade(
    match_id: str,
    home_team: str,
    away_team: str,
    commence_time: str,
    selection: str,
    odds: float,
    fair_odds: float,
    stake: float,
    edge_pct: float
):
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO trades (
                    match_id, home_team, away_team, commence_time,
                    selection, odds, fair_odds, stake, edge_pct,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (
                match_id, home_team, away_team, commence_time,
                selection, odds, fair_odds, stake, edge_pct,
                created_at
            ))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            print(f"[!] Database error on log_executed_trade: {e}")
            return False

def get_pending_trades():
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE status = 'PENDING'")
        return [dict(row) for row in cursor.fetchall()]

def settle_trade(trade_id: int, status: str, final_score: str, pnl: float, closing_odds: float = None):
    settled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        clv_pct = None
        if closing_odds and closing_odds > 1.0:
            cursor.execute("SELECT odds FROM trades WHERE id = ?", (trade_id,))
            row = cursor.fetchone()
            if row:
                taken_odds = row[0]
                clv_pct = round(((taken_odds / closing_odds) - 1.0) * 100.0, 2)

        cursor.execute("""
            UPDATE trades
            SET status = ?,
                final_score = ?,
                pnl = ?,
                closing_odds = ?,
                clv_pct = ?,
                settled_at = ?
            WHERE id = ?
        """, (status, final_score, pnl, closing_odds, clv_pct, settled_at, trade_id))
        conn.commit()

if __name__ == "__main__":
    initialize_database()
    print("Database schema verified: 'trades' and 'odds_snapshots' ready.")