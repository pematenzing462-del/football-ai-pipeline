import numpy as np
from scipy.stats import poisson

# Empirical Dixon-Coles parameter for low-scoring matches (0-0, 1-0, 0-1, 1-1)
RHO = -0.11

def tau_correction(x, y, lam, mu, rho=RHO):
    """
    Applies the Dixon-Coles adjustment for low-scoring dependency.
    """
    if x == 0 and y == 0:
        return 1.0 - (lam * mu * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lam * rho)
    elif x == 1 and y == 0:
        return 1.0 + (mu * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0

def build_score_matrix(lambda_home, lambda_away, max_goals=6):
    """
    Constructs a 2D probability matrix of exact scorelines up to max_goals.
    Rows = Home Goals (0 to 6), Columns = Away Goals (0 to 6).
    """
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p_h = poisson.pmf(h, lambda_home)
            p_a = poisson.pmf(a, lambda_away)
            tau = tau_correction(h, a, lambda_home, lambda_away)
            matrix[h, a] = tau * p_h * p_a
            
    # Normalize matrix so total sum of probabilities equals 1.0
    matrix = matrix / np.sum(matrix)
    return matrix

def derive_match_markets(score_matrix):
    """
    Extracts 1X2 outcomes, Over/Under 2.5, and BTTS from the score matrix.
    """
    # 1X2 Probabilities
    prob_home_win = np.sum(np.tril(score_matrix, -1))
    prob_draw = np.sum(np.diag(score_matrix))
    prob_away_win = np.sum(np.triu(score_matrix, 1))
    
    # Over / Under 2.5
    under_2_5 = 0.0
    for h in range(score_matrix.shape[0]):
        for a in range(score_matrix.shape[1]):
            if (h + a) < 2.5:
                under_2_5 += score_matrix[h, a]
    over_2_5 = 1.0 - under_2_5

    return {
        "home_win": {"prob": prob_home_win, "fair_odds": 1.0 / prob_home_win},
        "draw": {"prob": prob_draw, "fair_odds": 1.0 / prob_draw},
        "away_win": {"prob": prob_away_win, "fair_odds": 1.0 / prob_away_win},
        "over_2_5": {"prob": over_2_5, "fair_odds": 1.0 / over_2_5},
        "under_2_5": {"prob": under_2_5, "fair_odds": 1.0 / under_2_5}
    }

def calculate_edge_and_kelly(model_prob, market_odds, bankroll=25000.0, fraction=0.25):
    """
    Expected Value (EV) and Quarter-Kelly stake calculation.
    """
    ev = (model_prob * market_odds) - 1.0
    b = market_odds - 1.0
    p = model_prob
    q = 1.0 - p
    
    raw_kelly = (b * p - q) / b
    
    if ev > 0 and raw_kelly > 0:
        recommended_stake = bankroll * (raw_kelly * fraction)
        return ev, round(recommended_stake, 2)
    return ev, 0.0

if __name__ == "__main__":
    # Test simulation: Home xG = 1.65, Away xG = 1.10
    lam_h = 1.65
    lam_a = 1.10
    
    grid = build_score_matrix(lam_h, lam_a)
    markets = derive_match_markets(grid)
    
    print("=== DIXON-COLES MATRIX SIMULATION ===")
    print(f"Top 3 Most Likely Exact Scorelines:")
    
    # Flatten and sort exact scores
    scores = []
    for h in range(grid.shape[0]):
        for a in range(grid.shape[1]):
            scores.append((f"{h}-{a}", grid[h, a]))
    scores.sort(key=lambda x: x[1], reverse=True)
    
    for score, p in scores[:3]:
        print(f"  {score} -> Probability: {p*100:.1f}% | Fair Odds: {1/p:.2f}")
        
    print("\nDerived 1X2 Fair Odds:")
    print(f"  Home Win: {markets['home_win']['prob']*100:.1f}% (Odds: {markets['home_win']['fair_odds']:.2f})")
    print(f"  Draw:     {markets['draw']['prob']*100:.1f}% (Odds: {markets['draw']['fair_odds']:.2f})")
    print(f"  Away Win: {markets['away_win']['prob']*100:.1f}% (Odds: {markets['away_win']['fair_odds']:.2f})")