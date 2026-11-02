"""
live_decay.py
Dynamic in-play time-decay Poisson pricer with non-linear goal distribution,
stoppage time expansion, Dixon-Coles adjustment, and green-up hedging.
"""

import math
from typing import Dict, Any, Tuple


# Empirical cumulative goal percentage by 15-minute segments across Europe's top 5 leagues
# 0-15': 12% | 16-30': 15% | 31-45': 17% (1H total = 44%)
# 46-60': 16% | 61-75': 18% | 76-90': 22% (2H total = 56%)
CUMULATIVE_GOAL_CURVE = [
    (0, 0.00),
    (15, 0.12),
    (30, 0.27),
    (45, 0.44),
    (60, 0.60),
    (75, 0.78),
    (90, 1.00)
]


def get_cumulative_goal_fraction(minute: float) -> float:
    """
    Interpolates empirical cumulative goal density F(t) from minute 0 to 90.
    Returns value between 0.0 (kickoff) and 1.0 (end of regulation).
    """
    if minute <= 0:
        return 0.0
    if minute >= 90:
        return 1.0

    for i in range(len(CUMULATIVE_GOAL_CURVE) - 1):
        t0, f0 = CUMULATIVE_GOAL_CURVE[i]
        t1, f1 = CUMULATIVE_GOAL_CURVE[i + 1]
        if t0 <= minute <= t1:
            # Linear piecewise interpolation
            slope = (f1 - f0) / (t1 - t0)
            return f0 + slope * (minute - t0)
    return 1.0


def calculate_decayed_lambdas(
    pre_match_lam_h: float,
    pre_match_lam_a: float,
    minute: int,
    stoppage_announced: int = 0,
    stoppage_elapsed: int = 0,
    home_reds: int = 0,
    away_reds: int = 0
) -> Tuple[float, float]:
    """
    Calculates remaining expected goals using non-linear timing and stoppage windows.
    """
    # 1. Regulation Remaining Weight (0 to 90)
    if minute < 90:
        elapsed_fraction = get_cumulative_goal_fraction(float(minute))
        base_regulation_remaining = max(0.0, 1.0 - elapsed_fraction)
    else:
        base_regulation_remaining = 0.0

    # 2. Stoppage Time Expansion
    # Intensity in stoppage time is calibrated to 76'-90' pressure (~0.0147 goals/min per team)
    stoppage_rate_per_min = (0.22 / 15.0)  # ~1.47% of total game goals per stoppage minute
    remaining_stoppage_mins = max(0, stoppage_announced - stoppage_elapsed)
    stoppage_remaining_fraction = remaining_stoppage_mins * stoppage_rate_per_min

    total_remaining_fraction = base_regulation_remaining + stoppage_remaining_fraction

    decayed_h = pre_match_lam_h * total_remaining_fraction
    decayed_a = pre_match_lam_a * total_remaining_fraction

    # 3. Tactical red card adjustments
    if home_reds > 0:
        decayed_h *= (0.72 ** home_reds)
        decayed_a *= (1.15 ** home_reds)
    if away_reds > 0:
        decayed_a *= (0.72 ** away_reds)
        decayed_h *= (1.15 ** away_reds)

    return max(0.001, decayed_h), max(0.001, decayed_a)


def dixon_coles_tau(x: int, y: int, lam_h: float, lam_a: float, rho: float = -0.11) -> float:
    """Low-score correlation factor."""
    if x == 0 and y == 0:
        return 1.0 - (lam_h * lam_a * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lam_h * rho)
    elif x == 1 and y == 0:
        return 1.0 + (lam_a * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def calculate_live_odds(
    pre_match_lam_h: float,
    pre_match_lam_a: float,
    minute: int,
    home_score: int,
    away_score: int,
    stoppage_announced: int = 0,
    stoppage_elapsed: int = 0,
    home_reds: int = 0,
    away_reds: int = 0,
    rho: float = -0.11,
    max_additional_goals: int = 6
) -> Dict[str, Any]:
    """
    Computes fair 1X2 in-play probabilities and odds reflecting current clock status.
    """
    lam_h_rem, lam_a_rem = calculate_decayed_lambdas(
        pre_match_lam_h=pre_match_lam_h,
        pre_match_lam_a=pre_match_lam_a,
        minute=minute,
        stoppage_announced=stoppage_announced,
        stoppage_elapsed=stoppage_elapsed,
        home_reds=home_reds,
        away_reds=away_reds
    )

    def poisson_pmf(k: int, lam: float) -> float:
        return (lam ** k * math.exp(-lam)) / math.factorial(k)

    prob_home_win = 0.0
    prob_draw = 0.0
    prob_away_win = 0.0

    for add_h in range(max_additional_goals):
        p_h = poisson_pmf(add_h, lam_h_rem)
        for add_a in range(max_additional_goals):
            p_a = poisson_pmf(add_a, lam_a_rem)
            tau = dixon_coles_tau(add_h, add_a, lam_h_rem, lam_a_rem, rho)
            cell_prob = p_h * p_a * tau

            final_h = home_score + add_h
            final_a = away_score + add_a

            if final_h > final_a:
                prob_home_win += cell_prob
            elif final_h == final_a:
                prob_draw += cell_prob
            else:
                prob_away_win += cell_prob

    total_prob = prob_home_win + prob_draw + prob_away_win
    if total_prob > 0:
        p_h = prob_home_win / total_prob
        p_d = prob_draw / total_prob
        p_a = prob_away_win / total_prob
    else:
        p_h, p_d, p_a = 0.0, 1.0, 0.0

    fair_home = round(1.0 / p_h, 2) if p_h > 0.001 else 999.0
    fair_draw = round(1.0 / p_d, 2) if p_d > 0.001 else 999.0
    fair_away = round(1.0 / p_a, 2) if p_a > 0.001 else 999.0

    clock_display = f"{minute}'"
    if minute >= 90 and stoppage_announced > 0:
        clock_display = f"90+{stoppage_elapsed}' (of +{stoppage_announced}')"

    return {
        "clock": clock_display,
        "current_score": f"{home_score}-{away_score}",
        "lam_h_remaining": round(lam_h_rem, 3),
        "lam_a_remaining": round(lam_a_rem, 3),
        "probs": {"home": round(p_h, 4), "draw": round(p_d, 4), "away": round(p_a, 4)},
        "fair_odds": {"home": fair_home, "draw": fair_draw, "away": fair_away}
    }


def calculate_green_up_hedge(
    back_stake: float,
    back_odds: float,
    current_lay_odds: float,
    commission: float = 0.02
) -> Dict[str, float]:
    """Computes exact Lay stake to equalize profit across all outcomes."""
    if current_lay_odds <= 1.0:
        return {"lay_stake": 0.0, "locked_profit": 0.0}

    lay_stake = (back_stake * back_odds) / (current_lay_odds - commission)
    profit_if_win = (back_stake * (back_odds - 1.0)) - (lay_stake * (current_lay_odds - 1.0))
    net_profit = profit_if_win * (1.0 - commission)

    return {
        "lay_stake": round(lay_stake, 2),
        "locked_profit": round(net_profit, 2)
    }