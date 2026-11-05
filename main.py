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

# Graceful check: Exit with 0 so missing secrets skip the run instead of crashing GitHub Actions
if not ODDS_API_KEY:
    print("[!] Warning: ODDS_API_KEY is missing in environment variables or .env file. Skipping scan gracefully.")
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

# --- RISK & FILTER CONTROLS ---
MIN_EDGE_SIDES = 0.025     # +2.5% minimum edge for Home, Away, Over 2.5, or Under 2.5
ALLOW_DRAWS = False        # Blocks Draw spam; set True only if you want Draws
MIN_EDGE_DRAW = 0.055      # +5.5% minimum edge required if ALLOW_DRAWS is True
MAX_EDGE_CAP = 0.085       # +8.5% max edge cap (ignores broken/stale API feeds)
MAX_ODDS_CAP = 3.80        # Ignores longshots above 3.80 decimal odds
MAX_DRIFT_TOLERANCE = 0.01 # Block trade if Pinnacle odds drifted up by more than 1%
DEFAULT_BANKROLL = 10000.0 # Base bankroll in INR
KELLY_FRACTION = 0.25      # Quarter-Kelly
TARGET_TOTAL_LINE = 2.5    # Strictly target Over/Under 2.5 goals

# Exchange commission haircuts on net profit
EXCHANGE_COMMISSIONS = {
    "betfair_ex_eu": 0.05,
    "betfair_ex_uk": 0.05,
    "matchbook": 0.02,
    "smarkets": 0.02
}

# Geo-locked regional European books and stale feeds to ignore
BOOKMAKER_BLACKLIST = {
    "gtbets",
    "mybookieag",
    "unibet_nl",
    "unibet_it",
    "unibet_fr",
    "unibet_se",
    "unibet_uk",
    "winamax_fr",
    "winamax_de",
    "parionssport_fr",
    "pmu_fr",
    "betclic_fr",
    "tipico_de",
    "codere_it",
    "leovegas_se"
}

