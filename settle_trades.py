"""
settle_trades.py
Audits trades.db: updates closing lines right before settlement (1X2 + Over/Under 2.5),
fetches match scores via The Odds API, settles PENDING trades, computes Closing Line Value (CLV),
and prints overall + market-segmented P&L metrics.
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
TARGET_TOTAL_LINE = 2.5

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
    "soccer_uefa_europa_conference_league",
    "soccer_efl_champ",              # English Championship
    "soccer_netherlands_eredivisie"  # Dutch Eredivisie
]


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_snapshot_columns():
    """Ensures over_25_odds and under_25_odds exist in odds_snapshots."""
    conn = get_db_connection()
    cursor = conn.cursor()
    for col in ("over_25_odds", "under_25_odds"):
        try:
            cursor.execute(f"ALTER TABLE odds_snapshots ADD COLUMN {col} REAL DEFAULT NULL")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def extract_totals_25(market_obj: dict) -> tuple[float, float]:
    """Extracts Over 2.5 and Under 2.5 decimal odds from a 'totals' market object."""
    if not market_obj:
        return None, None
    over_odds, under_odds = None, None
    for o in market_obj.get("outcomes", []):
        try:
            point = float(o.get("point", 0.0))
            price = float(o.get("price", 0.0))
        except (TypeError, ValueError):
            continue
        if abs(point - TARGET_TOTAL_LINE) < 1e-4 and price > 1.0:
            if o.get("name") == "Over":
                over_odds = price
            elif o.get("name") == "Under":
                under_odds = price
    return over_odds, under_odds


def fetch_live_odds_for_match(sport_key: str, match_id: str):
    """Fetches current live odds (h2h + totals) for a specific match to capture closing lines."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 200:
            for m in res.json():
                if m.get("id") == match_id:
                    return m
    except requests.RequestException:
        pass
    return None


