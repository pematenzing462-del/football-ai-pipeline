"""
settle.py
Nightly settlement engine.
Fetches completed match scores from The Odds API, settles pending trades,
computes net realized P&L after commission, and updates trades.db.
"""

import os
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv

# Enforce UTF-8 on Windows stdout/stderr
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from database import get_pending_trades, settle_trade

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
COMMISSION_RATE = 0.02

LEAGUES = [
    "soccer_epl",
    "soccer_spain_la_liga"
]

def fetch_completed_scores(sport_key: str, days_from: int = 3):
    """
    Fetches completed game results from The Odds API scores endpoint.
    Retrieves games completed within the last `days_from` days.
    """
    if not API_KEY:
        print("[!] Missing ODDS_API_KEY. Check .env file.")
        return []

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = {
        "apiKey": API_KEY,
        "daysFrom": days_from
    }

    try:
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        status_code = getattr(e.response, "status_code", "Connection Error")
        print(f"[!] Error fetching scores for {sport_key}: HTTP {status_code}")
        return []

def determine_match_result(home_score: int, away_score: int):
    """Returns 'Home', 'Away', or 'Draw'."""
    if home_score > away_score:
        return "Home"
    elif away_score > home_score:
        return "Away"
    return "Draw"

def parse_scores_payload(scores_data: list):
    """
    Builds a normalized lookup map keyed by (home_team, away_team).
    Returns: dict with outcome ('Home'/'Draw'/'Away') and scoreline string.
    """
    completed_map = {}

    for event in scores_data:
        if not event.get("completed", False):
            continue

        scores = event.get("scores")
        if not scores or len(scores) < 2:
            continue

        home_name = event.get("home_team")
        away_name = event.get("away_team")

        h_score = None
        a_score = None

        for s in scores:
            if s.get("name") == home_name:
                h_score = int(s.get("score", 0))
            elif s.get("name") == away_name:
                a_score = int(s.get("score", 0))

        if h_score is not None and a_score is not None:
            res_outcome = determine_match_result(h_score, a_score)
            key = (home_name.strip().lower(), away_name.strip().lower())
            completed_map[key] = {
                "result": res_outcome,
                "score_str": f"{h_score}-{a_score}"
            }

    return completed_map

def run_settlement():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Settlement Engine...")
    
    pending_trades = get_pending_trades()
    if not pending_trades:
        print("[*] No pending trades found in database.")
        return

    print(f"[*] Found {len(pending_trades)} pending trade(s) to audit.")

    # 1. Fetch completed scores across target leagues
    all_completed = {}
    for league in LEAGUES:
        raw_events = fetch_completed_scores(league)
        league_map = parse_scores_payload(raw_events)
        all_completed.update(league_map)

    settled_count = 0

    # 2. Match pending trades against completed fixtures
    for trade in pending_trades:
        h_team = trade["home_team"].strip().lower()
        a_team = trade["away_team"].strip().lower()
        trade_id = trade["id"]
        selection = trade["selection"]
        stake = trade["stake"]
        odds = trade["odds"]

        match_key = (h_team, a_team)
        if match_key not in all_completed:
            continue

        match_info = all_completed[match_key]
        actual_winner = match_info["result"]
        scoreline = match_info["score_str"]

        # Calculate P&L with 2% exchange commission on net profit
        if selection == actual_winner:
            status = "WON"
            gross_profit = stake * (odds - 1.0)
            net_profit = gross_profit * (1.0 - COMMISSION_RATE)
            pnl = round(net_profit, 2)
        else:
            status = "LOST"
            pnl = -round(stake, 2)

        settle_trade(
            trade_id=trade_id,
            status=status,
            final_score=scoreline,
            pnl=pnl
        )

        settled_count += 1
        print(f" [+] Settled #{trade_id}: {trade['home_team']} vs {trade['away_team']} | Pick: {selection} | Score: {scoreline} | Result: {status} ({pnl:+,.2f} INR)")

    print(f"[*] Settlement complete. {settled_count} trade(s) resolved.\n")

if __name__ == "__main__":
    run_settlement()