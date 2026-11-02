"""
settle_trades.py
Audits trades.db: fetches match scores from the verified API domain,
settles PENDING trades, computes Closing Line Value (CLV), and prints P&L metrics.
Matches confirmed table schema.
"""

import os
import sys
import sqlite3
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

API_KEY = (os.getenv("ODDS_API_KEY") or "").strip()
DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")

if not API_KEY:
    print("[!] Missing ODDS_API_KEY in .env")
    sys.exit(1)

TARGET_LEAGUES = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league"
]


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_completed_scores(sport_key: str, days_from: int = 3) -> list:
    """Fetches completed matches and final scores via the verified endpoint."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/"
    params = {
        "apiKey": API_KEY,
        "daysFrom": days_from
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            return res.json()
        return []
    except requests.RequestException as e:
        print(f"[!] Network error fetching scores for {sport_key}: {e}")
        return []


def get_latest_pinnacle_closing(conn, match_id: str, selection: str) -> float:
    """Retrieves the latest pre-kickoff Pinnacle price from odds_snapshots."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT home_odds, draw_odds, away_odds 
            FROM odds_snapshots 
            WHERE match_id = ? AND bookmaker = 'pinnacle'
            ORDER BY timestamp DESC LIMIT 1
        """, (match_id,))
        row = cursor.fetchone()
        if not row:
            return 0.0

        sel_lower = selection.lower()
        if "home" in sel_lower or "1" == sel_lower:
            return float(row["home_odds"])
        elif "draw" in sel_lower or "x" == sel_lower:
            return float(row["draw_odds"])
        elif "away" in sel_lower or "2" == sel_lower:
            return float(row["away_odds"])
    except sqlite3.OperationalError:
        return 0.0
    return 0.0


def determine_winning_selection(scores: list, home_team: str, away_team: str):
    """Evaluates the match winner from the scores array: returns ('Home'|'Draw'|'Away', score_str)."""
    if not scores:
        return None, None

    score_map = {item["name"]: int(item["score"]) for item in scores if "score" in item}
    h_goals = score_map.get(home_team)
    a_goals = score_map.get(away_team)

    if h_goals is None or a_goals is None:
        return None, None

    score_str = f"{h_goals}-{a_goals}"
    if h_goals > a_goals:
        return "Home", score_str
    elif a_goals > h_goals:
        return "Away", score_str
    return "Draw", score_str


def settle_pending_trades():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, match_id, home_team, away_team, 
               selection, odds, stake 
        FROM trades 
        WHERE status = 'PENDING'
    """)
    pending = cursor.fetchall()

    if not pending:
        print("✅ No PENDING trades requiring settlement in trades.db.")
        conn.close()
        return

    print(f"🔍 Found {len(pending)} PENDING trades. Fetching scores across all leagues...")

    all_completed_matches = []
    for sport in TARGET_LEAGUES:
        scores = fetch_completed_scores(sport)
        all_completed_matches.extend([m for m in scores if m.get("completed")])

    settled_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for trade in pending:
        match_id = trade["match_id"]
        home_team = trade["home_team"]
        away_team = trade["away_team"]
        trade_id = trade["id"]

        target_match = next(
            (m for m in all_completed_matches 
             if m["id"] == match_id or (m.get("home_team") == home_team and m.get("away_team") == away_team)),
            None
        )

        if not target_match:
            continue

        winner, final_score = determine_winning_selection(
            target_match.get("scores", []),
            target_match.get("home_team"),
            target_match.get("away_team")
        )

        if not winner:
            continue

        trade_sel = trade["selection"].strip()
        is_win = (
            (trade_sel.lower() == winner.lower()) or
            (winner == "Home" and trade_sel == home_team) or
            (winner == "Away" and trade_sel == away_team)
        )

        odds = float(trade["odds"])
        stake = float(trade["stake"])

        if is_win:
            status = "WON"
            profit = round((odds - 1.0) * stake, 2)
        else:
            status = "LOST"
            profit = round(-stake, 2)

        closing_odds = get_latest_pinnacle_closing(conn, match_id, trade_sel)
        if closing_odds > 1.0:
            clv = round(((odds / closing_odds) - 1.0) * 100.0, 2)
        else:
            closing_odds = None
            clv = None

        cursor.execute("""
            UPDATE trades 
            SET status = ?, 
                pnl = ?, 
                profit_loss = ?, 
                final_score = ?, 
                closing_odds = ?, 
                clv_pct = ?, 
                clv_percent = ?, 
                settled_at = ?
            WHERE id = ?
        """, (status, profit, profit, final_score, closing_odds, clv, clv, now_iso, trade_id))

        settled_count += 1
        print(f"  • {home_team} vs {away_team} [{final_score}] | Pick: {trade_sel} -> {status} (₹{profit:+})")

    conn.commit()
    conn.close()
    print(f"\n🎯 Successfully settled {settled_count} trades.")


def print_performance_audit():
    """Calculates overall win rate, P&L, ROI, and average CLV across all settled trades."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT status, stake, COALESCE(profit_loss, pnl, 0.0) as pnl_val, COALESCE(clv_percent, clv_pct) as clv_val 
        FROM trades 
        WHERE status IN ('WON', 'LOST')
    """)
    trades = cursor.fetchall()
    conn.close()

    if not trades:
        print("📊 No settled trades found in database yet.")
        return

    total_trades = len(trades)
    wins = sum(1 for t in trades if t["status"] == "WON")
    total_staked = sum(float(t["stake"]) for t in trades)
    net_pnl = sum(float(t["pnl_val"]) for t in trades)
    roi = (net_pnl / total_staked * 100.0) if total_staked > 0 else 0.0

    clv_values = [float(t["clv_val"]) for t in trades if t["clv_val"] is not None]
    avg_clv = sum(clv_values) / len(clv_values) if clv_values else 0.0

    print("\n" + "=" * 45)
    print("📈 QUANTITATIVE PERFORMANCE AUDIT")
    print("=" * 45)
    print(f"Total Settled Trades : {total_trades}")
    print(f"Win / Loss Record    : {wins}W - {total_trades - wins}L ({wins / total_trades * 100:.1f}%)")
    print(f"Total Turnover       : ₹{total_staked:,.2f}")
    print(f"Net Profit / Loss    : ₹{net_pnl:+,.2f}")
    print(f"Return on Investment : {roi:+.2f}%")
    print(f"Average CLV vs Pinny : {avg_clv:+.2f}%")
    print("=" * 45)

    if avg_clv > 1.5:
        print("✅ ALPHA CONFIRMED: Consistently beating Pinnacle closing lines.")
    elif avg_clv < 0:
        print("⚠️ NEGATIVE CLV: Market moved against signals before kickoff.")


if __name__ == "__main__":
    settle_pending_trades()
    print_performance_audit()