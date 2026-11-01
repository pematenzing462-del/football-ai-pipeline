import requests

# Put your 32-character key between the quotes:
API_KEY = "f4bbae334a42b289ce5bbf59b7fa6939"

URL = f"https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={API_KEY}&regions=eu&markets=totals"

print("Fetching live market data...")
response = requests.get(URL)

if response.status_code == 200:
    matches = response.json()
    print(f"Connection successful! Analyzing {len(matches)} matches.\n")
    
    for match in matches[:3]:
        home = match.get("home_team", "Unknown")
        away = match.get("away_team", "Unknown")
        print(f"Fixture: {home} vs {away}")
        
        bookmakers = match.get("bookmakers", [])
        if not bookmakers:
            print("  No bookmakers active yet.")
            print("-" * 50)
            continue
            
        bookie = bookmakers[0]
        print(f"  Bookmaker: {bookie.get('title')}")
        
        for market in bookie.get("markets", []):
            if market.get("key") == "totals":
                outcomes = market.get("outcomes", [])
                
                # Check for a standard two-way Over/Under market
                if len(outcomes) == 2:
                    o1, o2 = outcomes[0], outcomes[1]
                    price1 = o1.get("price", 0)
                    price2 = o2.get("price", 0)
                    
                    if price1 > 0 and price2 > 0:
                        # Raw implied probabilities
                        raw_prob1 = 1.0 / price1
                        raw_prob2 = 1.0 / price2
                        bookmaker_margin = (raw_prob1 + raw_prob2) - 1.0
                        
                        # Normalized (Fair) Probabilities - Removing the Vig
                        fair_prob1 = raw_prob1 / (raw_prob1 + raw_prob2)
                        fair_prob2 = raw_prob2 / (raw_prob1 + raw_prob2)
                        
                        fair_odds1 = 1.0 / fair_prob1
                        fair_odds2 = 1.0 / fair_prob2
                        
                        print(f"  Market: Total Goals {o1.get('point')}")
                        print(f"    Bookmaker Margin (Vig): {bookmaker_margin * 100:.2f}%")
                        print(f"    {o1.get('name')}: Listed Odds = {price1:.2f} | Fair Odds = {fair_odds1:.2f} (True Prob: {fair_prob1 * 100:.1f}%)")
                        print(f"    {o2.get('name')}: Listed Odds = {price2:.2f} | Fair Odds = {fair_odds2:.2f} (True Prob: {fair_prob2 * 100:.1f}%)")
        print("-" * 50)
else:
    print(f"Error: {response.status_code}")
    print(response.text)