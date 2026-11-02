"""
main.py
Core quantitative football scanner.
Queries upcoming fixtures, extracts Pinnacle de-vig true odds,
evaluates EV discrepancies, saves trades to trades.db, and sends Telegram alerts.
"""

import os
import sys
import sqlite3
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Import verified alert function with alias
from alerts import send_telegram_trade_alert as send_trade_alert

load_dotenv()

ODDS_API_KEY = (os.getenv("ODDS_API_KEY") or "").strip()
DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")

if not ODDS_API_KEY:
    print("[!] Missing ODDS_API_KEY in .env file.")
    sys.exit(1)

# Full European slate (Top 5 domestic + UEFA tournaments)
DEFAULT_LEAGUES = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_europa_conference_league"
]

MIN_EDGE_THRESHOLD = 0.02  # +2.0% minimum EV to trigger an alert
DEFAULT_BANKROLL = 10000.0 # Base bankroll in INR
KELLY_FRACTION = 0.25      # Quarter-Kelly


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes tables using verified database column names."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            home_team TEXT,
            away_team TEXT,
            commence_time TEXT,
            selection TEXT,
            odds REAL,
            fair_odds REAL,
            stake REAL,
            edge_pct REAL,
            status TEXT DEFAULT 'PENDING',
            closing_odds REAL DEFAULT NULL,
            clv_pct REAL DEFAULT NULL,
            final_score TEXT DEFAULT NULL,
            pnl REAL DEFAULT 0.0,
            created_at TEXT,
            settled_at TEXT,
            clv_percent REAL DEFAULT NULL,
            profit_loss REAL DEFAULT 0.0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            bookmaker TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()


def fetch_odds_for_league(sport_key: str) -> list:
    """Fetches upcoming fixtures using the verified hyphenated endpoint."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            return res.json()
        print(f"  [!] API Error {sport_key}: HTTP {res.status_code} - {res.text[:120]}")
        return []
    except requests.RequestException as e:
        print(f"  [!] Connection failed for {sport_key}: {e}")
        return []


def devig_pinnacle(h_odds: float, d_odds: float, a_odds: float) -> tuple[float, float, float]:
    """Computes zero-margin true market implied probabilities from Pinnacle lines."""
    inv_h = 1.0 / h_odds
    inv_d = 1.0 / d_odds
    inv_a = 1.0 / a_odds
    overround = inv_h + inv_d + inv_a
    return inv_h / overround, inv_d / overround, inv_a / overround


def calculate_kelly_stake(edge: float, market_odds: float, bankroll: float = DEFAULT_BANKROLL) -> float:
    """Calculates Quarter-Kelly stake size in INR."""
    b = market_odds - 1.0
    p = (edge + 1.0) / market_odds
    q = 1.0 - p
    f_star = (b * p - q) / b
    safe_fraction = max(0.0, f_star * KELLY_FRACTION)
    safe_fraction = min(safe_fraction, 0.05)  # Cap stake at 5% bankroll
    return round(bankroll * safe_fraction, 2)


def record_trade(match_id: str, home_team: str, away_team: str, commence_time: str,
                 selection: str, odds: float, fair_odds: float, stake: float, edge: float) -> bool:
    """Inserts a trade into trades.db if not already logged."""
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT id FROM trades 
        WHERE match_id = ? AND selection = ? AND status = 'PENDING'
    """, (match_id, selection))
    if c.fetchone():
        conn.close()
        return False

    now_iso = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO trades (
            match_id, home_team, away_team, commence_time,
            selection, odds, fair_odds, stake, edge_pct,
            status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
    """, (match_id, home_team, away_team, commence_time, selection, odds, fair_odds, stake, round(edge * 100, 2), now_iso))

    conn.commit()
    conn.close()
    return True


def record_pinnacle_snapshot(match_id: str, h_odds: float, d_odds: float, a_odds: float):
    """Logs the Pinnacle price line for post-match CLV auditing."""
    conn = get_db()
    c = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO odds_snapshots (match_id, bookmaker, home_odds, draw_odds, away_odds, timestamp)
        VALUES (?, 'pinnacle', ?, ?, ?, ?)
    """, (match_id, h_odds, d_odds, a_odds, now_iso))
    conn.commit()
    conn.close()


