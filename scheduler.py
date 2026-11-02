"""
scheduler.py
Autonomous process supervisor.
Orchestrates market scans every 3 hours and nightly settlements at 02:00.
"""

import sys
import time
import subprocess
from datetime import datetime
import schedule

# Enforce UTF-8 console output for Windows cmd/powershell
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PYTHON_EXEC = sys.executable  # Points to your active virtual environment/Python

def run_job(script_name: str, task_label: str):
    """
    Spawns the target script in a separate Python process with clean UTF-8 pipes.
    This guarantees any unhandled crash in a scan won't kill the main scheduler loop.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now_str}] >>> INITIATING {task_label.upper()} ({script_name})...")

    try:
        result = subprocess.run(
            [PYTHON_EXEC, script_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        # Stream child process output indented for readability
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                print(f"    {line}")

        if result.stderr:
            for line in result.stderr.strip().splitlines():
                print(f"    [STDERR] {line}")

        status = "successfully" if result.returncode == 0 else f"with exit code {result.returncode}"
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {task_label} completed {status}.")

    except Exception as e:
        print(f"[!] Critical error executing {script_name}: {e}")

def job_market_scan():
    run_job("main.py", "Market scan")

def job_settlement():
    run_job("settle.py", "Settlement engine")

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scheduler service initialized.")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Active schedules:")
    print("  - Market Scanner   : Every 3 hours")
    print("  - Settlement Engine: Nightly at 02:00")

    # 1. Register Schedules
    schedule.every(3).hours.do(job_market_scan)
    schedule.every().day.at("02:00").do(job_settlement)

    # 2. Run initial scan immediately on boot
    job_market_scan()

    # 3. Main supervision loop
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Scheduler stopped by user.")