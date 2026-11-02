"""
alerts.py
Telegram notification dispatcher for live trade signals.
Stitches home & away crests side-by-side into a single sleek match banner.
"""

import os
from io import BytesIO
from datetime import datetime
import pytz
import requests
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TEAM_LOGOS = {
    # Premier League
    "Arsenal": "https://a.espncdn.com/i/teamlogos/soccer/500/359.png",
    "Aston Villa": "https://a.espncdn.com/i/teamlogos/soccer/500/362.png",
    "Bournemouth": "https://a.espncdn.com/i/teamlogos/soccer/500/349.png",
    "Brentford": "https://a.espncdn.com/i/teamlogos/soccer/500/337.png",
    "Brighton and Hove Albion": "https://a.espncdn.com/i/teamlogos/soccer/500/331.png",
    "Chelsea": "https://a.espncdn.com/i/teamlogos/soccer/500/363.png",
    "Crystal Palace": "https://a.espncdn.com/i/teamlogos/soccer/500/384.png",
    "Everton": "https://a.espncdn.com/i/teamlogos/soccer/500/368.png",
    "Fulham": "https://a.espncdn.com/i/teamlogos/soccer/500/370.png",
    "Ipswich Town": "https://a.espncdn.com/i/teamlogos/soccer/500/373.png",
    "Leicester City": "https://a.espncdn.com/i/teamlogos/soccer/500/375.png",
    "Liverpool": "https://a.espncdn.com/i/teamlogos/soccer/500/364.png",
    "Manchester City": "https://a.espncdn.com/i/teamlogos/soccer/500/382.png",
    "Manchester United": "https://a.espncdn.com/i/teamlogos/soccer/500/360.png",
    "Newcastle United": "https://a.espncdn.com/i/teamlogos/soccer/500/361.png",
    "Nottingham Forest": "https://a.espncdn.com/i/teamlogos/soccer/500/393.png",
    "Southampton": "https://a.espncdn.com/i/teamlogos/soccer/500/376.png",
    "Tottenham Hotspur": "https://a.espncdn.com/i/teamlogos/soccer/500/367.png",
    "West Ham United": "https://a.espncdn.com/i/teamlogos/soccer/500/371.png",
    "Wolverhampton Wanderers": "https://a.espncdn.com/i/teamlogos/soccer/500/380.png",

    # La Liga
    "Athletic Bilbao": "https://a.espncdn.com/i/teamlogos/soccer/500/93.png",
    "Atletico Madrid": "https://a.espncdn.com/i/teamlogos/soccer/500/1068.png",
    "Barcelona": "https://a.espncdn.com/i/teamlogos/soccer/500/83.png",
    "Celta Vigo": "https://a.espncdn.com/i/teamlogos/soccer/500/85.png",
    "Espanyol": "https://a.espncdn.com/i/teamlogos/soccer/500/88.png",
    "Getafe": "https://a.espncdn.com/i/teamlogos/soccer/500/2922.png",
    "Girona": "https://a.espncdn.com/i/teamlogos/soccer/500/9812.png",
    "Mallorca": "https://a.espncdn.com/i/teamlogos/soccer/500/84.png",
    "Osasuna": "https://a.espncdn.com/i/teamlogos/soccer/500/97.png",
    "Rayo Vallecano": "https://a.espncdn.com/i/teamlogos/soccer/500/101.png",
    "Real Betis": "https://a.espncdn.com/i/teamlogos/soccer/500/244.png",
    "Real Madrid": "https://a.espncdn.com/i/teamlogos/soccer/500/86.png",
    "Real Sociedad": "https://a.espncdn.com/i/teamlogos/soccer/500/89.png",
    "Sevilla": "https://a.espncdn.com/i/teamlogos/soccer/500/243.png",
    "Valencia": "https://a.espncdn.com/i/teamlogos/soccer/500/94.png",
    "Villarreal": "https://a.espncdn.com/i/teamlogos/soccer/500/102.png"
}

def find_logo(team_name: str) -> str:
    if not team_name:
        return ""
    if team_name in TEAM_LOGOS:
        return TEAM_LOGOS[team_name]
    for key, url in TEAM_LOGOS.items():
        if key.lower() in team_name.lower() or team_name.lower() in key.lower():
            return url
    return ""