def run_quant_scan(leagues: list = None, max_hours_ahead: int = 168) -> int:
    """Runs a complete scan over the selected leagues and horizon window."""
    init_db()
    target_leagues = leagues or DEFAULT_LEAGUES
    now_utc = datetime.now(timezone.utc)

    total_value_found = 0

    print("\n" + "=" * 55)
    print(f"🚀 INITIATING QUANT SCAN | Horizon: Next {max_hours_ahead}h")
    print(f"⏰ Current UTC Clock: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 55)

    for sport_key in target_leagues:
        matches = fetch_odds_for_league(sport_key)
        print(f"\n📂 League: {sport_key} -> {len(matches)} fixtures pulled")

        for m in matches:
            match_id = m.get("id")
            home_team = m.get("home_team")
            away_team = m.get("away_team")
            commence_str = m.get("commence_time", "").replace("Z", "+00:00")

            try:
                kickoff_utc = datetime.fromisoformat(commence_str)
            except ValueError:
                continue

            hours_until = (kickoff_utc - now_utc).total_seconds() / 3600.0

            if hours_until < 0 or hours_until > max_hours_ahead:
                continue

            # Locate Pinnacle sharp benchmark
            pinnacle_data = next((b for b in m.get("bookmakers", []) if b["key"] == "pinnacle"), None)
            if not pinnacle_data:
                continue

            h2h_market = next((mk for mk in pinnacle_data.get("markets", []) if mk["key"] == "h2h"), None)
            if not h2h_market:
                continue

            outcomes = {o["name"]: float(o["price"]) for o in h2h_market.get("outcomes", [])}
            pin_h = outcomes.get(home_team)
            pin_a = outcomes.get(away_team)
            pin_d = outcomes.get("Draw")

            if not (pin_h and pin_a and pin_d):
                continue

            record_pinnacle_snapshot(match_id, pin_h, pin_d, pin_a)
            true_p_h, true_p_d, true_p_a = devig_pinnacle(pin_h, pin_d, pin_a)

            # Evaluate non-Pinnacle bookmakers against the true probabilities
            for b in m.get("bookmakers", []):
                if b["key"] == "pinnacle":
                    continue

                b_market = next((mk for mk in b.get("markets", []) if mk["key"] == "h2h"), None)
                if not b_market:
                    continue

                b_outcomes = {o["name"]: float(o["price"]) for o in b_market.get("outcomes", [])}

                candidates = [
                    (home_team, b_outcomes.get(home_team), true_p_h, 1.0 / true_p_h),
                    ("Draw", b_outcomes.get("Draw"), true_p_d, 1.0 / true_p_d),
                    (away_team, b_outcomes.get(away_team), true_p_a, 1.0 / true_p_a)
                ]

                for sel, bookie_odds, true_p, fair_price in candidates:
                    if not bookie_odds or bookie_odds <= 1.0:
                        continue

                    edge = (bookie_odds * true_p) - 1.0

                    if edge >= MIN_EDGE_THRESHOLD:
                        stake = calculate_kelly_stake(edge, bookie_odds)
                        if stake < 50.0:
                            stake = 100.0

                        is_new = record_trade(
                            match_id=match_id,
                            home_team=home_team,
                            away_team=away_team,
                            commence_time=commence_str,
                            selection=sel,
                            odds=bookie_odds,
                            fair_odds=round(fair_price, 2),
                            stake=stake,
                            edge=edge
                        )

                        if is_new:
                            total_value_found += 1
                            print(f"  [+] VALUE FOUND: {home_team} vs {away_team} | Pick: {sel} @ {bookie_odds} (EV: {edge*100:+.2f}%)")
                            
                            send_trade_alert(
                                home_team=home_team,
                                away_team=away_team,
                                selection=sel,
                                market_odds=bookie_odds,
                                fair_odds=round(fair_price, 2),
                                edge_pct=round(edge * 100, 2),
                                stake=stake,
                                cutoff_odds=round(fair_price, 2),
                                source=b["title"],
                                commence_time=kickoff_utc.strftime("%d %b %H:%M UTC"),
                                pinny_fair=round(fair_price, 2)
                            )
    print("\n" + "=" * 55)
    print(f"🏁 SCAN FINISHED | Total Valid Trades Alerted: {total_value_found}")
    print("=" * 55)
    return total_value_found


if __name__ == "__main__":
    run_quant_scan(max_hours_ahead=168)