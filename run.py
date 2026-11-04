"""
run.py
Master control script for your quantitative football trading pipeline.
Allows you to trigger live scans or settle pending bets from a single menu.
"""

import sys
import os

# Ensure local modules can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import run_quant_scan, init_db
from settle_trades import settle_pending_trades, print_performance_audit


def print_banner():
    print("\n" + "=" * 60)
    print("⚽ QUANTITATIVE FOOTBALL TRADING & ANALYTICS PIPELINE")
    print("=" * 60)


def main_menu():
    init_db()  # Ensure database and migration columns exist
    
    while True:
        print_banner()
        print("  [1] Run Live Quantitative Scan (1X2 + Over/Under 2.5)")
        print("  [2] Settle Pending Trades & Run CLV Performance Audit")
        print("  [3] Exit Pipeline")
        print("=" * 60)
        
        choice = input("Enter your choice (1-3): ").strip()
        
        if choice == "1":
            print("\nSelect Pre-Match Liquid Scan Window:")
            print("  [1] 1 Hour Pre-Kickoff (Hyper-liquid, closing lines)")
            print("  [2] 24 Hours Pre-Kickoff (Standard daily scan - Recommended)")
            print("  [3] 48 Hours Pre-Kickoff (Extended slate)")
            
            sub_choice = input("Enter choice (1-3, default 2): ").strip()
            hours = 1.0 if sub_choice == "1" else (48.0 if sub_choice == "3" else 24.0)
            
            run_quant_scan(max_hours_ahead=hours)
            input("\nPress Enter to return to main menu...")
            
        elif choice == "2":
            print("\n" + "-" * 60)
            print("🔄 SETTLING PENDING TRADES & AUDITING CLV...")
            print("-" * 60)
            settle_pending_trades()
            print_performance_audit()
            input("\nPress Enter to return to main menu...")
            
        elif choice == "3":
            print("\nExiting pipeline. Good luck! 🚀\n")
            sys.exit(0)
        else:
            print("\n[!] Invalid choice. Please enter 1, 2, or 3.")


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n[!] Interrupted by user. Exiting safely.")
        sys.exit(0)