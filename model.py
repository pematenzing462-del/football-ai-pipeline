import numpy as np
from scipy.stats import poisson

def apply_dixon_coles_tau(x, y, lam_x, lam_y, rho=-0.11):
    """
    Dixon-Coles low-score correction factor tau(x, y).
    Adjusts correlation for 0-0, 1-0, 0-1, and 1-1 scorelines.
    """
    if x == 0 and y == 0:
        return 1.0 - (lam_x * lam_y * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lam_x * rho)
    elif x == 1 and y == 0:
        return 1.0 + (lam_y * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0

def adjust_inplay_lambdas(lam_home_pre, lam_away_pre, minute, current_home_goals=0, current_away_goals=0):
    """
    Adjusts home and away lambdas based on elapsed time and in-play game state.
    """
    if minute >= 90:
        # Minimal baseline for injury time
        remaining_fraction = 0.033  # ~3 mins stoppage
    else:
        remaining_fraction = max(0.0, (90.0 - minute) / 90.0)

    # Base decay strictly from remaining clock
    lam_home_rem = lam_home_pre * remaining_fraction
    lam_away_rem = lam_away_pre * remaining_fraction

    # Game-state tactical adjustments
    goal_diff = current_home_goals - current_away_goals

    # Home trailing
    if goal_diff < 0:
        # Home pushes forward, away counters
        lam_home_rem *= 1.12
        lam_away_rem *= 1.15
    # Away trailing
    elif goal_diff > 0:
        # Away pushes forward, home counters
        lam_away_rem *= 1.12
        lam_home_rem *= 1.15
    else:
        # Draw game: risk-averse late game (after 70 mins)
        if minute >= 70:
            lam_home_rem *= 0.92
            lam_away_rem *= 0.92

    return round(lam_home_rem, 4), round(lam_away_rem, 4)

def build_score_matrix(lam_home, lam_away, max_goals=10, rho=-0.11):
    """
    Builds a bivariate Poisson probability grid using Dixon-Coles adjustment.
    """
    matrix = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            p_i = poisson.pmf(i, lam_home)
            p_j = poisson.pmf(j, lam_away)
            tau = apply_dixon_coles_tau(i, j, lam_home, lam_away, rho)
            matrix[i, j] = p_i * p_j * tau

    # Normalize matrix so total probability sums to 1.0
    return matrix / np.sum(matrix)

def derive_match_markets(score_grid, current_home=0, current_away=0):
    """
    Derives true fair odds and probabilities for 1X2 and Over/Under totals,
    offsetting by the current in-play score.
    """
    max_goals = score_grid.shape[0]
    
    p_home_win = 0.0
    p_away_win = 0.0
    p_draw = 0.0

    p_over_1_5 = 0.0
    p_over_2_5 = 0.0
    p_over_3_5 = 0.0

    for rem_h in range(max_goals):
        for rem_a in range(max_goals):
            prob = score_grid[rem_h, rem_a]
            
            # Final full-time score
            final_h = current_home + rem_h
            final_a = current_away + rem_a
            total_goals = final_h + final_a

            # 1X2 Probabilities
            if final_h > final_a:
                p_home_win += prob
            elif final_a > final_h:
                p_away_win += prob
            else:
                p_draw += prob

            # Totals Probabilities
            if total_goals > 1.5:
                p_over_1_5 += prob
            if total_goals > 2.5:
                p_over_2_5 += prob
            if total_goals > 3.5:
                p_over_3_5 += prob

    def to_odds(p):
        return round(1.0 / p, 2) if p > 0.0001 else 999.0

    return {
        "home_win": {"prob": round(p_home_win, 4), "fair_odds": to_odds(p_home_win)},
        "away_win": {"prob": round(p_away_win, 4), "fair_odds": to_odds(p_away_win)},
        "draw": {"prob": round(p_draw, 4), "fair_odds": to_odds(p_draw)},
        "over_1_5": {"prob": round(p_over_1_5, 4), "fair_odds": to_odds(p_over_1_5)},
        "under_1_5": {"prob": round(1.0 - p_over_1_5, 4), "fair_odds": to_odds(1.0 - p_over_1_5)},
        "over_2_5": {"prob": round(p_over_2_5, 4), "fair_odds": to_odds(p_over_2_5)},
        "under_2_5": {"prob": round(1.0 - p_over_2_5, 4), "fair_odds": to_odds(1.0 - p_over_2_5)},
        "over_3_5": {"prob": round(p_over_3_5, 4), "fair_odds": to_odds(p_over_3_5)},
        "under_3_5": {"prob": round(1.0 - p_over_3_5, 4), "fair_odds": to_odds(1.0 - p_over_3_5)},
    }

def calculate_edge_and_kelly(model_prob, market_odds, bankroll=25000.0, fraction=0.25):
    """
    Computes Expected Value (EV) and Fractional Kelly Stake in INR.
    """
    ev = (model_prob * market_odds) - 1.0
    if ev <= 0 or market_odds <= 1.0:
        return round(ev, 4), 0.0

    b = market_odds - 1.0
    p = model_prob
    q = 1.0 - p
    full_kelly = (b * p - q) / b
    
    suggested_stake = max(0.0, full_kelly * fraction * bankroll)
    return round(ev, 4), round(suggested_stake, 2)

if __name__ == "__main__":
    print("=" * 65)
    print(" IN-PLAY DIXON-COLES ENGINE: ELCHE VS VALENCIA TEST ")
    print("=" * 65)

    # 1. Baseline pre-match full-game expected goals
    lam_home_pre = 1.05  # Elche
    lam_away_pre = 1.45  # Valencia

    # 2. Live Match State from the screenshot: 78th minute, Elche 0 - 1 Valencia
    minute = 78
    cur_home = 0
    cur_away = 1

    lam_home_rem, lam_away_rem = adjust_inplay_lambdas(
        lam_home_pre, lam_away_pre, minute, cur_home, cur_away
    )
    
    print(f"Match State     : Minute {minute}' | Score: {cur_home}-{cur_away}")
    print(f"Remaining Lambdas: Elche λ_rem = {lam_home_rem} | Valencia λ_rem = {lam_away_rem}")

    # 3. Build remaining goals matrix & derive final markets
    rem_grid = build_score_matrix(lam_home_rem, lam_away_rem)
    markets = derive_match_markets(rem_grid, cur_home, cur_away)

    print("\n--- IN-PLAY FAIR PROBABILITIES & ODDS ---")
    print(f"Valencia Win (1.33 Back / 1.34 Lay): Fair Odds {markets['away_win']['fair_odds']} (Prob: {markets['away_win']['prob']*100:.1f}%)")
    print(f"The Draw     (4.60 Back / 4.70 Lay): Fair Odds {markets['draw']['fair_odds']} (Prob: {markets['draw']['prob']*100:.1f}%)")
    print(f"Elche Win    (28.0 Back / 30.0 Lay): Fair Odds {markets['home_win']['fair_odds']} (Prob: {markets['home_win']['prob']*100:.1f}%)")
    print("-" * 65)
    print(f"Under 2.5 Goals (1.11 Back / 1.12 Lay): Fair Odds {markets['under_2_5']['fair_odds']} (Prob: {markets['under_2_5']['prob']*100:.1f}%)")
    print(f"Over 2.5 Goals  (9.80 Back / 10.0 Lay): Fair Odds {markets['over_2_5']['fair_odds']} (Prob: {markets['over_2_5']['prob']*100:.1f}%)")
    print("=" * 65)