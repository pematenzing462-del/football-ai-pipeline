"""
exchange_execution.py
Exchange execution and market microstructure layer.
Enforces order book liquidity caps, maximum bankroll liability limits,
and execution price cutoffs to protect against slippage.
"""

def enforce_liquidity_cap(
    requested_stake: float,
    market_odds: float,
    bankroll: float = 25000.0,
    max_bankroll_pct: float = 0.05,
    min_stake_threshold: float = 50.0
):
    """
    Enforces risk constraints and liquidity limits on a trade order:
    1. Hard ceiling: No single trade can exceed max_bankroll_pct (default: 5% = ₹1,250 on ₹25,000).
    2. Longshot liability dampener: Reduces stake on high-odds outcomes (> 6.00) to limit tail variance.
    3. Minimum threshold: Discards micro-stakes below min_stake_threshold (e.g. ₹50) where exchange commission/fees distort ROI.

    Returns:
        (final_stake: float, capped: bool)
    """
    if requested_stake <= 0.0 or market_odds <= 1.0:
        return 0.0, False

    capped = False
    stake = requested_stake

    # 1. Hard maximum stake ceiling (e.g., 5% of active bankroll)
    max_allowed_stake = bankroll * max_bankroll_pct
    if stake > max_allowed_stake:
        stake = max_allowed_stake
        capped = True

    # 2. Longshot liability scaling: dampen stakes when odds are high
    # When odds > 6.0, suppress stake so downside variance doesn't spike
    if market_odds > 6.0:
        odds_dampener = 6.0 / market_odds
        adjusted_stake = stake * odds_dampener
        if adjusted_stake < stake:
            stake = adjusted_stake
            capped = True

    # 3. Minimum viable trade size
    if stake < min_stake_threshold:
        return 0.0, False

    return round(stake, 2), capped

def calculate_execution_cutoff(fair_odds: float, buffer_pct: float = 0.02):
    """
    Computes minimum acceptable price cutoff.
    If market odds drift below this price, the edge is erased by exchange slippage.
    """
    return round(fair_odds * (1.0 + buffer_pct), 2)

if __name__ == "__main__":
    print("=" * 60)
    print(" TESTING EXCHANGE EXECUTION LAYER ")
    print("=" * 60)

    # Test cases
    test_bankroll = 25000.0

    # Case 1: Normal stake within limits
    s1, c1 = enforce_liquidity_cap(requested_stake=450.0, market_odds=2.40, bankroll=test_bankroll)
    print(f"Normal Order (₹450 @ 2.40): Executed = ₹{s1} | Capped = {c1}")

    # Case 2: Stake exceeds 5% bankroll cap (₹1,800 > ₹1,250)
    s2, c2 = enforce_liquidity_cap(requested_stake=1800.0, market_odds=2.10, bankroll=test_bankroll)
    print(f"Oversized Order (₹1,800 @ 2.10): Executed = ₹{s2} | Capped = {c2}")

    # Case 3: High odds dampener (₹800 @ 10.0)
    s3, c3 = enforce_liquidity_cap(requested_stake=800.0, market_odds=10.0, bankroll=test_bankroll)
    print(f"Longshot Order (₹800 @ 10.0): Executed = ₹{s3} | Capped = {c3}")

    # Case 4: Micro-stake below threshold (₹30 < ₹50)
    s4, c4 = enforce_liquidity_cap(requested_stake=30.0, market_odds=1.90, bankroll=test_bankroll)
    print(f"Micro Order (₹30 @ 1.90): Executed = ₹{s4} (Discarded)")
    print("=" * 60)