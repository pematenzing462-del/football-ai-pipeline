"""
alerts.py
Formats quantitative trade signals (1X2 + Over/Under 2.5 Goals) and 
dispatches them to Telegram via sendPhoto (with dynamic club crests) or sendMessage fallback.
"""

import os
import html
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

# Manual overrides for major European clubs with unique naming conventions
TEAM_LOGOS = {
    # Premier League
    "Arsenal": "https://upload.wikimedia.org/wikipedia/en/5/53/Arsenal_FC.svg.png",
    "Aston Villa": "https://upload.wikimedia.org/wikipedia/en/f/f9/Aston_Villa_FC_crest_%282016%29.svg.png",
    "Chelsea": "https://upload.wikimedia.org/wikipedia/en/c/cc/Chelsea_FC.svg.png",
    "Liverpool": "https://upload.wikimedia.org/wikipedia/en/0/0c/Liverpool_FC.svg.png",
    "Manchester City": "https://upload.wikimedia.org/wikipedia/en/e/eb/Manchester_City_FC_badge.svg.png",
    "Manchester United": "https://upload.wikimedia.org/wikipedia/en/7/7a/Manchester_United_FC_crest.svg.png",
    "Newcastle United": "https://upload.wikimedia.org/wikipedia/en/5/56/Newcastle_United_Logo.svg.png",
    "Tottenham Hotspur": "https://upload.wikimedia.org/wikipedia/en/b/b4/Tottenham_Hotspur.svg.png",
    "West Ham United": "https://upload.wikimedia.org/wikipedia/en/c/c2/West_Ham_United_FC_logo.svg.png",
    
    # La Liga
    "Real Madrid": "https://upload.wikimedia.org/wikipedia/en/5/56/Real_Madrid_CF.svg.png",
    "Barcelona": "https://upload.wikimedia.org/wikipedia/en/4/47/FC_Barcelona_%28crest%29.svg.png",
    "Atletico Madrid": "https://upload.wikimedia.org/wikipedia/en/f/f4/Atletico_Madrid_2024_logo.svg.png",
    "Villarreal": "https://upload.wikimedia.org/wikipedia/en/7/70/Villarreal_CF_logo.svg.png",
    "Real Sociedad": "https://upload.wikimedia.org/wikipedia/en/f/f1/Real_Sociedad_logo.svg.png",
    
    # Serie A
    "Inter": "https://upload.wikimedia.org/wikipedia/en/0/05/FC_Internazionale_Milano_2021.svg.png",
    "AC Milan": "https://upload.wikimedia.org/wikipedia/en/d/d0/AC_Milan_Logo_2019.svg.png",
    "Juventus": "https://upload.wikimedia.org/wikipedia/en/b/bc/Juventus_FC_2017_icon_%28black%29.svg.png",
    "Napoli": "https://upload.wikimedia.org/wikipedia/en/2/28/SSC_Napoli_Logo.svg.png",
    "Roma": "https://upload.wikimedia.org/wikipedia/en/f/f7/AS_Roma_Logo_2017.svg.png",
    
    # Bundesliga
    "Bayern Munich": "https://upload.wikimedia.org/wikipedia/commons/1/1b/FC_Bayern_M%C3%BCnchen_logo_%282002%E2%80%932024%29.svg.png",
    "Borussia Dortmund": "https://upload.wikimedia.org/wikipedia/commons/6/67/Borussia_Dortmund_logo.svg.png",
    "Bayer Leverkusen": "https://upload.wikimedia.org/wikipedia/en/5/59/Bayer_04_Leverkusen_logo.svg.png",
    "RB Leipzig": "https://upload.wikimedia.org/wikipedia/en/0/04/RB_Leipzig_2014_logo.svg.png",

    # Eredivisie & Ligue 1
    "Ajax": "https://upload.wikimedia.org/wikipedia/en/7/79/AFC_Ajax_%28logo%29.svg.png",
    "PSV Eindhoven": "https://upload.wikimedia.org/wikipedia/en/0/05/PSV_Eindhoven.svg.png",
    "Feyenoord": "https://upload.wikimedia.org/wikipedia/en/e/e3/Feyenoord_logo.svg.png",
    "Paris Saint-Germain": "https://upload.wikimedia.org/wikipedia/en/a/a7/Paris_Saint-Germain_F.C..svg.png"
}

# Generic fallback images
FALLBACK_LOGO_URL = "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=600&auto=format&fit=crop&q=60"
TOTALS_LOGO_URL = "https://images.unsplash.com/photo-1518091043644-c1d4457512c6?w=600&auto=format&fit=crop&q=60"


def get_team_logo(home_team: str, selection: str) -> str:
    """Dynamically generates or matches a club logo URL for any team worldwide across all leagues."""
    sel_clean = selection.strip()
    sel_lower = sel_clean.lower()

    # 1. Check manual overrides first
    if sel_clean in TEAM_LOGOS:
        return TEAM_LOGOS[sel_clean]
    if home_team in TEAM_LOGOS:
        return TEAM_LOGOS[home_team]

    # 2. If it's a Totals market pick, use a clean football-goals visual asset
    if "over" in sel_lower or "under" in sel_lower:
        return TOTALS_LOGO_URL

    # 3. Dynamic Fallback: Clean team name into a standard slug for global open-source badge repositories
    target_team = sel_clean if sel_clean not in ["Draw", "Over 2.5", "Under 2.5"] else home_team
    slug = (
        target_team.lower()
        .strip()
        .replace(" ", "-")
        .replace("é", "e")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
    )
    
    return f"https://raw.githubusercontent.com/openfootball/logos/master/{slug}.png"