def update_closing_snapshots_before_settling(pending_trades):
    """Pings the API to grab the latest Pinnacle 1X2 and O/U 2.5 lines for pending matches."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()

    seen_matches = set()
    for trade in pending_trades:
        match_id = trade["match_id"]
        if match_id in seen_matches:
            continue
        seen_matches.add(match_id)

        for sport in TARGET_LEAGUES:
            match_data = fetch_live_odds_for_match(sport, match_id)
            if match_data:
                pin_data = next((b for b in match_data.get("bookmakers", []) if b["key"] == "pinnacle"), None)
                if pin_data:
                    pin_markets = {mk["key"]: mk for mk in pin_data.get("markets", [])}
                    h2h = pin_markets.get("h2h")
                    totals = pin_markets.get("totals")

                    h_odds, d_odds, a_odds = None, None, None
                    if h2h:
                        outcomes = {o["name"]: float(o["price"]) for o in h2h.get("outcomes", [])}
                        h_odds = outcomes.get(match_data.get("home_team"))
                        a_odds = outcomes.get(match_data.get("away_team"))
                        d_odds = outcomes.get("Draw")

                    over_25, under_25 = extract_totals_25(totals)

                    if (h_odds and a_odds and d_odds) or (over_25 and under_25):
                        cursor.execute("""
                            INSERT INTO odds_snapshots (
                                match_id, bookmaker, home_odds, draw_odds, away_odds,
                                over_25_odds, under_25_odds, timestamp
                            ) VALUES (?, 'pinnacle', ?, ?, ?, ?, ?, ?)
                        """, (match_id, h_odds, d_odds, a_odds, over_25, under_25, now_iso))
                        conn.commit()
                break
    conn.close()


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


def get_latest_pinnacle_closing(conn, match_id: str, selection: str, home_team: str, away_team: str) -> float:
    """Retrieves the latest pre-kickoff Pinnacle price from odds_snapshots for 1X2 or O/U 2.5."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT home_odds, draw_odds, away_odds, over_25_odds, under_25_odds
            FROM odds_snapshots 
            WHERE match_id = ? AND bookmaker = 'pinnacle'
            ORDER BY id DESC LIMIT 1
        """, (match_id,))
        row = cursor.fetchone()
        if not row:
            return 0.0

        sel_clean = selection.strip()
        sel_lower = sel_clean.lower()

        if sel_clean == home_team or sel_lower in ("home", "1"):
            return float(row["home_odds"]) if row["home_odds"] is not None else 0.0
        elif sel_clean == away_team or sel_lower in ("away", "2"):
            return float(row["away_odds"]) if row["away_odds"] is not None else 0.0
        elif sel_lower in ("draw", "x"):
            return float(row["draw_odds"]) if row["draw_odds"] is not None else 0.0
        elif sel_lower == "over 2.5":
            return float(row["over_25_odds"]) if row["over_25_odds"] is not None else 0.0
        elif sel_lower == "under 2.5":
            return float(row["under_25_odds"]) if row["under_25_odds"] is not None else 0.0
    except sqlite3.OperationalError:
        return 0.0
    return 0.0


def determine_winning_selection(scores: list, home_team: str, away_team: str):
    """Evaluates match winner and total goals: returns ('Home'|'Draw'|'Away', total_goals, score_str)."""
    if not scores:
        return None, None, None

    try:
        score_map = {item["name"]: int(item["score"]) for item in scores if item.get("score") is not None}
    except (ValueError, TypeError):
        return None, None, None

    h_goals = score_map.get(home_team)
    a_goals = score_map.get(away_team)

    if h_goals is None or a_goals is None:
        return None, None, None

    total_goals = h_goals + a_goals
    score_str = f"{h_goals}-{a_goals}"
    if h_goals > a_goals:
        return "Home", total_goals, score_str
    elif a_goals > h_goals:
        return "Away", total_goals, score_str
    return "Draw", total_goals, score_str


def settle_pending_trades():
    ensure_snapshot_columns()
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

    print(f"🔍 Found {len(pending)} PENDING trades. Updating closing lines and fetching scores...")
    
    update_closing_snapshots_before_settling(pending)

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

        winner, total_goals, final_score = determine_winning_selection(
            target_match.get("scores", []),
            target_match.get("home_team"),
            target_match.get("away_team")
        )

        if not winner or total_goals is None:
            continue

        trade_sel = trade["selection"].strip()
        sel_lower = trade_sel.lower()

        if sel_lower == "over 2.5":
            is_win = total_goals > 2.5
        elif sel_lower == "under 2.5":
            is_win = total_goals < 2.5
        else:
            is_win = (
                (sel_lower == winner.lower()) or
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

        closing_odds = get_latest_pinnacle_closing(conn, match_id, trade_sel, home_team, away_team)
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
        clv_str = f" | CLV: {clv:+.2f}%" if clv is not None else ""
        print(f"  • {home_team} vs {away_team} [{final_score}] | Pick: {trade_sel} -> {status} (₹{profit:+,.2f}){clv_str}")

    conn.commit()
    conn.close()
    print(f"\n🎯 Successfully settled {settled_count} trades.")


def print_performance_audit():
    """Calculates overall win rate, P&L, ROI, and average CLV across all settled trades, split by market."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT selection, status, stake,
               COALESCE(profit_loss, pnl, 0.0) as pnl_val,
               COALESCE(clv_percent, clv_pct) as clv_val 
        FROM trades 
        WHERE status IN ('WON', 'LOST')
    """)
    trades = cursor.fetchall()
    conn.close()

    if not trades:
        print("📊 No settled trades found in database yet.")
        return

    def summarize(subset):
        count = len(subset)
        wins = sum(1 for t in subset if t["status"] == "WON")
        staked = sum(float(t["stake"]) for t in subset)
        pnl = sum(float(t["pnl_val"]) for t in subset)
        roi = (pnl / staked * 100.0) if staked > 0 else 0.0
        clvs = [float(t["clv_val"]) for t in subset if t["clv_val"] is not None]
        avg_clv = sum(clvs) / len(clvs) if clvs else 0.0
        return count, wins, staked, pnl, roi, avg_clv

    total_trades, wins, total_staked, net_pnl, roi, avg_clv = summarize(trades)
    totals_trades = [t for t in trades if t["selection"].strip().lower() in ("over 2.5", "under 2.5")]
    h2h_trades = [t for t in trades if t["selection"].strip().lower() not in ("over 2.5", "under 2.5")]

    print("\n" + "=" * 52)
    print("📈 QUANTITATIVE PERFORMANCE AUDIT")
    print("=" * 52)
    print(f"Total Settled Trades : {total_trades}")
    print(f"Win / Loss Record    : {wins}W - {total_trades - wins}L ({wins / total_trades * 100:.1f}%)")
    print(f"Total Turnover       : ₹{total_staked:,.2f}")
    print(f"Net Profit / Loss    : ₹{net_pnl:+,.2f}")
    print(f"Return on Investment : {roi:+.2f}%")
    print(f"Average CLV vs Pinny : {avg_clv:+.2f}%")

    if h2h_trades and totals_trades:
        h_cnt, h_w, _, h_pnl, h_roi, h_clv = summarize(h2h_trades)
        t_cnt, t_w, _, t_pnl, t_roi, t_clv = summarize(totals_trades)
        print("-" * 52)
        print(f"1X2 Market   ({h_cnt:2d} bets) : {h_w}W-{h_cnt-h_w}L | P&L: ₹{h_pnl:+,.2f} | ROI: {h_roi:+.2f}% | CLV: {h_clv:+.2f}%")
        print(f"O/U 2.5 Mkt  ({t_cnt:2d} bets) : {t_w}W-{t_cnt-t_w}L | P&L: ₹{t_pnl:+,.2f} | ROI: {t_roi:+.2f}% | CLV: {t_clv:+.2f}%")

    print("=" * 52)

    if avg_clv > 1.5:
        print("✅ ALPHA CONFIRMED: Consistently beating Pinnacle closing lines.")
    elif avg_clv < 0:
        print("⚠️ NEGATIVE CLV: Market moved against signals before kickoff.")


if __name__ == "__main__":
    settle_pending_trades()
    print_performance_audit()