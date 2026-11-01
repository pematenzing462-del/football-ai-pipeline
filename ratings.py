import os
import io
import requests
import pandas as pd
import numpy as np
from datetime import datetime

LOCAL_CACHE_FILE = "epl_season_data.csv"
DECAY_RATE = 0.0077

# Fast, accessible raw CSV sources
DATA_URLS = [
    "https://raw.githubusercontent.com/footballcsv/england/master/2020s/2023-24/1-premierleague.csv",
    "https://www.football-data.co.uk/mmz4252/2425/E0.csv"
]

_CACHED_DF = None

TEAM_NAME_MAP = {
    "Manchester United": "Man United",
    "Manchester City": "Man City",
    "Tottenham Hotspur": "Tottenham",
    "Nottingham Forest": "Nott'm Forest",
    "Wolverhampton Wanderers": "Wolves",
    "Sheffield United": "Sheffield United",
    "Brighton and Hove Albion": "Brighton",
    "West Ham United": "West Ham",
    "Newcastle United": "Newcastle",
    "Leicester City": "Leicester",
    "Ipswich Town": "Ipswich"
}

def clean_team_name(name):
    """Normalizes team names across data sources."""
    return TEAM_NAME_MAP.get(name, name)

def fetch_raw_csv_text():
    """
    Checks the local cache file first. Only attempts web downloads
    if no local copy exists, using a fast 3-second timeout.
    """
    # 1. Instant local cache lookup
    if os.path.exists(LOCAL_CACHE_FILE):
        try:
            with open(LOCAL_CACHE_FILE, "r", encoding="utf-8") as f:
                content = f.read()
                if len(content.strip()) > 100:
                    return content
        except Exception:
            pass

    # 2. Fast network download attempt
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    })

    for url in DATA_URLS:
        try:
            res = session.get(url, timeout=3)
            if res.status_code == 200 and len(res.text.strip()) > 100:
                with open(LOCAL_CACHE_FILE, "w", encoding="utf-8") as f:
                    f.write(res.text)
                return res.text
        except Exception:
            continue

    return None

def generate_baseline_dataframe():
    """Fallback standard baseline numbers if data cannot be retrieved."""
    teams = [
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton",
        "Chelsea", "Crystal Palace", "Everton", "Fulham", "Ipswich",
        "Leicester", "Liverpool", "Man City", "Man United", "Newcastle",
        "Nott'm Forest", "Southampton", "Tottenham", "West Ham", "Wolves"
    ]
    rows = []
    for h in teams:
        for a in teams:
            if h != a:
                rows.append({
                    "Date": datetime.now(),
                    "HomeTeam": h,
                    "AwayTeam": a,
                    "FTHG": 1.55,
                    "FTAG": 1.25,
                    "DaysAgo": 0,
                    "Weight": 1.0
                })
    return pd.DataFrame(rows)

def load_decay_weighted_data(decay_rate=DECAY_RATE):
    """Parses match data, computes days elapsed, and sets exponential weights."""
    global _CACHED_DF
    if _CACHED_DF is not None:
        return _CACHED_DF

    csv_text = fetch_raw_csv_text()
    if not csv_text:
        _CACHED_DF = generate_baseline_dataframe()
        return _CACHED_DF

    try:
        df = pd.read_csv(io.StringIO(csv_text))
        
        # Standardize football-data format
        if "FTHG" in df.columns and "FTAG" in df.columns:
            df = df[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]].dropna()
        else:
            date_col = next((c for c in df.columns if "date" in c.lower()), "Date")
            home_col = next((c for c in df.columns if "home" in c.lower() or "team 1" in c.lower()), df.columns[1])
            away_col = next((c for c in df.columns if "away" in c.lower() or "team 2" in c.lower()), df.columns[2])
            
            if "FT" in df.columns or "Score" in df.columns:
                score_col = "FT" if "FT" in df.columns else "Score"
                df[["FTHG", "FTAG"]] = df[score_col].astype(str).str.split("-", expand=True)
            
            df = df.rename(columns={date_col: "Date", home_col: "HomeTeam", away_col: "AwayTeam"})
            df = df[["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]].dropna()

        df["FTHG"] = pd.to_numeric(df["FTHG"], errors="coerce")
        df["FTAG"] = pd.to_numeric(df["FTAG"], errors="coerce")
        df = df.dropna(subset=["FTHG", "FTAG"])

        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        df = df.dropna(subset=["Date"])

        today = datetime.now()
        df["DaysAgo"] = (today - df["Date"]).dt.days
        df["DaysAgo"] = df["DaysAgo"].apply(lambda d: max(d, 0))

        df["Weight"] = np.exp(-decay_rate * df["DaysAgo"])
        _CACHED_DF = df
    except Exception:
        _CACHED_DF = generate_baseline_dataframe()

    return _CACHED_DF

def calculate_match_lambdas(home_team, away_team):
    """
    Computes time-decay weighted attack/defense ratings and returns expected 
    goal intensities (lambda_home, lambda_away, total_lambda) for the match.
    """
    df = load_decay_weighted_data()

    h_clean = clean_team_name(home_team)
    a_clean = clean_team_name(away_team)

    total_weight = df["Weight"].sum()
    avg_home_goals = (df["FTHG"] * df["Weight"]).sum() / total_weight
    avg_away_goals = (df["FTAG"] * df["Weight"]).sum() / total_weight

    home_matches = df[df["HomeTeam"] == h_clean]
    away_matches = df[df["AwayTeam"] == a_clean]

    if home_matches.empty or away_matches.empty:
        return round(avg_home_goals, 3), round(avg_away_goals, 3), round(avg_home_goals + avg_away_goals, 3)

    home_weight = home_matches["Weight"].sum()
    away_weight = away_matches["Weight"].sum()

    home_goals_scored_avg = (home_matches["FTHG"] * home_matches["Weight"]).sum() / home_weight
    home_goals_conceded_avg = (home_matches["FTAG"] * home_matches["Weight"]).sum() / home_weight

    away_goals_scored_avg = (away_matches["FTAG"] * away_matches["Weight"]).sum() / away_weight
    away_goals_conceded_avg = (away_matches["FTHG"] * away_matches["Weight"]).sum() / away_weight

    home_attack = home_goals_scored_avg / avg_home_goals
    home_defense = home_goals_conceded_avg / avg_away_goals

    away_attack = away_goals_scored_avg / avg_away_goals
    away_defense = away_goals_conceded_avg / avg_home_goals

    lambda_home = home_attack * away_defense * avg_home_goals
    lambda_away = away_attack * home_defense * avg_away_goals
    total_lambda = lambda_home + lambda_away

    return round(float(lambda_home), 3), round(float(lambda_away), 3), round(float(total_lambda), 3)

if __name__ == "__main__":
    test_h = "Arsenal"
    test_a = "Chelsea"
    lh, la, tot = calculate_match_lambdas(test_h, test_a)
    print("--- TIME-DECAY RATINGS TEST ---")
    print(f"Fixture: {test_h} vs {test_a}")
    print(f"Expected Goals -> {test_h}: {lh:.3f} | {test_a}: {la:.3f} | Total: {tot:.3f}")