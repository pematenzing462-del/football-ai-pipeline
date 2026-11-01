import sqlite3
import pandas as pd

# Set display options so columns do not get truncated in terminal
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
            fair_odds,
            edge_percent,
            stake_inr
        FROM signals
        ORDER BY id DESC
    """
    
    try:
        df = pd.read_sql_query(query, conn)
        conn.close()

        if df.empty:
            print("\nDatabase is currently empty. Run 'python main.py' to detect and log trades first.")
            return

        print("\n" + "=" * 80)
        print(" RECORDED +EV SIGNALS (TRADES.DB) ")
        print("=" * 80)
        print(df.to_string(index=False))
        print("=" * 80)
        print(f"Total signals logged: {len(df)}\n")

    except sqlite3.OperationalError:
        print("\n'signals' table not found. Run 'python main.py' first to initialize the database.")
        conn.close()

if __name__ == "__main__":
    display_logged_trades()