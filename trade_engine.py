"""
trade_engine.py
Execution valuation, steam velocity tracking, and trade generation engine.
Calculates net expected value (+EV) accounting for exchange commissions,
determines quarter-Kelly stake sizing, validates opportunities against
Pinnacle's no-vig benchmark, and detects institutional line steam.
"""

def devig_pinnacle_odds(pinny_home: float, pinny_draw: float, pinny_away: float):
    """
    Strips the bookmaker margin (vig) from Pinnacle's 3-way odds
    using proportional (multiplicative) normalization.
    """
    if pinny_home <= 1.0 or pinny_draw <= 1.0 or pinny_away <= 1.0:
        return {}

    # Calculate raw implied probabilities
    raw_p_home = 1.0 / pinny_home
    raw_p_draw = 1.0 / pinny_draw
    raw_p_away = 1.0 / pinny_away

    # Total overround (bookmaker margin)
    total_overround = raw_p_home + raw_p_draw + raw_p_away
    if total_overround <= 0.0:
        return {}

    # Strip margin to obtain true fair probabilities
    fair_p_home = raw_p_home / total_overround
    fair_p_draw = raw_p_draw / total_overround
    fair_p_away = raw_p_away / total_overround

    return {
        "Home": {"prob": fair_p_home, "fair_odds": round(1.0 / fair_p_home, 2)},
        "Draw": {"prob": fair_p_draw, "fair_odds": round(1.0 / fair_p_draw, 2)},
        "Away": {"prob": fair_p_away, "fair_odds": round(1.0 / fair_p_away, 2)},
        "overround_pct": round((total_overround - 1.0) * 100.0, 2)
    }

def detect_steam_move(
    current_pinny_odds: float,
    prior_pinny_odds: float,
    retail_odds: float,
    prob_shift_threshold: float = 0.04
):
    """
    Detects institutional steam moves on Pinnacle and identifies lagging retail prices.

    Args:
        current_pinny_odds: Pinnacle's current market price.
        prior_pinny_odds: Pinnacle's price from an earlier snapshot.
        retail_odds: Current price offered by a retail/soft book.
        prob_shift_threshold: Minimum shift in implied probability to classify as steam (default: 4%).

    Returns:
        (is_steam: bool, lag_edge_pct: float, reason: str)
    """
    if not current_pinny_odds or not prior_pinny_odds or retail_odds <= 1.0:
        return False, 0.0, ""

    prior_prob = 1.0 / prior_pinny_odds
    current_prob = 1.0 / current_pinny_odds
    prob_delta = current_prob - prior_prob

    # Steam condition: Probability spiked sharply (odds dropped significantly)
    if prob_delta < prob_shift_threshold:
        return False, 0.0, ""

    # Check if retail book hasn't adjusted down to match the sharp market move
    if retail_odds > current_pinny_odds:
        lag_edge = (retail_odds / current_pinny_odds) - 1.0
        reason = (
            f"Pinny shifted {prior_pinny_odds:.2f} -> {current_pinny_odds:.2f} "
            f"(+{prob_delta*100:.1f}% implied prob shift). Retail lagging at {retail_odds:.2f}."
        )
        return True, round(lag_edge * 100.0, 2), reason

    return False, 0.0, ""

def calculate_net_edge(model_prob: float, market_odds: float, commission: float = 0.02):
    """
    Computes true edge after subtracting exchange commission from winnings.
    Commission applies strictly to net profit: (odds - 1.0) * (1.0 - commission).
    """
    if model_prob <= 0.0 or market_odds <= 1.0:
        return -1.0, 0.0

    net_odds = 1.0 + (market_odds - 1.0) * (1.0 - commission)
    expected_value = (model_prob * net_odds) - 1.0
    return round(expected_value, 4), round(net_odds, 4)

def calculate_fractional_kelly(model_prob: float, net_odds: float, bankroll: float = 25000.0, fraction: float = 0.25):
    """
    Calculates stake size in INR using Fractional Kelly criterion (quarter-Kelly).
    """
    if net_odds <= 1.0 or model_prob <= 0.0:
        return 0.0

    b = net_odds - 1.0
    p = model_prob
    q = 1.0 - p

    full_kelly = (b * p - q) / b
    if full_kelly <= 0.0:
        return 0.0

    raw_stake = full_kelly * fraction * bankroll
    return round(raw_stake, 2)

def evaluate_match_edges(
    probs: dict,
    market_odds: dict,
    pinnacle_odds: dict = None,
    bankroll: float = 25000.0,
    commission: float = 0.02,
    min_edge: float = 0.02,
    require_pinny_agreement: bool = False
):
    """
    Evaluates 1X2 market outcomes for positive expected value (+EV).
    If require_pinny_agreement=True, only triggers when Pinnacle's no-vig line agrees.
    """
    opportunities = []
    outcomes = ["Home", "Draw", "Away"]

    pinny_devigged = {}
    if pinnacle_odds and all(pinnacle_odds.get(k, 0) > 1.0 for k in outcomes):
        pinny_devigged = devig_pinnacle_odds(
            pinnacle_odds["Home"],
            pinnacle_odds["Draw"],
            pinnacle_odds["Away"]
        )

    for outcome in outcomes:
        model_p = probs.get(outcome, 0.0)
        taken_odds = market_odds.get(outcome, 0.0)

        if model_p <= 0.001 or taken_odds <= 1.0:
            continue

        fair_odds = round(1.0 / model_p, 2)
        model_edge, net_odds = calculate_net_edge(model_p, taken_odds, commission=commission)

        if model_edge <= min_edge:
            continue

        pinny_edge = None
        pinny_fair_odds = None
        if pinny_devigged and outcome in pinny_devigged:
            sharp_prob = pinny_devigged[outcome]["prob"]
            pinny_fair_odds = pinny_devigged[outcome]["fair_odds"]
            pinny_edge = (sharp_prob * (1.0 + (taken_odds - 1.0) * (1.0 - commission))) - 1.0

            if require_pinny_agreement and pinny_edge <= 0.0:
                continue

        stake = calculate_fractional_kelly(model_p, net_odds, bankroll=bankroll, fraction=0.25)
        if stake > 0:
            opportunities.append({
                "outcome": outcome,
                "fair_odds": fair_odds,
                "market_odds": taken_odds,
                "edge_pct": round(model_edge * 100.0, 2),
                "stake": stake,
                "pinny_fair_odds": pinny_fair_odds,
                "pinny_edge_pct": round(pinny_edge * 100.0, 2) if pinny_edge is not None else None
            })

    return opportunities

def should_snipe_draw(lambda_total: float, prob_draw: float, market_draw_odds: float):
    """
    Draw-Sniper quantitative heuristic for low-scoring profiles.
    """
    if lambda_total <= 2.25 and prob_draw >= 0.28:
        fair_draw = round(1.0 / prob_draw, 2)
        if market_draw_odds > fair_draw:
            return True, f"Low λ ({lambda_total:.2f}) + P(Draw) {prob_draw*100:.1f}%"
    return False, ""