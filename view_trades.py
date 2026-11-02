"""
view_trades.py
Terminal inspector for trades.db.
Displays pending exposure, settled performance, and full trade details.
"""

import sqlite3
import os

DB_NAME = "trades.db"

def inspect_trades():
    if not os.path.exists(DB_NAME):
        print(f"[!] Database file '{DB_NAME}' not found.")
        return

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM trades ORDER BY id DESC")
        rows = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"[!] Error querying database: {e}")
        conn.close()
        return

    if not rows:
        print("[*] trades.db is initialized, but no trades have been recorded yet.")
        conn.close()
        return

    pending = [r for r in rows if r["status"] == "PENDING"]
    settled = [r for r in rows if r["status"] in ("WON", "LOST", "VOID")]

    # Portfolio exposure summary
    total_staked_pending = sum(r["stake"] for r in pending)
    realized_pnl = sum(r["pnl"] for r in settled)

    print("=" * 105)
    print(" PORTFOLIO EXECUTIVE SUMMARY")
    print("=" * 105)
    print(f"Total Logged Trades : {len(rows)}")
    print(f"Active Pending      : {len(pending)} (Total Exposure: ₹{total_staked_pending:,.2f})")
    print(f"Settled Trades      : {len(settled)} (Realized P&L: ₹{realized_pnl:+,.2f})")
    print("=" * 105)

    # 1. PENDING TRADES TABLE
    if pending:
        print("\n[ACTIVE PENDING TICKETS]")
        print("-" * 105)
        header = f"{'ID':<4} | {'Match':<30} | {'Pick':<6} | {'Odds':<6} | {'Fair':<6} | {'Edge %':<8} | {'Stake (₹)':<10} | {'Commence'}"
        print(header)
        print("-" * 105)

        for t in pending:
            match_str = f"{t['home_team']} vs {t['away_team']}"[:30]
            commence = str(t['commence_time'])[:16].replace("T", " ")
            print(
                f"{t['id']:<4} | {match_str:<30} | {t['selection']:<6} | "
                f"{t['odds']:<6.2f} | {t['fair_odds']:<6.2f} | +{t['edge_pct']:<7.2f} | "
                f"₹{t['stake']:<9.2f} | {commence}"
            )
        print("-" * 105)

    # 2. SETTLED TRADES TABLE
    if settled:
        print("\n[SETTLED TICKETS]")
        print("-" * 105)
        s_header = f"{'ID':<4} | {'Match':<28} | {'Pick':<6} | {'Odds':<6} | {'Score':<7} | {'Result':<6} | {'P&L (₹)':<10} | {'CLV %'}"
        print(s_header)
        print("-" * 105)

        for s in settled:
            match_str = f"{s['home_team']} vs {s['away_team']}"[:28]
            score_str = s['final_score'] if s['final_score'] else "N/A"
            clv_str = f"{s['clv_pct']:+.2f}%" if s['clv_pct'] is not None else "N/A"
            pnl_val = s['pnl']
            pnl_str = f"{pnl_val:+,.2f}"

            print(
                f"{s['id']:<4} | {match_str:<28} | {s['selection']:<6} | "
                f"{s['odds']:<6.2f} | {score_str:<7} | {s['status']:<6} | "
                f"₹{pnl_str:<9} | {clv_str}"
            )
        print("-" * 105)

    conn.close()

if __name__ == "__main__":
    inspect_trades()