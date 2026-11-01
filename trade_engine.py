def evaluate_market_trade(model_prob, back_odds, lay_odds, commission=0.02):
    """
    Evaluates whether an outcome presents a mathematical Back Edge, Lay Edge,
    or should be avoided based on model probabilities and exchange commission.
    """
    fair_odds = 1.0 / model_prob
    
    # Back EV: Expected Return - 1
    back_ev = (model_prob * (back_odds - 1.0)) - (1.0 - model_prob)
    
    # Lay EV: Probability outcome fails * net backer stake - probability outcome happens * lay liability
    prob_fail = 1.0 - model_prob
    lay_ev = (prob_fail * (1.0 - commission)) - (model_prob * (lay_odds - 1.0))
    
    action = "PASS"
    edge_pct = 0.0
    
    if back_ev > 0.02:
        action = "BACK (BUY)"
        edge_pct = round(back_ev * 100, 2)
    elif lay_ev > 0.02:
        action = "LAY (SHORT-SELL)"
        edge_pct = round(lay_ev * 100, 2)
        
    return {
        "action": action,
        "fair_odds": round(fair_odds, 2),
        "back_ev_pct": round(back_ev * 100, 2),
        "lay_ev_pct": round(lay_ev * 100, 2),
        "primary_edge_pct": edge_pct
    }

def calculate_green_up(back_stake_inr, back_odds, current_lay_odds, commission=0.02):
    """
    Computes exact Lay Stake, Liability, and Guaranteed Locked Profit in ₹
    to hedge out of an existing open Back position (equal P&L regardless of outcome).
    """
    # Lay stake required to equalize profit across outcomes factoring commission
    lay_stake = (back_stake_inr * back_odds) / (current_lay_odds - commission)
    liability = lay_stake * (current_lay_odds - 1.0)
    
    # Net profit if selection wins
    profit_win = (back_stake_inr * (back_odds - 1.0)) - liability
    # Net profit if selection loses
    profit_lose = (lay_stake * (1.0 - commission)) - back_stake_inr
    
    guaranteed_pnl = min(profit_win, profit_lose)
    roi_percent = (guaranteed_pnl / back_stake_inr) * 100
    
    return {
        "recommended_lay_stake_inr": round(lay_stake, 2),
        "liability_inr": round(liability, 2),
        "profit_if_win_inr": round(profit_win, 2),
        "profit_if_lose_inr": round(profit_lose, 2),
        "guaranteed_pnl_inr": round(guaranteed_pnl, 2),
        "roi_percent": round(roi_percent, 2)
    }

if __name__ == "__main__":
    print("=" * 65)
    print(" QUANTITATIVE EXCHANGE ENGINE: BACK, LAY & HEDGING TEST ")
    print("=" * 65)
    
    # ---------------------------------------------------------
    # Scenario A: Evaluating Trade Signals (Back vs Lay)
    # ---------------------------------------------------------
    print("\n[TEST 1: OVERPRICED OUTCOME -> SHORT-SELL (LAY)]")
    # True probability of an upset is 18% (Fair Odds: 5.56)
    # Market hype pushes Lay odds down to 3.80 (significantly underpriced risk)
    simulated_prob = 0.18
    market_back = 3.75
    market_lay = 3.80
    
    signal = evaluate_market_trade(simulated_prob, market_back, market_lay)
    print(f"Model Fair Odds: {signal['fair_odds']}")
    print(f"Market Prices   : Back @ {market_back} | Lay @ {market_lay}")
    print(f"Back EV         : {signal['back_ev_pct']:+}%")
    print(f"Lay EV          : {signal['lay_ev_pct']:+}%")
    print(f"Decision        : {signal['action']} with {signal['primary_edge_pct']}% edge")
    
    # ---------------------------------------------------------
    # Scenario B: Hedging / Greening-Up an Active Position
    # ---------------------------------------------------------
    print("\n" + "-" * 65)
    print("[TEST 2: GREENING-UP (RISK-FREE CASH OUT)]")
    # You backed an underdog at 4.20 with ₹1,500.
    # In-play or closer to matchday, their odds drop to 2.30.
    initial_stake = 1500.0
    initial_odds = 4.20
    current_lay = 2.30
    
    hedge = calculate_green_up(initial_stake, initial_odds, current_lay)
    print(f"Initial Position : Backed @ {initial_odds} with ₹{initial_stake:,.2f}")
    print(f"Current Lay Odds : {current_lay}")
    print(f"Required Lay     : Place Lay bet of ₹{hedge['recommended_lay_stake_inr']:,.2f}")
    print(f"Exchange Risk    : Maximum Liability ₹{hedge['liability_inr']:,.2f}")
    print(f"Result (If Win)  : ₹{hedge['profit_if_win_inr']:+,.2f}")
    print(f"Result (If Lose) : ₹{hedge['profit_if_lose_inr']:+,.2f}")
    print(f"Locked Profit    : ₹{hedge['guaranteed_pnl_inr']:+,.2f} ({hedge['roi_percent']}% ROI guaranteed)")
    print("=" * 65 + "\n")