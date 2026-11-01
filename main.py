import os
import requests
from dotenv import load_dotenv
from model import build_score_matrix, derive_match_markets, calculate_edge_and_kelly
from ratings import calculate_match_lambdas
from database import init_db, log_trade

# 1. Initialize SQLite Database (and ensure lookup index exists)
init_db()

# 2. Load private secrets from .env
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("Error: ODDS_API_KEY not found! Check your .env file.")
    exit()

# 3. Portfolio & Risk Settings
SPORT = "soccer_epl"
BANKROLL_INR = 25000.0   # Testing bankroll in Rupees
KELLY_FRACTION = 0.25    # Quarter-Kelly risk mitigation

# Request both 1X2 (h2h) and Over/Under (totals) markets
URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/?apiKey={API_KEY}&regions=eu&markets=h2h,totals"

print("==================================================")
print(" FOOTBALL AI: DIXON-COLES +EV SCANNER & DB LOGGER ")
print("==================================================")
print("Connecting to live bookmaker feeds...\n")

response = requests.get(URL)

if response.status_code != 200:
    print(f"Error connecting to odds server: {response.status_code}")
    exit()

matches = response.json()
print(f"Fetched {len(matches)} fixtures across active bookmakers.\n")

edges_found = 0

for match in matches:
    home = match.get("home_team", "Unknown")
    away = match.get("away_team", "Unknown")
    match_title = f"{home} vs {away}"
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