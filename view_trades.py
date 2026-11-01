import sqlite3
import pandas as pd

DB_NAME = "trades.db"

def display_trade_ledger():
    conn = sqlite3.connect(DB_NAME)
    
    # Read the updated table schema
    query = """
        SELECT 
            id AS ID,
            timestamp AS Date,
            match_name AS Match,
            market_type AS Market,
            selection AS Pick,
            bookmaker AS Bookie,
            market_odds AS Odds,
            closing_odds AS Closing,
            clv_percent AS `CLV %`,
            edge_percent AS `Edge %`,
            stake_inr AS `Stake (INR)`,
            status AS Status,
            score AS Score,
            pnl_inr AS `P&L (INR)`
        FROM trades
        ORDER BY id DESC
    """
    
    try:
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"Error reading trades from {DB_NAME}: {e}")
        conn.close()
        return

    conn.close()

    if df.empty:
        print("\nNo trades recorded in trades.db yet.")
        return

    # Set Pandas display rules for clean console formatting
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)
    pd.set_option("display.colheader_justify", "left")

    # Format numeric columns for presentation
    df_display = df.copy()
    df_display["Date"] = pd.to_datetime(df_display["Date"]).dt.strftime("%Y-%m-%d %H:%M")
    df_display["Odds"] = df_display["Odds"].map(lambda x: f"{x:.2f}" if pd.notnull(x) else "-")
    df_display["Closing"] = df_display["Closing"].map(lambda x: f"{x:.2f}" if pd.notnull(x) else "-")
    df_display["CLV %"] = df_display["CLV %"].map(lambda x: f"{x:+.2f}%" if pd.notnull(x) else "-")
    df_display["Edge %"] = df_display["Edge %"].map(lambda x: f"+{x:.2f}%" if pd.notnull(x) else "-")
    df_display["Stake (INR)"] = df_display["Stake (INR)"].map(lambda x: f"₹{x:,.2f}" if pd.notnull(x) else "-")
    df_display["P&L (INR)"] = df_display["P&L (INR)"].map(lambda x: f"₹{x:+,.2f}" if pd.notnull(x) else "-")
    df_display["Score"] = df_display["Score"].fillna("-")

    print("\n" + "=" * 125)
    print(" QUANTITATIVE TRADE LEDGER: LIVE & SETTLED POSITIONS WITH CLV ")
    print("=" * 125)
    print(df_display.to_string(index=False))
    print("=" * 125)

    # Performance Summary Analytics
    total_trades = len(df)
    settled = df[df["Status"].isin(["WON", "LOST"])]
    pending = df[df["Status"] == "PENDING"]
    
    total_pnl = settled["P&L (INR)"].sum() if not settled.empty else 0.0
    wins = len(settled[settled["Status"] == "WON"])
    losses = len(settled[settled["Status"] == "LOST"])
    win_rate = (wins / len(settled) * 100) if len(settled) > 0 else 0.0

    # CLV Metric: True indicator of beating market closing consensus
    valid_clv = df["CLV %"].dropna()
    avg_clv = valid_clv.mean() if not valid_clv.empty else None

    print("\n--- PORTFOLIO METRICS ---")
    print(f"Total Logged Trades : {total_trades} (Settled: {len(settled)} | Pending: {len(pending)})")
    print(f"Record              : {wins}W - {losses}L (Win Rate: {win_rate:.1f}%)")
    print(f"Total Realized P&L  : ₹{total_pnl:+,.2f}")
    if avg_clv is not None:
        print(f"Average CLV         : {avg_clv:+.2f}% (Market Edge Benchmark)")
    else:
        print("Average CLV         : Pending settled lines")
    print("-" * 35 + "\n")

if __name__ == "__main__":
    display_trade_ledger()