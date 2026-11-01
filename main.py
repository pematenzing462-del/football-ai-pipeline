import os
import requests
from dotenv import load_dotenv
from model import build_score_matrix, derive_match_markets, calculate_edge_and_kelly
from ratings import calculate_match_lambdas
from database import init_db, log_trade
from trade_engine import evaluate_market_trade, evaluate_draw_sniper
from exchange_execution import evaluate_liquidity_cap

# 1. Initialize SQLite Database
init_db()

# 2. Load private credentials
load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")

if not API_KEY:
    print("Error: ODDS_API_KEY not found in .env!")
    exit()

# 3. Portfolio & Trading Parameters
BANKROLL_INR = 25000.0
KELLY_FRACTION = 0.25
EXCHANGE_COMMISSION = 0.02
MINIMUM_STAKE_INR = 100.0

# Multi-League Roster: Premier League + Spanish La Liga
ACTIVE_LEAGUES = [
    {"key": "soccer_epl", "name": "English Premier League"},
    {"key": "soccer_spain_la_liga", "name": "Spanish La Liga"}
]

print("=" * 75)
print(" QUANTITATIVE AI: MULTI-LEAGUE SCANNER WITH LIQUIDITY FILTER ")
print("=" * 75)

total_back_edges = 0
total_lay_edges = 0
total_sniper_edges = 0
total_liquidity_rejections = 0
total_matches_scanned = 0