def generate_matchup_banner(home_team: str, away_team: str) -> BytesIO:
    """
    Downloads both crests, resizes them cleanly, and merges them onto
    a single transparent canvas with natural spacing. Returns a PNG byte buffer.
    """
    url_home = find_logo(home_team)
    url_away = find_logo(away_team)

    if not url_home or not url_away:
        return None

    try:
        res_h = requests.get(url_home, timeout=4)
        res_a = requests.get(url_away, timeout=4)
        if res_h.status_code != 200 or res_a.status_code != 200:
            return None

        img_h = Image.open(BytesIO(res_h.content)).convert("RGBA")
        img_a = Image.open(BytesIO(res_a.content)).convert("RGBA")

        # Resize both logos to a uniform compact size (150x150)
        target_size = (150, 150)
        img_h = img_h.resize(target_size, Image.Resampling.LANCZOS)
        img_a = img_a.resize(target_size, Image.Resampling.LANCZOS)

        # Build a single wide canvas: 460px width x 160px height
        canvas = Image.new("RGBA", (460, 160), (0, 0, 0, 0))

        # Paste Home on left (x=30), Away on right (x=280)
        canvas.paste(img_h, (30, 5), img_h)
        canvas.paste(img_a, (280, 5), img_a)

        buf = BytesIO()
        canvas.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        return None

def format_kickoff_ist(iso_time_str: str) -> str:
    if not iso_time_str:
        return "Upcoming"
    try:
        clean_str = iso_time_str.replace("Z", "+00:00")
        utc_dt = datetime.fromisoformat(clean_str)
        ist_tz = pytz.timezone("Asia/Kolkata")
        ist_dt = utc_dt.astimezone(ist_tz)
        return ist_dt.strftime("%d %b %Y, %I:%M %p IST")
    except Exception:
        return iso_time_str[:16].replace("T", " ")

def send_telegram_trade_alert(
    home_team: str,
    away_team: str,
    selection: str,
    market_odds: float,
    fair_odds: float,
    edge_pct: float,
    stake: float,
    cutoff_odds: float,
    source: str,
    commence_time: str = None,
    pinny_fair: float = None,
    steam_reason: str = ""
):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    if selection == "Home":
        target = f"{home_team} [BACK - Blue]"
    elif selection == "Away":
        target = f"{away_team} [BACK - Blue]"
    else:
        target = "Draw / X [BACK - Blue]"

    match_time = format_kickoff_ist(commence_time)
    sharp_line = f"• *Pinnacle Fair:* `{pinny_fair:.2f}`\n" if pinny_fair else ""
    steam_flag = f"⚡ *STEAM ALERT:* _{steam_reason}_\n\n" if steam_reason else ""

    caption = (
        f"{steam_flag}⚽ *SIGNAL: {home_team} vs {away_team}*\n"
        f"📅 *Kickoff:* `{match_time}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Pick:* *{target}*\n"
        f"🏢 *Source:* {source}\n\n"
        f"📊 *Odds Matrix:*\n"
        f"• *Current Odds:* `{market_odds:.2f}`\n"
        f"• *Model Fair:* `{fair_odds:.2f}`\n"
        f"{sharp_line}"
        f"• *Edge:* `+{edge_pct:.2f}%`\n"
        f"• *Min Floor:* `>= {cutoff_odds:.2f}`\n\n"
        f"💰 *Stake:* *₹{stake:,.2f}*\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    # 1. Attempt to generate single combined matchup banner
    banner_buffer = generate_matchup_banner(home_team, away_team)
    if banner_buffer:
        photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        files = {"photo": ("banner.png", banner_buffer, "image/png")}
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "Markdown"
        }
        try:
            res = requests.post(photo_url, data=data, files=files, timeout=8)
            if res.status_code == 200:
                return True
        except requests.RequestException:
            pass

    # 2. Plain text fallback if images fail to download
    text_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": caption,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        res = requests.post(text_url, json=payload, timeout=6)
        return res.status_code == 200
    except requests.RequestException:
        return False

if __name__ == "__main__":
    success = send_telegram_trade_alert(
        home_team="Liverpool",
        away_team="Manchester United",
        selection="Away",
        market_odds=4.33,
        fair_odds=3.15,
        edge_pct=35.45,
        stake=678.90,
        cutoff_odds=3.21,
        source="1xBet",
        commence_time="2026-11-08T16:30:00Z",
        pinny_fair=4.10,
        steam_reason="Pinnacle sharp dropped from 4.60 -> 4.20"
    )
    if success:
        print("[+] Unified side-by-side banner sent to Telegram!")
    else:
        print("[!] Delivery failed.")