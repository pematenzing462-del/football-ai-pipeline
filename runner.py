import time
import subprocess
from datetime import datetime

# Interval between scans in seconds (1800s = 30 minutes)
SCAN_INTERVAL_SECONDS = 1800

def run_pipeline():
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] Starting market scan...")
        
        # Executes main.py and streams the terminal output
        try:
            result = subprocess.run(["python", "main.py"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during execution: {e}")
            
        print(f"Scan complete. Sleeping for {SCAN_INTERVAL_SECONDS // 60} minutes until next cycle...")
        time.sleep(SCAN_INTERVAL_SECONDS)

if __name__ == "__main__":
    try:
        run_pipeline()
    except KeyboardInterrupt:
        print("\nRunner stopped by user.")