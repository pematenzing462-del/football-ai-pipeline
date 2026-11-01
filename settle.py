import os
import requests
from dotenv import load_dotenv
from database import init_db, get_pending_trades, update_trade_result

# 1. Environment & DB Setup
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("Error: ODDS_API_KEY not found in .env!")
    exit()

init_db()

# Multi-League Roster
ACTIVE_SPORTS = [
    {"key": "soccer_epl", "name": "English Premier League"},
    {"key": "soccer_spain_la_liga", "name": "Spanish La Liga"}
]

EXCHANGE_COMMISSION = 0.02

def calculate_clv(entry_odds, closing_odds):
    """
    Computes Closing Line Value percentage:
    ((entry_odds / closing_odds) - 1.0) * 100
    """
    if not closing_odds or closing_odds <= 1.0 or entry_odds <= 1.0:
        return None
    return round(((entry_odds / closing_odds) - 1.0) * 100.0, 2)

def extract_closing_odds(event_data, market_type, selection, bookmaker_name):
    """Extracts closing odds for 1X2, DRAW-SNIPER, or Totals."""
    bookmakers = event_data.get("bookmakers", [])
    if not bookmakers:
        return None

    target_book = next((b for b in bookmakers if b.get("title") == bookmaker_name), bookmakers[0])
    
    for market in target_book.get("markets", []):
        m_key = market.get("key")
        
        # 1X2 Match Odds and DRAW-SNIPER both pull from h2h market
        if ("1X2" in market_type or "SNIPER" in market_type or "h2h" in m_key) and m_key == "h2h":
            clean_sel = selection.replace("Lay ", "").replace("(Sniper)", "").strip()
            for outcome in market.get("outcomes", []):
                out_name = outcome.get("name", "")
                if out_name in clean_sel or clean_sel in out_name:
                    return outcome.get("price")

        # Over 2.5 Goals Totals
        elif "Totals" in market_type and m_key == "totals":
            for outcome in market.get("outcomes", []):
                if outcome.get("name") == "Over" and outcome.get("point") == 2.5:
                    return outcome.get("price")

    return None

def fetch_completed_matches():
    """Queries The Odds API for completed scores across EPL and La Liga."""
    completed_matches = {}

    for sport in ACTIVE_SPORTS:
        sport_key = sport["key"]
        league_name = sport["name"]
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/?apiKey={API_KEY}&daysFrom=3"
        
        try:
            res = requests.get(url, timeout=10)
        except Exception as e:
            print(f"Failed to fetch scores for {league_name}: {e}")
            continue

        if res.status_code != 200:
            print(f"API Error ({league_name}): {res.status_code}")
            continue

        events = res.json()
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
                completed_matches[match_key] = {
                    "score": (h_score, a_score),
                    "event_data": ev,
                    "league": league_name
                }

    return completed_matches

def settle_trades():
    pending = get_pending_trades()
    if not pending:
        print("No pending trades to settle in trades.db.")
        return

    print(f"Found {len(pending)} pending trades in trades.db.")
    print("Fetching scores from EPL and La Liga feeds...")
    
    completed_matches = fetch_completed_matches()
    print(f"Loaded {len(completed_matches)} completed fixtures from the last 3 days.")

    settled_count = 0
    total_pnl = 0.0

    for trade in pending:
        match_key = trade["match_name"].lower().strip()
        
        if match_key not in completed_matches:
            continue

        match_info = completed_matches[match_key]
        h_score, a_score = match_info["score"]
        score_str = f"{h_score}-{a_score}"
        league_label = match_info["league"]
        
        m_type = trade["market_type"]
        selection = trade["selection"]
        odds = trade["market_odds"]
        stake = trade["stake_inr"]
        bookmaker = trade["bookmaker"]

        # 1. Determine actual match outcome
        event_happened = False
        if "Home Win" in selection:
            event_happened = (h_score > a_score)
        elif "Away Win" in selection:
            event_happened = (a_score > h_score)
        elif "Draw" in selection:
            event_happened = (h_score == a_score)
        elif "Over 2.5" in selection:
            event_happened = ((h_score + a_score) > 2.5)

        # 2. Settle BACK vs LAY rules
        won = False
        pnl = 0.0

        if "LAY" in m_type:
            if not event_happened:
                won = True
                pnl = round(stake * (1.0 - EXCHANGE_COMMISSION), 2)
                status = "WON"
            else:
                liability = stake * (odds - 1.0)
                pnl = round(-liability, 2)
                status = "LOST"
        else:
            # Covers 1X2-BACK, Totals-BACK, and DRAW-SNIPER
            if event_happened:
                won = True
                pnl = round(stake * (odds - 1.0), 2)
                status = "WON"
            else:
                pnl = round(-stake, 2)
                status = "LOST"

        # 3. Compute Closing Line Value
        closing_odds = extract_closing_odds(match_info["event_data"], m_type, selection, bookmaker)
        clv_pct = calculate_clv(odds, closing_odds)

        # 4. Commit results to trades.db
        update_trade_result(
            trade_id=trade["id"],
            status=status,
            score=score_str,
            pnl_inr=pnl,
            closing_odds=closing_odds,
            clv_percent=clv_pct
        )

        settled_count += 1
        total_pnl += pnl

        clv_display = f"+{clv_pct}%" if (clv_pct is not None and clv_pct > 0) else f"{clv_pct}%"
        print(f"[{status}] [{league_label}] {trade['match_name']} ({score_str})")
        print(f"  Market Type : {m_type} | Selection: {selection} @ {odds:.2f} ({bookmaker})")
        print(f"  Closing Odds: {closing_odds if closing_odds else 'N/A'} | CLV: {clv_display if clv_pct is not None else 'N/A'}")
        print(f"  Stake (₹)   : ₹{stake:,.2f} | Net Realized P&L: ₹{pnl:+,.2f}")
        print("-" * 65)

    if settled_count == 0:
        print("Pending fixtures are either still active, unplayed, or not yet marked complete by the API.")
    else:
        print(f"\nSettlement complete: {settled_count} trades settled.")
        print(f"Total Session Realized P&L: ₹{total_pnl:+,.2f}")

if __name__ == "__main__":
    settle_trades()