for league in ACTIVE_LEAGUES:
    sport_key = league["key"]
    league_name = league["name"]
    
    print(f"\n>>> Scanning {league_name} ({sport_key})...")
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={API_KEY}&regions=eu,uk&markets=h2h,totals"
    
    try:
        response = requests.get(url, timeout=12)
    except Exception as e:
        print(f"Connection failed for {sport_key}: {e}")
        continue

    if response.status_code != 200:
        print(f"Error fetching odds for {sport_key}: {response.status_code}")
        continue

    matches = response.json()
    print(f"Fetched {len(matches)} fixtures across active feeds.")

    for match in matches:
        home = match.get("home_team", "Unknown")
        away = match.get("away_team", "Unknown")
        match_title = f"{home} vs {away}"
        bookmakers = match.get("bookmakers", [])
        
        if not bookmakers:
            continue

        total_matches_scanned += 1

        # Calculate time-decay weighted expected goals using rolling xG
        lam_home, lam_away, projected_tot = calculate_match_lambdas(home, away, sport_key=sport_key)
        
        # Build 2D Dixon-Coles grid and derive fair market probabilities
        score_grid = build_score_matrix(lam_home, lam_away)
        fair_markets = derive_match_markets(score_grid)

        for bookie in bookmakers:
            bookie_name = bookie.get("title")
            
            for market in bookie.get("markets", []):
                m_key = market.get("key")
                
                # --- 1. Evaluate 1X2 Match Winner (Back vs Lay & Draw Sniper) ---
                if m_key == "h2h":
                    for outcome in market.get("outcomes", []):
                        name = outcome.get("name")
                        back_price = outcome.get("price", 0)
                        
                        if back_price <= 1.0:
                            continue

                        # Extract volume if feed supports exchange depth, else set safe baseline
                        raw_volume = outcome.get("depth", outcome.get("volume", 5000.0))

                        # Synthetic Lay price approximation (exchange spread ~2.5%)
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
                            
                            # PRIORITY CHECK: Draw Sniper in low-intensity fixtures
                            if name == "Draw":
                                sniper_res = evaluate_draw_sniper(
                                    lam_home=lam_home,
                                    lam_away=lam_away,
                                    model_draw_prob=model_prob,
                                    draw_market_odds=back_price,
                                    min_edge_pct=8.0
                                )
                                if sniper_res["qualified"]:
                                    ev, raw_stake = calculate_edge_and_kelly(
                                        model_prob=model_prob,
                                        market_odds=back_price,
                                        bankroll=BANKROLL_INR,
                                        fraction=KELLY_FRACTION
                                    )
                                    
                                    # Enforce Liquidity Cap
                                    liq_check = evaluate_liquidity_cap(
                                        suggested_stake=raw_stake,
                                        available_volume=raw_volume,
                                        min_stake=MINIMUM_STAKE_INR
                                    )
                                    
                                    if not liq_check["can_execute"]:
                                        total_liquidity_rejections += 1
                                        continue

                                    final_stake = liq_check["executable_stake"]
                                    edge_pct = sniper_res["edge_pct"]
                                    
                                    is_new = log_trade(
                                        match_name=match_title,
                                        market_type="DRAW-SNIPER",
                                        selection="Draw (Sniper)",
                                        bookmaker=bookie_name,
                                        market_odds=back_price,
                                        fair_odds=fair_price,
                                        edge_percent=edge_pct,
                                        stake_inr=final_stake
                                    )
                                    if is_new:
                                        total_sniper_edges += 1
                                        partial_note = " [CAPPED TO DEPTH]" if liq_check["is_partial"] else ""
                                        print(f"  [🎯 DRAW SNIPER ACTIVE] {match_title}")
                                        print(f"    Expected λ: {lam_home:.2f}H / {lam_away:.2f}A (Total: {projected_tot:.2f})")
                                        print(f"    Draw Odds: {back_price:.2f} ({bookie_name}) | Fair: {fair_price}")
                                        print(f"    Edge: +{edge_pct}% | Executed Stake: ₹{final_stake:,.2f}{partial_note}")
                                        print("  " + "-" * 65)
                                        continue

                            # Standard Back vs Lay Evaluation
                            trade_decision = evaluate_market_trade(
                                model_prob=model_prob,
                                back_odds=back_price,
                                lay_odds=lay_price,
                                commission=EXCHANGE_COMMISSION
                            )
                            
                            action = trade_decision["action"]
                            
                            # Execute Back
                            if action == "BACK (BUY)":
                                ev, raw_stake = calculate_edge_and_kelly(
                                    model_prob=model_prob,
                                    market_odds=back_price,
                                    bankroll=BANKROLL_INR,
                                    fraction=KELLY_FRACTION
                                )
                                if ev > 0.01:
                                    # Enforce Liquidity Cap
                                    liq_check = evaluate_liquidity_cap(
                                        suggested_stake=raw_stake,
                                        available_volume=raw_volume,
                                        min_stake=MINIMUM_STAKE_INR
                                    )
                                    if not liq_check["can_execute"]:
                                        total_liquidity_rejections += 1
                                        continue

                                    final_stake = liq_check["executable_stake"]
                                    edge_pct = round(ev * 100, 2)
                                    
                                    is_new = log_trade(
                                        match_name=match_title,
                                        market_type="1X2-BACK",
                                        selection=label,
                                        bookmaker=bookie_name,
                                        market_odds=back_price,
                                        fair_odds=fair_price,
                                        edge_percent=edge_pct,
                                        stake_inr=final_stake
                                    )
                                    if is_new:
                                        total_back_edges += 1
                                        partial_note = " [CAPPED TO DEPTH]" if liq_check["is_partial"] else ""
                                        print(f"  [+EV BACK LOGGED] {match_title}")
                                        print(f"    Pick: {label} @ Odds {back_price:.2f} ({bookie_name})")
                                        print(f"    Fair: {fair_price} | Edge: +{edge_pct}% | Executed Stake: ₹{final_stake:,.2f}{partial_note}")
                                        print("  " + "-" * 65)

                            # Execute Lay (Short-Sell)
                            elif action == "LAY (SHORT-SELL)":
                                lay_edge = trade_decision["lay_ev_pct"]
                                if lay_edge > 2.0:
                                    prob_fail = 1.0 - model_prob
                                    _, raw_lay_stake = calculate_edge_and_kelly(
                                        model_prob=prob_fail,
                                        market_odds=lay_price / (lay_price - 1.0) if lay_price > 1.0 else 2.0,
                                        bankroll=BANKROLL_INR,
                                        fraction=KELLY_FRACTION
                                    )
                                    
                                    # Enforce Liquidity Cap on Lay volume
                                    lay_depth = outcome.get("lay_depth", raw_volume * 1.5)
                                    liq_check = evaluate_liquidity_cap(
                                        suggested_stake=raw_lay_stake,
                                        available_volume=lay_depth,
                                        min_stake=MINIMUM_STAKE_INR
                                    )
                                    if not liq_check["can_execute"]:
                                        total_liquidity_rejections += 1
                                        continue

                                    final_lay_stake = liq_check["executable_stake"]
                                    liability = round(final_lay_stake * (lay_price - 1.0), 2)
                                    
                                    is_new = log_trade(
                                        match_name=match_title,
                                        market_type="1X2-LAY",
                                        selection=f"Lay {label}",
                                        bookmaker=bookie_name,
                                        market_odds=lay_price,
                                        fair_odds=fair_price,
                                        edge_percent=lay_edge,
                                        stake_inr=final_lay_stake
                                    )
                                    if is_new:
                                        total_lay_edges += 1
                                        partial_note = " [CAPPED TO DEPTH]" if liq_check["is_partial"] else ""
                                        print(f"  [+EV LAY SHORT-SELL] {match_title}")
                                        print(f"    Pick: Lay {label} @ Odds {lay_price:.2f} ({bookie_name})")
                                        print(f"    Fair: {fair_price} | Lay Edge: +{lay_edge}%")
                                        print(f"    Backer Stake: ₹{final_lay_stake:,.2f}{partial_note} | Liability: ₹{liability:,.2f}")
                                        print("  " + "-" * 65)

                # --- 2. Evaluate Over 2.5 Goals Totals ---
                elif m_key == "totals":
                    for outcome in market.get("outcomes", []):
                        point = outcome.get("point")
                        side = outcome.get("name")
                        back_price = outcome.get("price", 0)

                        if point == 2.5 and side == "Over" and back_price > 1.0:
                            raw_volume = outcome.get("depth", outcome.get("volume", 3000.0))
                            target_market = fair_markets["over_2_5"]
                            model_prob = target_market["prob"]
                            fair_price = round(target_market["fair_odds"], 2)
                            
                            ev, raw_stake = calculate_edge_and_kelly(
                                model_prob=model_prob,
                                market_odds=back_price,
                                bankroll=BANKROLL_INR,
                                fraction=KELLY_FRACTION
                            )

                            if ev > 0.01:
                                liq_check = evaluate_liquidity_cap(
                                    suggested_stake=raw_stake,
                                    available_volume=raw_volume,
                                    min_stake=MINIMUM_STAKE_INR
                                )
                                if not liq_check["can_execute"]:
                                    total_liquidity_rejections += 1
                                    continue

                                final_stake = liq_check["executable_stake"]
                                edge_pct = round(ev * 100, 2)
                                
                                is_new = log_trade(
                                    match_name=match_title,
                                    market_type="Totals-BACK",
                                    selection="Over 2.5",
                                    bookmaker=bookie_name,
                                    market_odds=back_price,
                                    fair_odds=fair_price,
                                    edge_percent=edge_pct,
                                    stake_inr=final_stake
                                )
                                if is_new:
                                    total_back_edges += 1
                                    partial_note = " [CAPPED TO DEPTH]" if liq_check["is_partial"] else ""
                                    print(f"  [+EV BACK LOGGED] {match_title}")
                                    print(f"    Pick: Over 2.5 @ Odds {back_price:.2f} ({bookie_name})")
                                    print(f"    Fair: {fair_price} | Edge: +{edge_pct}% | Executed Stake: ₹{final_stake:,.2f}{partial_note}")
                                    print("  " + "-" * 65)

print("\n" + "=" * 75)
print("MULTI-LEAGUE SCAN COMPLETE")
print(f"Total Matches Analyzed       : {total_matches_scanned}")
print(f"Draw Sniper Trades Found     : {total_sniper_edges}")
print(f"New Back Signals Logged      : {total_back_edges}")
print(f"New Lay Signals Logged       : {total_lay_edges}")
print(f"Trades Rejected (Low Liquidity): {total_liquidity_rejections}")
print("=" * 75)