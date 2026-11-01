import os
import requests
from dotenv import load_dotenv
from model import build_score_matrix, derive_match_markets, calculate_edge_and_kelly
from ratings import calculate_match_lambdas
from database import init_db, log_trade
from trade_engine import evaluate_market_trade

# 1. Initialize SQLite Database
init_db()

# 2. Load private secrets
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("Error: ODDS_API_KEY not found in .env!")
    exit()

# 3. Portfolio & Risk Settings
SPORT = "soccer_epl"
BANKROLL_INR = 25000.0
KELLY_FRACTION = 0.25
EXCHANGE_COMMISSION = 0.02

# Query UK and EU bookmakers for high liquidity
URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/?apiKey={API_KEY}&regions=eu,uk&markets=h2h,totals"

print("=" * 65)
print(" FOOTBALL AI: DIXON-COLES QUANTITATIVE BACK & LAY SCANNER ")
print("=" * 65)
print("Connecting to live bookmaker and exchange feeds...\n")

response = requests.get(URL)

if response.status_code != 200:
    print(f"Error connecting to odds server: {response.status_code}")
    exit()

matches = response.json()
print(f"Fetched {len(matches)} fixtures across active feeds.\n")

back_edges = 0
lay_edges = 0
matches_with_odds = 0

for match in matches:
    home = match.get("home_team", "Unknown")
    away = match.get("away_team", "Unknown")
    match_title = f"{home} vs {away}"
    bookmakers = match.get("bookmakers", [])
    
    if not bookmakers:
        continue

    matches_with_odds += 1

    # Compute expected goal intensities (lambdas)
    lam_home, lam_away, _ = calculate_match_lambdas(home, away)
    
    # Build Dixon-Coles 2D grid and derive fair probabilities
    score_grid = build_score_matrix(lam_home, lam_away)
    fair_markets = derive_match_markets(score_grid)

    for bookie in bookmakers:
        bookie_name = bookie.get("title")
        
        for market in bookie.get("markets", []):
            m_key = market.get("key")
            
            # --- Scan 1X2 Match Winner (Back vs Lay) ---
            if m_key == "h2h":
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    back_price = outcome.get("price", 0)
                    
                    if back_price <= 1.0:
                        continue

                    # Synthetic lay price (exchange spread ~2.5% above back price)
                    lay_price = round(back_price * 1.025, 2)
                    
                    target_market = None
                    if name == home:
                        target_market = fair_markets["home_win"]
                        label = f"Home Win ({home})"
                    elif name == away:
                        target_market = fair_markets["away_win"]
                        label = f"Away Win ({away})"
                    elif name == "Draw":
                        target_market = fair_markets["draw"]
                        label = "Draw"
                        
                    if target_market:
                        model_prob = target_market["prob"]
                        fair_price = round(target_market["fair_odds"], 2)
                        
                        trade_decision = evaluate_market_trade(
                            model_prob=model_prob,
                            back_odds=back_price,
                            lay_odds=lay_price,
                            commission=EXCHANGE_COMMISSION
                        )
                        
                        action = trade_decision["action"]
                        
                        if action == "BACK (BUY)":
                            ev, stake = calculate_edge_and_kelly(
                                model_prob=model_prob,
                                market_odds=back_price,
                                bankroll=BANKROLL_INR,
                                fraction=KELLY_FRACTION
                            )
                            if ev > 0.01:
                                edge_pct = round(ev * 100, 2)
                                is_new = log_trade(
                                    match_name=match_title,
                                    market_type="1X2-BACK",
                                    selection=label,
                                    bookmaker=bookie_name,
                                    market_odds=back_price,
                                    fair_odds=fair_price,
                                    edge_percent=edge_pct,
                                    stake_inr=stake
                                )
                                if is_new:
                                    back_edges += 1
                                    print(f"[+EV BACK LOGGED] {match_title}")
                                    print(f"  Selection : {label} @ Odds {back_price:.2f} ({bookie_name})")
                                    print(f"  Fair Odds : {fair_price} | Edge: +{edge_pct}% | Stake: ₹{stake:,.2f}")
                                    print("-" * 65)

                        elif action == "LAY (SHORT-SELL)":
                            # For lay bets, edge is based on lay EV
                            lay_edge = trade_decision["lay_ev_pct"]
                            if lay_edge > 2.0:
                                # Standard lay liability sizing using quarter Kelly on fail probability
                                prob_fail = 1.0 - model_prob
                                _, lay_stake = calculate_edge_and_kelly(
                                    model_prob=prob_fail,
                                    market_odds=lay_price / (lay_price - 1.0) if lay_price > 1.0 else 2.0,
                                    bankroll=BANKROLL_INR,
                                    fraction=KELLY_FRACTION
                                )
                                liability = round(lay_stake * (lay_price - 1.0), 2)
                                
                                is_new = log_trade(
                                    match_name=match_title,
                                    market_type="1X2-LAY",
                                    selection=f"Lay {label}",
                                    bookmaker=bookie_name,
                                    market_odds=lay_price,
                                    fair_odds=fair_price,
                                    edge_percent=lay_edge,
                                    stake_inr=lay_stake
                                )
                                if is_new:
                                    lay_edges += 1
                                    print(f"[+EV LAY SHORT-SELL] {match_title}")
                                    print(f"  Selection : Lay {label} @ Odds {lay_price:.2f} ({bookie_name})")
                                    print(f"  Fair Odds : {fair_price} | Lay Edge: +{lay_edge}%")
                                    print(f"  Backer Stake: ₹{lay_stake:,.2f} | Max Liability: ₹{liability:,.2f}")
                                    print("-" * 65)

            # --- Scan Totals Over 2.5 Goals ---
            elif m_key == "totals":
                for outcome in market.get("outcomes", []):
                    point = outcome.get("point")
                    side = outcome.get("name")
                    back_price = outcome.get("price", 0)

                    if point == 2.5 and side == "Over" and back_price > 1.0:
                        target_market = fair_markets["over_2_5"]
                        model_prob = target_market["prob"]
                        fair_price = round(target_market["fair_odds"], 2)
                        
                        ev, stake = calculate_edge_and_kelly(
                            model_prob=model_prob,
                            market_odds=back_price,
                            bankroll=BANKROLL_INR,
                            fraction=KELLY_FRACTION
                        )

                        if ev > 0.01:
                            edge_pct = round(ev * 100, 2)
                            is_new = log_trade(
                                match_name=match_title,
                                market_type="Totals-BACK",
                                selection="Over 2.5",
                                bookmaker=bookie_name,
                                market_odds=back_price,
                                fair_odds=fair_price,
                                edge_percent=edge_pct,
                                stake_inr=stake
                            )
                            if is_new:
                                back_edges += 1
                                print(f"[+EV BACK LOGGED] {match_title}")
                                print(f"  Selection : Over 2.5 @ Odds {back_price:.2f} ({bookie_name})")
                                print(f"  Fair Odds : {fair_price} | Edge: +{edge_pct}% | Stake: ₹{stake:,.2f}")
                                print("-" * 65)

print("\n" + "=" * 65)
print("SCAN COMPLETE")
print(f"Fixtures Analyzed        : {matches_with_odds}/{len(matches)}")
print(f"New Back Signals Logged  : {back_edges}")
print(f"New Lay Signals Logged   : {lay_edges}")
print("=" * 65)