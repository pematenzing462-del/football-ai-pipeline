"""
main.py
Core quantitative football scanner (1X2 + Over/Under 2.5 Goals).
Includes Shin's de-vigging, exchange commission haircuts, regional bookmaker filtering,
and Pinnacle line-velocity (Steam) verification.
"""

import os
import sys
import math
import sqlite3
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

from alerts import send_telegram_trade_alert as send_trade_alert

load_dotenv()

ODDS_API_KEY = (os.getenv("ODDS_API_KEY") or "").strip()
DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")

if not ODDS_API_KEY:
    print("[!] Missing ODDS_API_KEY in environment variables or .env file. Skipping scan.")
    sys.exit(0)

TARGET_LEAGUES = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league",
    "soccer_efl_champ",            # English Championship (Midweek action)
    "soccer_netherlands_eredivisie"  # Dutch Eredivisie (Midweek action)
]
