import os
import requests
from dotenv import load_dotenv
from model import build_score_matrix, derive_match_markets, calculate_edge_and_kelly
from ratings import calculate_match_lambdas

# 1. Load private secrets from .env
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("Error: ODDS_API_KEY not found! Make sure you created a .env file containing:")
    print('ODDS_API_KEY="your_api_key_here"')
    exit()

# 2. Portfolio & Risk Settings
SPORT = "soccer_epl"
BANKROLL_INR = 25000.0   # Testing bankroll in Rupees
KELLY_FRACTION = 0.25    # Quarter-Kelly risk mitigation

# Request both 1X2 (h2h) and Over/Under (totals) markets
URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/?apiKey={API_KEY}&regions=eu&markets=h2h,totals"

print("==================================================")
print(" FOOTBALL AI: DIXON-COLES +EV SCANNER (1X2 & O/U) ")
print("==================================================")
print("Connecting to live bookmaker feeds...\n")

response = requests.get(URL)

if response.status_code != 200:
    print(f"Error connecting to odds server: {response.status_code}")
    print(response.text)
    exit()

matches = response.json()
print(f"Fetched {len(matches)} fixtures across active bookmakers.\n")

edges_found = 0

for match in matches:
    home = match.get("home_team", "Unknown")
    away = match.get("away_team", "Unknown")
    bookmakers = match.get("bookmakers", [])
    
    if not bookmakers:
        continue

    # Compute expected goal intensities (lambdas)
    lam_home, lam_away, total_lam = calculate_match_lambdas(home, away)
    
    # Build Dixon-Coles 2D grid and derive fair probabilities
    score_grid = build_score_matrix(lam_home, lam_away)
    fair_markets = derive_match_markets(score_grid)

    for bookie in bookmakers:
        bookie_name = bookie.get("title")
        
        for market in bookie.get("markets", []):
            m_key = market.get("key")
            
            # --- Scan 1X2 (Match Winner) ---
            if m_key == "h2h":
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price", 0)
                    
                    if price <= 1.0:
                        continue
                    
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
                        ev, stake = calculate_edge_and_kelly(
                            model_prob=target_market["prob"],
                            market_odds=price,
                            bankroll=BANKROLL_INR,
                            fraction=KELLY_FRACTION
                        )
                        
                        # Filter for mathematical edge > 1%
                        if ev > 0.01:
                            edges_found += 1
                            print(f"[+EV FOUND] {home} vs {away}")
                            print(f"  Market: 1X2 -> {label} @ Odds {price:.2f} (Bookie: {bookie_name})")
                            print(f"  Model Fair Prob: {target_market['prob']*100:.1f}% (Fair Odds: {target_market['fair_odds']:.2f})")
                            print(f"  Edge (EV): +{ev*100:.2f}% | Recommended Stake: ₹{stake:,.2f}")
                            print("-" * 50)

            # --- Scan Over 2.5 Goals ---
            elif m_key == "totals":
                for outcome in market.get("outcomes", []):
                    point = outcome.get("point")
                    side = outcome.get("name")
                    price = outcome.get("price", 0)

                    if point == 2.5 and side == "Over" and price > 1.0:
                        target_market = fair_markets["over_2_5"]
                        ev, stake = calculate_edge_and_kelly(
                            model_prob=target_market["prob"],
                            market_odds=price,
                            bankroll=BANKROLL_INR,
                            fraction=KELLY_FRACTION
                        )

                        if ev > 0.01:
                            edges_found += 1
                            print(f"[+EV FOUND] {home} vs {away}")
                            print(f"  Market: Total Goals -> Over 2.5 @ Odds {price:.2f} (Bookie: {bookie_name})")
                            print(f"  Model Fair Prob: {target_market['prob']*100:.1f}% (Fair Odds: {target_market['fair_odds']:.2f})")
                            print(f"  Edge (EV): +{ev*100:.2f}% | Recommended Stake: ₹{stake:,.2f}")
                            print("-" * 50)

if edges_found == 0:
    print("Scan complete. No +EV opportunities > 1% found at current market prices.")
else:
    print(f"Scan complete. Total +EV trading signals detected: {edges_found}")