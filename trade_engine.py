def calculate_green_up(back_stake, back_odds, current_lay_odds, commission=0.02):
    """
    Calculates the exact Lay stake required to lock in an equal, 
    risk-free profit across all outcomes (Greening-Up).
    """
    if current_lay_odds <= 1.0 or back_odds <= 1.0:
        return {"lay_stake": 0.0, "net_profit": 0.0}

    # Hedged lay stake formula: (Back Stake * Back Odds) / Current Lay Odds
    target_lay_stake = round((back_stake * back_odds) / current_lay_odds, 2)
    
    # Gross profit before commission
    gross_profit = target_lay_stake - back_stake
    net_profit = round(gross_profit * (1.0 - commission), 2) if gross_profit > 0 else round(gross_profit, 2)
    
    return {
        "lay_stake": target_lay_stake,
        "net_profit": net_profit,
        "is_profitable": net_profit > 0
    }

def evaluate_market_trade(model_prob, back_odds, lay_odds, commission=0.02):
    """
    Evaluates both sides of an exchange order book (Back vs Lay).
    Returns whether to Back (Buy), Lay (Short-Sell), or Pass.
    """
    # 1. Back EV: Expected return on standard buy
    back_ev = (model_prob * back_odds) - 1.0
    
    # 2. Lay EV: Net expected value of short-selling (taking backer's money)
    # Lay wins when event fails: (1 - p) * Stake * (1 - comm)
    # Lay loses when event occurs: -p * Liability = -p * Stake * (lay_odds - 1)
    prob_fail = 1.0 - model_prob
    net_win_factor = 1.0 - commission
    loss_factor = lay_odds - 1.0
    lay_ev = (prob_fail * net_win_factor) - (model_prob * loss_factor)

    back_ev_pct = round(back_ev * 100.0, 2)
    lay_ev_pct = round(lay_ev * 100.0, 2)

    if back_ev > 0.02 and back_ev >= lay_ev:
        return {
            "action": "BACK (BUY)",
            "side": "BACK",
            "back_ev_pct": back_ev_pct,
            "lay_ev_pct": lay_ev_pct,
            "selected_odds": back_odds
        }
    elif lay_ev > 0.02 and lay_ev > back_ev:
        return {
            "action": "LAY (SHORT-SELL)",
            "side": "LAY",
            "back_ev_pct": back_ev_pct,
            "lay_ev_pct": lay_ev_pct,
            "selected_odds": lay_odds
        }
    else:
        return {
            "action": "PASS",
            "side": "NONE",
            "back_ev_pct": back_ev_pct,
            "lay_ev_pct": lay_ev_pct,
            "selected_odds": 0.0
        }

def evaluate_draw_sniper(lam_home, lam_away, model_draw_prob, draw_market_odds, min_edge_pct=8.0):
    """
    Screens for high-edge draw trades in low-scoring/defensive fixtures.
    Flags opportunities where retail neglect pushes market draw odds into +EV territory.
    """
    projected_total = lam_home + lam_away
    
    # Condition 1: Projected total goals must indicate a low/medium scoring environment
    if projected_total > 2.30:
        return {"qualified": False, "reason": f"Expected goals too high ({projected_total:.2f} > 2.30)"}
    
    # Condition 2: Check EV against market odds
    fair_odds = round(1.0 / model_draw_prob, 2) if model_draw_prob > 0 else 999.0
    ev = (model_draw_prob * draw_market_odds) - 1.0
    edge_pct = round(ev * 100.0, 2)
    
    if edge_pct < min_edge_pct:
        return {
            "qualified": False, 
            "reason": f"Edge below threshold (+{edge_pct}% < +{min_edge_pct}%)",
            "edge_pct": edge_pct,
            "fair_odds": fair_odds
        }
        
    return {
        "qualified": True,
        "edge_pct": edge_pct,
        "fair_odds": fair_odds,
        "market_odds": draw_market_odds,
        "model_prob": model_draw_prob,
        "projected_total": round(projected_total, 2)
    }
    print("=" * 65 + "\n")