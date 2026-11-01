"""
exchange_execution.py
Handles order-book liquidity matching, slippage prevention,
and live position greening-up (hedging) across exchange ladders.
"""

def evaluate_liquidity_cap(suggested_stake, available_volume, min_stake=100.0):
    """
    Prevents execution slippage by capping the Kelly stake to the depth available
    at the top of the book. Returns 0.0 if volume is below exchange minimums.
    """
    if available_volume < min_stake:
        return {
            "can_execute": False,
            "executable_stake": 0.0,
            "reason": f"Available liquidity (₹{available_volume:,.2f}) is below minimum stake (₹{min_stake:,.2f})"
        }

    # Cap stake to available depth to prevent walking down the ladder
    actual_stake = min(suggested_stake, available_volume)

    return {
        "can_execute": True,
        "executable_stake": round(actual_stake, 2),
        "is_partial": actual_stake < suggested_stake,
        "unmatched_spillover": round(max(0.0, suggested_stake - actual_stake), 2)
    }

def calculate_full_ladder_green_up(entry_side, entry_odds, entry_stake, current_back_odds, current_lay_odds, commission=0.02):
    """
    Computes exact hedge/greening-up orders across both Back and Lay starting positions.
    
    Case A: Initial position was BACK (Buy low, sell high)
      Counter-order: LAY at current_lay_odds
      Formula: Target Lay Stake = (entry_stake * entry_odds) / current_lay_odds
      
    Case B: Initial position was LAY (Short-sell high, buy back cheap)
      Counter-order: BACK at current_back_odds
      Formula: Target Back Stake = (entry_stake * entry_odds) / current_back_odds
    """
    entry_side = entry_side.upper().strip()

    if entry_side == "BACK":
        if current_lay_odds <= 1.0:
            return {"actionable": False, "reason": "Invalid counter Lay odds"}
        
        counter_stake = (entry_stake * entry_odds) / current_lay_odds
        gross_profit = counter_stake - entry_stake
        net_profit = gross_profit * (1.0 - commission) if gross_profit > 0 else gross_profit

        roi_pct = (net_profit / entry_stake) * 100.0

        return {
            "actionable": True,
            "original_side": "BACK",
            "counter_action": "LAY",
            "counter_odds": current_lay_odds,
            "counter_stake": round(counter_stake, 2),
            "guaranteed_pnl_inr": round(net_profit, 2),
            "roi_pct": round(roi_pct, 2),
            "is_profitable": net_profit > 0
        }

    elif entry_side == "LAY":
        if current_back_odds <= 1.0:
            return {"actionable": False, "reason": "Invalid counter Back odds"}

        counter_stake = (entry_stake * entry_odds) / current_back_odds
        gross_profit = entry_stake - counter_stake
        net_profit = gross_profit * (1.0 - commission) if gross_profit > 0 else gross_profit

        liability = entry_stake * (entry_odds - 1.0)
        roi_pct = (net_profit / liability) * 100.0 if liability > 0 else 0.0

        return {
            "actionable": True,
            "original_side": "LAY",
            "counter_action": "BACK",
            "counter_odds": current_back_odds,
            "counter_stake": round(counter_stake, 2),
            "guaranteed_pnl_inr": round(net_profit, 2),
            "roi_pct": round(roi_pct, 2),
            "is_profitable": net_profit > 0
        }

    return {"actionable": False, "reason": "Unrecognized entry side"}

if __name__ == "__main__":
    print("=" * 70)
    print(" TESTING EXCHANGE EXECUTION & GREEN-UP ENGINE ")
    print("=" * 70)

    # TEST 1: Liquidity Cap check from the Elche vs Valencia order book
    # Screenshot: Best Back 1.33 has ₹389.29 depth; Lay 1.34 has ₹2,676.15 depth
    kelly_stake = 1500.0
    back_depth = 389.29

    check = evaluate_liquidity_cap(suggested_stake=kelly_stake, available_volume=back_depth)
    print("Test 1: Liquidity Filter (Valencia 1.33 Back)")
    print(f"  Kelly Calculated Stake : ₹{kelly_stake:,.2f}")
    print(f"  Top-of-Book Depth     : ₹{back_depth:,.2f}")
    print(f"  Executable Stake       : ₹{check['executable_stake']:,.2f} (Partial Fill: {check['is_partial']})")
    print(f"  Unmatched Spillover    : ₹{check['unmatched_spillover']:,.2f}")
    print("-" * 70)

    # TEST 2: Greening Up a Pre-Match Back position
    # Entered Pre-Match: Back Valencia @ 2.40 with ₹2,000 stake
    # In-Play (78th min, 0-1): Valencia Lay price is now 1.34
    entry_stk = 2000.0
    entry_odd = 2.40
    live_lay = 1.34

    hedge = calculate_full_ladder_green_up(
        entry_side="BACK",
        entry_odds=entry_odd,
        entry_stake=entry_stk,
        current_back_odds=1.33,
        current_lay_odds=live_lay
    )
    print("Test 2: Pre-Match BACK -> In-Play GREEN-UP (Valencia Win)")
    print(f"  Initial Position       : BACK ₹{entry_stk:,.2f} @ {entry_odd:.2f}")
    print(f"  Current Market Price   : LAY @ {live_lay:.2f}")
    print(f"  Action Required        : Submit {hedge['counter_action']} order for ₹{hedge['counter_stake']:,.2f} @ {hedge['counter_odds']:.2f}")
    print(f"  Guaranteed Locked P&L  : ₹{hedge['guaranteed_pnl_inr']:+,.2f} ({hedge['roi_pct']:+.1f}% Net ROI)")
    print("-" * 70)

    # TEST 3: Greening Up an In-Play Under 2.5 Goals Position
    # Entered: Back Under 2.5 @ 1.80 with ₹1,000
    # In-Play (78th min): Under 2.5 price drops to Lay 1.12
    totals_hedge = calculate_full_ladder_green_up(
        entry_side="BACK",
        entry_odds=1.80,
        entry_stake=1000.0,
        current_back_odds=1.11,
        current_lay_odds=1.12
    )
    print("Test 3: Totals Market GREEN-UP (Under 2.5 Goals)")
    print(f"  Initial Position       : BACK ₹1,000.00 @ 1.80")
    print(f"  Current Market Price   : LAY @ 1.12")
    print(f"  Action Required        : Submit LAY order for ₹{totals_hedge['counter_stake']:,.2f} @ {totals_hedge['counter_odds']:.2f}")
    print(f"  Guaranteed Locked P&L  : ₹{totals_hedge['guaranteed_pnl_inr']:+,.2f} ({totals_hedge['roi_pct']:+.1f}% Net ROI)")
    print("=" * 70)