def format_trade_message(
    home_team: str,
    away_team: str,
    selection: str,
    market_odds: float,
    fair_odds: float,
    edge_pct: float,
    stake: float,
    cutoff_odds: float = None,
    source: str = "Soft Book",
    commence_time: str = "TBD",
    pinny_fair: float = None,
    steam_reason: str = ""
) -> str:
    """Builds an HTML-safe Telegram caption tailored for 1X2 or Over/Under 2.5 markets."""
    sel_clean = selection.strip()
    sel_lower = sel_clean.lower()
    is_totals = sel_lower in ("over 2.5", "under 2.5")

    if is_totals:
        market_badge = "⚽ TOTAL GOALS (O/U 2.5)"
        pick_display = f"{sel_clean.upper()} GOALS"
    elif sel_lower == "draw":
        market_badge = "⚔️ 1X2 MATCH WINNER"
        pick_display = "DRAW (1X2)"
    else:
        market_badge = "⚔️ 1X2 MATCH WINNER"
        pick_display = f"{sel_clean} (1X2)"

    safe_home = html.escape(str(home_team))
    safe_away = html.escape(str(away_team))
    safe_pick = html.escape(pick_display)
    safe_source = html.escape(str(source))
    safe_time = html.escape(str(commence_time))

    min_playable = cutoff_odds if cutoff_odds is not None else round(fair_odds * 1.025, 2)
    pin_display = f"{pinny_fair:.2f}" if pinny_fair is not None else "N/A"

    lines = [
        f"🚨 <b>QUANT VALUE SIGNAL</b> | <b>{market_badge}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🏟 <b>Fixture:</b> {safe_home} vs {safe_away}",
        f"⏰ <b>Kickoff:</b> {safe_time}",
        "",
        f"🎯 <b>Selection:</b> <code>{safe_pick}</code>",
        f"🏦 <b>Bookmaker:</b> <b>{safe_source} @ {market_odds:.2f}</b>",
        "",
        "📊 <b>PRICING BREAKDOWN</b>",
        f"  • <b>Market Odds:</b> <code>{market_odds:.2f}</code>",
        f"  • <b>Shin Model Fair:</b> <code>{fair_odds:.2f}</code>",
        f"  • <b>Pinnacle Raw Line:</b> <code>{pin_display}</code>",
        f"  • <b>Min Cutoff Odds:</b> <code>{min_playable:.2f}</code>",
        f"  • <b>True Edge (EV):</b> <code>{edge_pct:+.2f}%</code>",
        "",
        f"💰 <b>Rec. Stake (0.25x Kelly):</b> <code>₹{stake:,.2f}</code>"
    ]

    if steam_reason:
        safe_steam = html.escape(str(steam_reason))
        lines.append(f"🔥 <b>Steam Check:</b> <i>{safe_steam}</i>")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def send_telegram_trade_alert(
    home_team: str,
    away_team: str,
    selection: str,
    market_odds: float,
    fair_odds: float,
    edge_pct: float,
    stake: float,
    cutoff_odds: float = None,
    source: str = "Soft Book",
    commence_time: str = "TBD",
    pinny_fair: float = None,
    steam_reason: str = ""
) -> bool:
    """Sends the trade alert as a Photo with the pricing breakdown as the caption."""
    msg_html = format_trade_message(
        home_team=home_team,
        away_team=away_team,
        selection=selection,
        market_odds=market_odds,
        fair_odds=fair_odds,
        edge_pct=edge_pct,
        stake=stake,
        cutoff_odds=cutoff_odds,
        source=source,
        commence_time=commence_time,
        pinny_fair=pinny_fair,
        steam_reason=steam_reason
    )

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram credentials missing in .env. Printing alert locally:")
        print(msg_html)
        return False

    logo_url = get_team_logo(home_team, selection)
    
    # Attempt photo dispatch first
    photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    photo_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": logo_url,
        "caption": msg_html,
        "parse_mode": "HTML"
    }

    try:
        res = requests.post(photo_url, json=photo_payload, timeout=10)
        if res.status_code == 200:
            return True
            
        # Fallback to standard text message if dynamic badge URL fails
        text_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        text_payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        res_text = requests.post(text_url, json=text_payload, timeout=10)
        if res_text.status_code == 200:
            return True
            
        print(f"  [!] Telegram API Error (HTTP {res_text.status_code}): {res_text.text[:150]}")
        return False
        
    except requests.RequestException as e:
        print(f"  [!] Failed to send Telegram alert: {e}")
        return False


if __name__ == "__main__":
    # Local preview test
    sample = format_trade_message(
        home_team="Leeds United",
        away_team="Sunderland",
        selection="Over 2.5",
        market_odds=2.05,
        fair_odds=1.92,
        edge_pct=6.77,
        stake=400.00,
        cutoff_odds=1.98,
        source="Unibet",
        commence_time="08 Nov 15:00 UTC",
        pinny_fair=1.88,
        steam_reason="Sharp money backing pick (Line tightening: 1.94 to 1.88)"
    )
    print(sample)