"""
bot_menu.py
Interactive Telegram bot menu for quantitative football scanner and live in-play trading.
Supports Top 5 European leagues, dynamic time decay calculations, and green-up hedging.
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv

# Import local engines
from live_decay import calculate_live_odds, calculate_green_up_hedge
from main import run_quant_scan

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTH_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not AUTH_CHAT_ID:
    print("[!] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env file.")
    sys.exit(1)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Mapping internal league selections to The Odds API keys
LEAGUE_MAP = {
    "epl": ["soccer_epl"],
    "laliga": ["soccer_spain_la_liga"],
    "serie_a": ["soccer_italy_serie_a"],
    "bundesliga": ["soccer_germany_bundesliga"],
    "ligue_1": ["soccer_france_ligue_one"],
    "uefa": [
        "soccer_uefa_champs_league",
        "soccer_uefa_europa_league",
        "soccer_uefa_europa_conference_league"
    ],
    "top5": [
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_italy_serie_a",
        "soccer_germany_bundesliga",
        "soccer_france_ligue_one"
    ],
    "all": [
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_italy_serie_a",
        "soccer_germany_bundesliga",
        "soccer_france_ligue_one",
        "soccer_uefa_champs_league",
        "soccer_uefa_europa_league",
        "soccer_uefa_europa_conference_league"
    ]
}

# In-memory user configuration
user_state = {
    "league": "top5",
    "window_hours": 48
}

# Concurrency lock to prevent overlapping API scans
is_scanning = False


def send_telegram_message(chat_id: str, text: str, reply_markup: dict = None) -> dict:
    """Dispatches a Markdown-formatted Telegram message."""
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json()
    except requests.RequestException as e:
        print(f"[!] Error sending message: {e}")
        return {}


def edit_telegram_message(chat_id: str, message_id: int, text: str, reply_markup: dict = None) -> dict:
    """Edits an existing Telegram message in place."""
    url = f"{BASE_URL}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.json()
    except requests.RequestException as e:
        print(f"[!] Error editing message: {e}")
        return {}


def answer_callback_query(callback_query_id: str, text: str = None) -> None:
    """Acknowledges an inline button click to dismiss the loading spinner."""
    url = f"{BASE_URL}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(url, json=payload, timeout=5)
    except requests.RequestException:
        pass


def build_menu_markup():
    """Builds the inline interactive keyboard with current selections."""
    league_display_names = {
        "epl": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL",
        "laliga": "🇪🇸 La Liga",
        "serie_a": "🇮🇹 Serie A",
        "bundesliga": "🇩🇪 Bundesliga",
        "ligue_1": "🇫🇷 Ligue 1",
        "top5": "🌐 Top 5 All"
    }

    current_league_name = league_display_names.get(user_state["league"], "Custom")
    window_label = f"Next {user_state['window_hours']}h" if user_state['window_hours'] < 168 else "Next 7 Days"

    text = (
        "⚙️ *QUANT SCANNER TERMINAL*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *Target Leagues:* `{current_league_name}`\n"
        f"⏳ *Kickoff Horizon:* `{window_label}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Select your filter parameters and trigger the scanner below:"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": ("✅ " if user_state["league"] == "epl" else "") + "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL", "callback_data": "set_epl"},
                {"text": ("✅ " if user_state["league"] == "laliga" else "") + "🇪🇸 La Liga", "callback_data": "set_laliga"},
                {"text": ("✅ " if user_state["league"] == "serie_a" else "") + "🇮🇹 Serie A", "callback_data": "set_serie_a"}
            ],
            [
                {"text": ("✅ " if user_state["league"] == "bundesliga" else "") + "🇩🇪 Bundesliga", "callback_data": "set_bundesliga"},
                {"text": ("✅ " if user_state["league"] == "ligue_1" else "") + "🇫🇷 Ligue 1", "callback_data": "set_ligue_1"},
                {"text": ("✅ " if user_state["league"] == "top5" else "") + "🌐 Top 5 All", "callback_data": "set_top5"}
            ],
            [
                {"text": ("✅ " if user_state["window_hours"] == 24 else "") + "24h", "callback_data": "time_24"},
                {"text": ("✅ " if user_state["window_hours"] == 48 else "") + "48h", "callback_data": "time_48"},
                {"text": ("✅ " if user_state["window_hours"] == 168 else "") + "7 Days", "callback_data": "time_168"}
            ],
            [
                {"text": "🚀 RUN SCAN NOW", "callback_data": "trigger_scan"}
            ]
        ]
    }
    return text, keyboard


def handle_live_command(chat_id: str, text: str):
    """
    Supports standard and stoppage time syntax:
      • /live 72 1-0 Arsenal vs Chelsea
      • /live 90+3 1-1 Real Madrid vs Barcelona (+6)
      • /live 88 0-0 1.95 1.10 (+5)
    """
    args = text.strip().split()[1:]

    if len(args) < 3:
        usage = (
            "⚠️ *Invalid /live syntax*\n\n"
            "Format:\n"
            "• `/live <min> <score> <TeamA> vs <TeamB> [(+added)]`\n"
            "  _Example:_ `/live 75 1-0 Arsenal vs Chelsea`\n"
            "  _Example:_ `/live 90+2 1-1 Arsenal vs Chelsea +6`\n\n"
            "• `/live <min> <score> <lam_h> <lam_a> [+added]`\n"
            "  _Example:_ `/live 88 0-0 1.85 1.15 +5`"
        )
        send_telegram_message(chat_id, usage)
        return

    # Parse clock and stoppage
    clock_raw = args[0]
    stoppage_announced = 0
    stoppage_elapsed = 0

    if "+" in clock_raw:
        parts = clock_raw.split("+")
        minute = 90
        try:
            stoppage_elapsed = int(parts[1])
        except ValueError:
            stoppage_elapsed = 0
    else:
        try:
            minute = int(clock_raw)
        except ValueError:
            send_telegram_message(chat_id, "❌ Minute must be numeric (e.g. `78` or `90+3`).")
            return

    # Check for trailing explicit stoppage announcement like '+6' or '(+6)'
    last_arg = args[-1].replace("(", "").replace(")", "")
    if last_arg.startswith("+") and last_arg[1:].isdigit():
        stoppage_announced = int(last_arg[1:])
        args = args[:-1]  # Remove from team/lambda arguments
    elif minute >= 85 and stoppage_announced == 0:
        stoppage_announced = 5  # Default empirical added time assumption

    # Parse Score
    try:
        h_score, a_score = [int(s) for s in args[1].split("-")]
    except (ValueError, IndexError):
        send_telegram_message(chat_id, "❌ Score must be formatted like `1-0` or `2-2`.")
        return

    # Parse Teams or Raw Lambdas
    if len(args) == 4 and args[2].replace(".", "", 1).isdigit() and args[3].replace(".", "", 1).isdigit():
        lam_h = float(args[2])
        lam_a = float(args[3])
        team_h, team_a = "Home", "Away"
    else:
        match_str = " ".join(args[2:])
        if " vs " in match_str:
            team_h, team_a = [t.strip() for t in match_str.split(" vs ", 1)]
        elif " v " in match_str:
            team_h, team_a = [t.strip() for t in match_str.split(" v ", 1)]
        else:
            send_telegram_message(chat_id, "❌ Separate teams using `vs` (e.g. `Arsenal vs Chelsea`).")
            return
        lam_h, lam_a = 1.45, 1.15  # Fallback league baselines

    result = calculate_live_odds(
        pre_match_lam_h=lam_h,
        pre_match_lam_a=lam_a,
        minute=minute,
        home_score=h_score,
        away_score=a_score,
        stoppage_announced=stoppage_announced,
        stoppage_elapsed=stoppage_elapsed
    )

    p = result["probs"]
    odds = result["fair_odds"]

    card = (
        f"⏱️ *IN-PLAY VALUE: {result['clock']}*\n"
        f"⚽ *{team_h}* `{h_score} - {a_score}` *{team_a}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Remaining Expectancy (λ):*\n"
        f"• {team_h}: `{result['lam_h_remaining']}` goals\n"
        f"• {team_a}: `{result['lam_a_remaining']}` goals\n\n"
        f"🎯 *Decayed Fair Odds:*\n"
        f"• 1 ({team_h}): *{odds['home']}* ({int(p['home'] * 100)}%)\n"
        f"• X (Draw): *{odds['draw']}* ({int(p['draw'] * 100)}%)\n"
        f"• 2 ({team_a}): *{odds['away']}* ({int(p['away'] * 100)}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚖️ _Calculated with 2H non-linear weighting & added time._"
    )
    send_telegram_message(chat_id, card)

def handle_cashout_command(chat_id: str, text: str):
    """
    Calculates green-up lay stakes to lock equal profit across all outcomes.
    Syntax: /cashout <back_stake> <back_odds> <current_lay_odds>
    Example: /cashout 1000 2.10 1.30
    """
    args = text.strip().split()[1:]
    if len(args) != 3:
        send_telegram_message(
            chat_id,
            "⚠️ *Usage:* `/cashout <back_stake> <back_odds> <current_lay_odds>`\n"
            "_Example:_ `/cashout 1000 2.10 1.30`"
        )
        return

    try:
        b_stake = float(args[0])
        b_odds = float(args[1])
        l_odds = float(args[2])
    except ValueError:
        send_telegram_message(chat_id, "❌ *Error:* Stakes and odds must be numeric values.")
        return

    hedge = calculate_green_up_hedge(back_stake=b_stake, back_odds=b_odds, current_lay_odds=l_odds)

    card = (
        f"🟢 *GREEN-UP HEDGE CALCULATOR*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 *Original Back:* ₹{b_stake:.2f} @ `{b_odds:.2f}`\n"
        f"🔄 *Current Lay Price:* `{l_odds:.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Lay Stake to Place:* *₹{hedge['lay_stake']}*\n"
        f"💰 *Locked Profit (Any Result):* *₹{hedge['locked_profit']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚖️ _Calculated after 2% exchange commission._"
    )
    send_telegram_message(chat_id, card)


def handle_callback(callback_query: dict):
    """Processes interactive inline menu clicks."""
    global is_scanning
    query_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = str(message.get("chat", {}).get("id"))
    message_id = message.get("message_id")

    if chat_id != str(AUTH_CHAT_ID):
        answer_callback_query(query_id, "Unauthorized.")
        return

    # League selections
    if data in ["set_epl", "set_laliga", "set_serie_a", "set_bundesliga", "set_ligue_1", "set_top5"]:
        user_state["league"] = data.replace("set_", "")
        text, markup = build_menu_markup()
        edit_telegram_message(chat_id, message_id, text, markup)
        answer_callback_query(query_id, "League filter updated.")

    # Time horizon selections
    elif data in ["time_24", "time_48", "time_168"]:
        user_state["window_hours"] = int(data.replace("time_", ""))
        text, markup = build_menu_markup()
        edit_telegram_message(chat_id, message_id, text, markup)
        answer_callback_query(query_id, "Time window updated.")

    # Scanner trigger
    elif data == "trigger_scan":
        if is_scanning:
            answer_callback_query(query_id, "A scan is already running. Please wait.")
            return

        answer_callback_query(query_id, "Starting scan...")
        is_scanning = True

        status_msg = send_telegram_message(chat_id, "⏳ *Scanning European markets and checking sharp lines...*")
        status_id = status_msg.get("result", {}).get("message_id")

        target_leagues = LEAGUE_MAP.get(user_state["league"], LEAGUE_MAP["top5"])
        found_signals = 0

        try:
            found_signals = run_quant_scan(
                leagues=target_leagues,
                max_hours_ahead=user_state["window_hours"]
            )
        except Exception as e:
            print(f"[!] Scan execution error: {e}")
            send_telegram_message(chat_id, f"❌ *Scan Failed:* `{e}`")
        finally:
            is_scanning = False

        summary_text = (
            f"✅ *SCAN COMPLETE*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Found *{found_signals}* mathematical value signals.\n"
            f"All alerts have been dispatched above."
        )

        if status_id:
            edit_telegram_message(chat_id, status_id, summary_text)
        else:
            send_telegram_message(chat_id, summary_text)


def start_menu_bot():
    """Starts the long-polling loop."""
    print("=" * 50)
    print("🤖 Telegram Quant Scanner & In-Play Bot is ACTIVE")
    print(f"📡 Authorized Chat ID: {AUTH_CHAT_ID}")
    print("=" * 50)

    # Initial menu dispatch
    text, markup = build_menu_markup()
    send_telegram_message(AUTH_CHAT_ID, text, markup)

    offset = 0
    while True:
        try:
            url = f"{BASE_URL}/getUpdates?offset={offset}&timeout=20"
            res = requests.get(url, timeout=25).json()

            if not res.get("ok"):
                time.sleep(2)
                continue

            for update in res.get("result", []):
                offset = update["update_id"] + 1

                # Handle inline keyboard clicks
                if "callback_query" in update:
                    handle_callback(update["callback_query"])

                # Handle text messages
                elif "message" in update and "text" in update["message"]:
                    msg = update["message"]
                    chat_id = str(msg["chat"]["id"])
                    text_in = msg["text"].strip()

                    if chat_id != str(AUTH_CHAT_ID):
                        continue

                    if text_in == "/menu" or text_in == "/start":
                        t, m = build_menu_markup()
                        send_telegram_message(chat_id, t, m)
                    elif text_in.startswith("/live"):
                        handle_live_command(chat_id, text_in)
                    elif text_in.startswith("/cashout"):
                        handle_cashout_command(chat_id, text_in)

        except requests.exceptions.ReadTimeout:
            continue
        except requests.exceptions.ConnectionError:
            print("[!] Network drop. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"[!] Unexpected error in main polling loop: {e}")
            time.sleep(2)


if __name__ == "__main__":
    start_menu_bot()