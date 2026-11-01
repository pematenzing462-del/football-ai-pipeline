import time
import subprocess
from datetime import datetime
from settle import settle_trades

# Scan every 30 minutes (1800 seconds)
SCAN_INTERVAL_SECONDS = 1800

def run_pipeline():
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("\n" + "=" * 60)
        print(f"[{now}] STARTING SCAN & SETTLEMENT CYCLE")
        print("=" * 60)
        
        # 1. Run live market odds scan
        print("\n--- PHASE 1: MARKET ODDS SCAN (main.py) ---")
        try:
            subprocess.run(["python", "main.py"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during odds scan: {e}")
            
        # 2. Settle completed matches and update P&L
        print("\n--- PHASE 2: AUTOMATED SETTLEMENT (settle.py) ---")
        try:
            settle_trades()
        except Exception as e:
            print(f"Error during settlement pass: {e}")
            
        # 3. Enter cooldown interval
        minutes = SCAN_INTERVAL_SECONDS // 60
        print(f"\nCycle complete. Sleeping for {minutes} minutes until next pass...")
        time.sleep(SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        run_pipeline()
    except KeyboardInterrupt:
        print("\nRunner terminated by user.")