BOOKMAKER_WHITELIST = set()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes tables and safely migrates odds_snapshots for Over/Under 2.5 tracking."""
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
            over_25_odds REAL DEFAULT NULL,
            under_25_odds REAL DEFAULT NULL,
            timestamp TEXT
        )
    """)
    for col in ("over_25_odds", "under_25_odds"):
        try:
            c.execute(f"ALTER TABLE odds_snapshots ADD COLUMN {col} REAL DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


def fetch_odds_for_league(sport_key: str) -> list:
    """Fetches upcoming h2h and totals markets from the verified endpoint."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal"
    }
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            return res.json()
        print(f"  [!] API Error {sport_key}: HTTP {res.status_code} {res.text[:120]}")
        return []
    except requests.RequestException as e:
        print(f"  [!] Connection failed for {sport_key}: {e}")
        return []


def devig_shin(odds_list: list[float], max_iter: int = 200, tol: float = 1e-7) -> list[float]:
    """Strips bookmaker margin using Shin's (1992/1993) model."""
    inv_odds = [1.0 / o for o in odds_list]
    booksum = sum(inv_odds)

    if abs(booksum - 1.0) < 1e-5:
        return [p / booksum for p in inv_odds]

    def calc_probs(z_val: float) -> list[float]:
        denom = 2.0 * (1.0 - z_val)
        probs = []
        for b_i in inv_odds:
            radicand = max(0.0, (z_val ** 2) + 4.0 * (1.0 - z_val) * (b_i ** 2) / booksum)
            probs.append((math.sqrt(radicand) - z_val) / denom)
        return probs

    lo, hi = 1e-9, 0.4
    for _ in range(max_iter):
        z_mid = (lo + hi) / 2.0
        p_candidates = calc_probs(z_mid)
        diff = sum(p_candidates) - 1.0

        if abs(diff) < tol:
            break
        elif diff > 0:
            lo = z_mid
        else:
            hi = z_mid

    p_norm = sum(p_candidates)
    return [p / p_norm for p in p_candidates]


def devig_pinnacle(h_odds: float, d_odds: float, a_odds: float) -> tuple[float, float, float]:
    """Passes 3-way Pinnacle odds through Shin de-vigging."""
    p_h, p_d, p_a = devig_shin([h_odds, d_odds, a_odds])
    return p_h, p_d, p_a


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


def apply_commission(raw_odds: float, bookie_key: str) -> float:
    """Deducts betting exchange commission from raw decimal odds."""
    comm = EXCHANGE_COMMISSIONS.get(bookie_key, 0.0)
    if comm > 0.0 and raw_odds > 1.0:
        return round(1.0 + (raw_odds - 1.0) * (1.0 - comm), 3)
    return raw_odds


def get_dynamic_bankroll() -> float:
    """Calculates current live bankroll based on settled profit/loss in trades.db."""
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT SUM(COALESCE(profit_loss, pnl, 0.0)) as net_pnl
            FROM trades
            WHERE status IN ('WON', 'LOST')
        """)
        row = c.fetchone()
        net_pnl = float(row["net_pnl"]) if row and row["net_pnl"] is not None else 0.0
    except sqlite3.OperationalError:
        net_pnl = 0.0
    conn.close()
    return max(1000.0, DEFAULT_BANKROLL + net_pnl)


def calculate_kelly_stake(edge: float, market_odds: float, bankroll: float = None) -> float:
    """Calculates Quarter-Kelly stake size in INR."""
    active_bankroll = bankroll if bankroll is not None else get_dynamic_bankroll()
    b = market_odds - 1.0
    p = (edge + 1.0) / market_odds
    q = 1.0 - p
    f_star = (b * p - q) / b
    safe_fraction = max(0.0, f_star * KELLY_FRACTION)
    safe_fraction = min(safe_fraction, 0.05)
    return round(active_bankroll * safe_fraction, 2)


def get_previous_pinnacle_snapshot(match_id: str) -> dict:
    """Fetches the most recent Pinnacle odds snapshot for line-velocity comparison."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT home_odds, draw_odds, away_odds, over_25_odds, under_25_odds
        FROM odds_snapshots
        WHERE match_id = ? AND bookmaker = 'pinnacle'
        ORDER BY id DESC LIMIT 1
    """, (match_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "home_odds": float(row["home_odds"]) if row["home_odds"] is not None else None,
            "draw_odds": float(row["draw_odds"]) if row["draw_odds"] is not None else None,
            "away_odds": float(row["away_odds"]) if row["away_odds"] is not None else None,
            "over_25_odds": float(row["over_25_odds"]) if row["over_25_odds"] is not None else None,
            "under_25_odds": float(row["under_25_odds"]) if row["under_25_odds"] is not None else None
        }
    return None


def record_pinnacle_snapshot(match_id: str, h_odds: float, d_odds: float, a_odds: float,
                             over_25: float = None, under_25: float = None):
    """Logs the Pinnacle 1X2 and Over/Under 2.5 lines for CLV auditing and steam tracking."""
    conn = get_db()
    c = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    c.execute("""
        INSERT INTO odds_snapshots (
            match_id, bookmaker, home_odds, draw_odds, away_odds, over_25_odds, under_25_odds, timestamp
        ) VALUES (?, 'pinnacle', ?, ?, ?, ?, ?, ?)
    """, (match_id, h_odds, d_odds, a_odds, over_25, under_25, now_iso))
    conn.commit()
    conn.close()


def record_trade(match_id: str, home_team: str, away_team: str, commence_time: str,
                 selection: str, odds: float, fair_odds: float, stake: float, edge: float) -> bool:
    """Inserts a trade into trades.db with duplicate prevention."""
    conn = get_db()
    c = conn.cursor()

    is_totals = selection.strip().lower() in ("over 2.5", "under 2.5")

    if is_totals:
        c.execute("""
            SELECT id FROM trades 
            WHERE match_id = ? 
              AND status = 'PENDING'
              AND LOWER(TRIM(selection)) IN ('over 2.5', 'under 2.5')
        """, (match_id,))
    else:
        c.execute("""
            SELECT id FROM trades 
            WHERE match_id = ? 
              AND status = 'PENDING'
              AND LOWER(TRIM(selection)) NOT IN ('over 2.5', 'under 2.5')
        """, (match_id,))

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


def run_quant_scan(leagues: list = None, max_hours_ahead: int = 48) -> int:
    """Runs a complete scan over the selected leagues and horizon window."""
    init_db()
    target_leagues = leagues or TARGET_LEAGUES
    now_utc = datetime.now(timezone.utc)
    live_bankroll = get_dynamic_bankroll()

    total_value_found = 0

    print("\n" + "=" * 60)
    print(f"🚀 INITIATING SHIN + STEAM QUANT SCAN (1X2 + O/U 2.5) | Horizon: Next {max_hours_ahead}h")
    print(f"💰 Active Bankroll: ₹{live_bankroll:,.2f} | Blocked Regional Books: {len(BOOKMAKER_BLACKLIST)}")
    print(f"⏰ Current UTC Clock: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

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
            if hours_until < 0.15 or hours_until > max_hours_ahead:
                continue

            pinnacle_data = next((b for b in m.get("bookmakers", []) if b["key"] == "pinnacle"), None)
            if not pinnacle_data:
                continue

            pin_markets = {mk["key"]: mk for mk in pinnacle_data.get("markets", [])}
            h2h_market = pin_markets.get("h2h")
            totals_market = pin_markets.get("totals")

            if not h2h_market:
                continue

            outcomes = {o["name"]: float(o["price"]) for o in h2h_market.get("outcomes", [])}
            pin_h = outcomes.get(home_team)
            pin_a = outcomes.get(away_team)
            pin_d = outcomes.get("Draw")

            if not (pin_h and pin_a and pin_d):
                continue

            pin_o25, pin_u25 = extract_totals_25(totals_market)

            prev_snap = get_previous_pinnacle_snapshot(match_id)
            record_pinnacle_snapshot(match_id, pin_h, pin_d, pin_a, pin_o25, pin_u25)

            true_p_h, true_p_d, true_p_a = devig_pinnacle(pin_h, pin_d, pin_a)

            outcomes_meta = [
                (home_team, true_p_h, 1.0 / true_p_h, False, pin_h, prev_snap["home_odds"] if prev_snap else None, "h2h"),
                ("Draw", true_p_d, 1.0 / true_p_d, True, pin_d, prev_snap["draw_odds"] if prev_snap else None, "h2h"),
                (away_team, true_p_a, 1.0 / true_p_a, False, pin_a, prev_snap["away_odds"] if prev_snap else None, "h2h")
            ]

            if pin_o25 and pin_u25:
                true_p_o25, true_p_u25 = devig_shin([pin_o25, pin_u25])
                outcomes_meta.append(
                    ("Over 2.5", true_p_o25, 1.0 / true_p_o25, False, pin_o25, prev_snap["over_25_odds"] if prev_snap else None, "totals")
                )
                outcomes_meta.append(
                    ("Under 2.5", true_p_u25, 1.0 / true_p_u25, False, pin_u25, prev_snap["under_25_odds"] if prev_snap else None, "totals")
                )

            for sel, true_p, fair_price, is_draw, curr_pin, prev_pin, mkt_type in outcomes_meta:
                if is_draw and not ALLOW_DRAWS:
                    continue

                if fair_price > MAX_ODDS_CAP:
                    continue

                steam_note = ""
                if prev_pin is not None:
                    if curr_pin > prev_pin * (1.0 + MAX_DRIFT_TOLERANCE):
                        print(f"  [-] Skipped {sel} ({home_team} vs {away_team}): Sharp line drifting ({prev_pin:.2f} -> {curr_pin:.2f})")
                        continue
                    elif curr_pin < prev_pin:
                        steam_note = f"Sharp money backing pick (Line tightening: {prev_pin:.2f} to {curr_pin:.2f})"

                min_req_edge = MIN_EDGE_DRAW if is_draw else MIN_EDGE_SIDES
                best_edge = -1.0
                best_bookie_odds = 0.0
                best_bookie_title = ""

                for b in m.get("bookmakers", []):
                    b_key = b["key"]
                    if b_key == "pinnacle" or b_key in BOOKMAKER_BLACKLIST:
                        continue
                    if BOOKMAKER_WHITELIST and b_key not in BOOKMAKER_WHITELIST:
                        continue

                    b_market = next((mk for mk in b.get("markets", []) if mk["key"] == mkt_type), None)
                    if not b_market:
                        continue

                    raw_price = None
                    if mkt_type == "h2h":
                        b_outcomes = {o["name"]: float(o["price"]) for o in b_market.get("outcomes", [])}
                        raw_price = b_outcomes.get(sel)
                    elif mkt_type == "totals":
                        b_o25, b_u25 = extract_totals_25(b_market)
                        raw_price = b_o25 if sel == "Over 2.5" else b_u25

                    if not raw_price or raw_price <= 1.0:
                        continue

                    eff_price = apply_commission(raw_price, b_key)
                    if eff_price > MAX_ODDS_CAP:
                        continue

                    edge = (eff_price * true_p) - 1.0
                    if edge > best_edge:
                        best_edge = edge
                        best_bookie_odds = eff_price
                        best_bookie_title = b["title"]

                if min_req_edge <= best_edge <= MAX_EDGE_CAP:
                    stake = calculate_kelly_stake(best_edge, best_bookie_odds, live_bankroll)
                    if stake < 50.0:
                        stake = 100.0

                    is_new = record_trade(
                        match_id=match_id,
                        home_team=home_team,
                        away_team=away_team,
                        commence_time=commence_str,
                        selection=sel,
                        odds=best_bookie_odds,
                        fair_odds=round(fair_price, 2),
                        stake=stake,
                        edge=best_edge
                    )

                    if is_new:
                        total_value_found += 1
                        print(f"  [+] VALUE FOUND: {home_team} vs {away_team} | Pick: {sel} @ {best_bookie_odds} ({best_bookie_title}) [Edge: {best_edge*100:+.2f}%]")

                        send_trade_alert(
                            home_team=home_team,
                            away_team=away_team,
                            selection=sel,
                            market_odds=best_bookie_odds,
                            fair_odds=round(fair_price, 2),
                            edge_pct=round(best_edge * 100, 2),
                            stake=stake,
                            cutoff_odds=round(fair_price * (1.0 + min_req_edge), 2),
                            source=best_bookie_title,
                            commence_time=kickoff_utc.strftime("%d %b %H:%M UTC"),
                            pinny_fair=round(curr_pin, 2),
                            steam_reason=steam_note
                        )

    print("\n" + "=" * 60)
    print(f"🏁 SCAN FINISHED | Total Valid Trades Alerted: {total_value_found}")
    print("=" * 60)
    return total_value_found


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        run_quant_scan(max_hours_ahead=24.0)
    else:
        print("\nSelect Pre-Match Liquid Scan Window:")
        print("  [1] 1 Hour Pre-Kickoff (Hyper-liquid, closing lines)")
        print("  [2] 24 Hours Pre-Kickoff (Standard daily scan - Recommended)")
        print("  [3] 48 Hours Pre-Kickoff (Extended slate)")
        
        choice = input("Enter choice (1-3, default 2): ").strip()
        hours = 1.0 if choice == "1" else (48.0 if choice == "3" else 24.0)
        run_quant_scan(max_hours_ahead=hours)
