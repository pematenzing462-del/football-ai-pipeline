import sqlite3
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

def display_logged_trades():
    conn = sqlite3.connect("trades.db")
    query = """
        SELECT 
            id,
            timestamp,
            match_name,
            market_type,
            selection,
            bookmaker,
            market_odds,
            stake_inr,
            status,
            result_score,
            pnl_inr
        FROM signals
        ORDER BY id DESC
    """
    
    try:
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            print("\nDatabase is currently empty.")
            return

        print("\n" + "=" * 95)
        print(" RECORDED TRADES & REALIZED P&L (TRADES.DB) ")
        print("=" * 95)
        print(df.to_string(index=False))
        print("=" * 95)
        
        # Calculate overall ledger metrics
        total_staked = df["stake_inr"].sum()
        settled_df = df[df["status"] != "PENDING"]
        net_pnl = settled_df["pnl_inr"].sum()
        
        print(f"Total Trades: {len(df)} | Settled: {len(settled_df)}")
        print(f"Total Staked: ₹{total_staked:,.2f} | Net Realized P&L: ₹{net_pnl:+,.2f}\n")

    except sqlite3.OperationalError as e:
        print(f"Database error: {e}")
        conn.close()

if __name__ == "__main__":
    display_logged_trades()