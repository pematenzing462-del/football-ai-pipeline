import os
import requests
from dotenv import load_dotenv
from database import init_db, get_pending_trades, update_trade_result

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("Error: ODDS_API_KEY not found in .env!")
    exit()

init_db()

SPORT = "soccer_epl"
# Look back up to 3 days for completed scores (The Odds API default is 3 days)
SCORES_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/scores/?apiKey={API_KEY}&daysFrom=3"

def settle_trades():
    pending = get_pending_trades()
    if not pending:
        print("No pending trades to settle.")
        return

    print(f"Found {len(pending)} pending trades in trades.db. Fetching live scores...")
    res = requests.get(SCORES_URL)
    
    if res.status_code != 200:
        print(f"Error fetching scores: {res.status_code} - {res.text}")
        return

    events = res.json()
    # Build a lookup mapping: "Home vs Away" -> {home_score, away_score, completed}
    completed_matches = {}
    for ev in events:
        if not ev.get("completed", False):
            continue
            
        home = ev.get("home_team")
        away = ev.get("away_team")
        scores = ev.get("scores")
        
        if not scores:
            continue
            
        h_score, a_score = None, None
        for s in scores:
            if s.get("name") == home:
                h_score = int(s.get("score"))
            elif s.get("name") == away:
                a_score = int(s.get("score"))
                
        if h_score is not None and a_score is not None:
            match_key = f"{home} vs {away}".lower().strip()
            completed_matches[match_key] = (h_score, a_score)

    settled_count = 0
    total_pnl = 0.0

    for trade in pending:
        match_key = trade["match_name"].lower().strip()
        
        if match_key not in completed_matches:
            continue
            
        h_score, a_score = completed_matches[match_key]
        score_str = f"{h_score}-{a_score}"
        
        m_type = trade["market_type"]
        selection = trade["selection"]
        odds = trade["market_odds"]
        stake = trade["stake_inr"]
        
        won = False
        
        # --- Settle 1X2 Markets ---
        if m_type == "1X2":
            if "Home Win" in selection and h_score > a_score:
                won = True
            elif "Away Win" in selection and a_score > h_score:
                won = True
            elif "Draw" in selection and h_score == a_score:
                won = True
                
        # --- Settle Totals Markets ---
        elif m_type == "Totals":
            if "Over 2.5" in selection and (h_score + a_score) > 2.5:
                won = True

        # Calculate P&L in INR
        if won:
            pnl = round(stake * (odds - 1.0), 2)
            status = "WON"
        else:
            pnl = round(-stake, 2)
            status = "LOST"

        update_trade_result(trade["id"], status, score_str, pnl)
        settled_count += 1
        total_pnl += pnl

        print(f"[SETTLED: {status}] {trade['match_name']} ({score_str})")
        print(f"  Selection: {selection} @ {odds:.2f} | Stake: ₹{stake:,.2f} | P&L: ₹{pnl:+,.2f}")

    if settled_count == 0:
        print("Matches with pending trades are either still in progress or scheduled.")
    else:
        print(f"\nSettled {settled_count} trades. Batch P&L: ₹{total_pnl:+,.2f}")

if __name__ == "__main__":
    settle_trades()