"""
ratings.py
Rolling xG ratings engine with exponential time decay.
Provides calculate_match_lambdas and calculate_team_ratings for the quant pipeline.
"""

import os
import io
import time
import requests
import pandas as pd
import numpy as np

# League mapping for football-data and open xG mirrors
LEAGUE_CONFIG = {
    "soccer_epl": {
        "code": "E0",
        "cache": "epl_season_data.csv",
        "xg_url": "https://raw.githubusercontent.com/footballcsv/england/master/2025-26/premier-league.csv"
    },
    "soccer_spain_la_liga": {
        "code": "SP1",
        "cache": "laliga_season_data.csv",
        "xg_url": "https://raw.githubusercontent.com/footballcsv/spain/master/2025-26/laliga.csv"
    }
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def load_league_data(sport_key="soccer_epl", max_cache_age_hours=12):
    """
    Fetches match logs with shot-based xG metrics.
    Caches data locally on disk to avoid repeated network calls.
    """
    cfg = LEAGUE_CONFIG.get(sport_key, LEAGUE_CONFIG["soccer_epl"])
    cache_file = cfg["cache"]
    league_code = cfg["code"]

    # Check local cache first
    if os.path.exists(cache_file):
        file_age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600.0
        if file_age_hours < max_cache_age_hours:
            try:
                df = pd.read_csv(cache_file)
                if not df.empty and "HomeTeam" in df.columns:
                    return df
            except Exception:
                pass

    session = requests.Session()
    session.headers.update(HEADERS)

    # 1. Primary standard data source
    url = f"https://www.football-data.co.uk/mmz4281/2526/{league_code}.csv"
    content = None
    try:
        res = session.get(url, timeout=10)
        if res.status_code == 200 and len(res.content) > 1000:
            content = res.content
    except Exception:
        pass

    # 2. Fallback mirror
    if content is None:
        try:
            res = session.get(cfg["xg_url"], timeout=10)
            if res.status_code == 200:
                content = res.content
        except Exception:
            pass

    if content is None and os.path.exists(cache_file):
        return pd.read_csv(cache_file)

    if content is not None:
        raw_df = pd.read_csv(io.StringIO(content.decode("utf-8", errors="ignore")))
        # De-fragment frame immediately
        df = raw_df.copy()

        # Fix fragmentation warning: compute and assign columns together
        if "HST" in df.columns and "AST" in df.columns and "HS" in df.columns and "AS" in df.columns:
            home_xg = (df["HST"] * 0.32) + ((df["HS"] - df["HST"]).clip(lower=0) * 0.055)
            away_xg = (df["AST"] * 0.32) + ((df["AS"] - df["AST"]).clip(lower=0) * 0.055)
        else:
            home_xg = df.get("FTHG", pd.Series(np.nan, index=df.index)).astype(float)
            away_xg = df.get("FTAG", pd.Series(np.nan, index=df.index)).astype(float)

        df = df.assign(Home_xG=home_xg, Away_xG=away_xg)
        df.to_csv(cache_file, index=False)
        return df

    return pd.DataFrame()

def calculate_match_lambdas(home_team, away_team, sport_key="soccer_epl", rolling_window=10, xi=0.0077):
    """
    Calculates expected goals (lambdas) using Rolling xG and Exponential Time-Decay.
    """
    df = load_league_data(sport_key)
    if df.empty or "Home_xG" not in df.columns or "Away_xG" not in df.columns:
        return 1.35, 1.15, 2.50

    df = df.dropna(subset=["Home_xG", "Away_xG", "HomeTeam", "AwayTeam"]).copy()

    try:
        df["MatchDate"] = pd.to_datetime(df["Date"], dayfirst=True)
        max_date = df["MatchDate"].max()
        days_diff = (max_date - df["MatchDate"]).dt.days
        weights = np.exp(-xi * days_diff)
    except Exception:
        weights = np.ones(len(df))

    df["Weight"] = weights

    total_weight = df["Weight"].sum()
    if total_weight <= 0:
        return 1.35, 1.15, 2.50

    avg_home_xg = (df["Home_xG"] * df["Weight"]).sum() / total_weight
    avg_away_xg = (df["Away_xG"] * df["Weight"]).sum() / total_weight

    home_matches = df[df["HomeTeam"] == home_team]
    away_matches = df[df["AwayTeam"] == away_team]

    if home_matches.empty or away_matches.empty:
        return round(float(avg_home_xg), 3), round(float(avg_away_xg), 3), round(float(avg_home_xg + avg_away_xg), 3)

    if len(home_matches) > rolling_window:
        home_matches = home_matches.tail(rolling_window)
    if len(away_matches) > rolling_window:
        away_matches = away_matches.tail(rolling_window)

    h_w = home_matches["Weight"].sum()
    h_att_xg = (((home_matches["Home_xG"] * home_matches["Weight"]).sum() / h_w) / avg_home_xg) if h_w > 0 else 1.0
    h_def_xg = (((home_matches["Away_xG"] * home_matches["Weight"]).sum() / h_w) / avg_away_xg) if h_w > 0 else 1.0

    a_w = away_matches["Weight"].sum()
    a_att_xg = (((away_matches["Away_xG"] * away_matches["Weight"]).sum() / a_w) / avg_away_xg) if a_w > 0 else 1.0
    a_def_xg = (((away_matches["Home_xG"] * away_matches["Weight"]).sum() / a_w) / avg_home_xg) if a_w > 0 else 1.0

    lam_home = h_att_xg * a_def_xg * avg_home_xg
    lam_away = a_att_xg * h_def_xg * avg_away_xg

    lam_home = max(0.20, min(lam_home, 3.80))
    lam_away = max(0.20, min(lam_away, 3.50))

    return round(float(lam_home), 3), round(float(lam_away), 3), round(float(lam_home + lam_away), 3)

def calculate_team_ratings():
    """
    Builds the global team ratings registry used by main.py.
    Extracts all distinct active teams from both EPL and La Liga datasets.
    """
    ratings_dict = {}

    for sport_key in LEAGUE_CONFIG:
        df = load_league_data(sport_key)
        if df.empty or "HomeTeam" not in df.columns:
            continue

        teams = set(df["HomeTeam"].dropna().unique()).union(set(df["AwayTeam"].dropna().unique()))
        for t in teams:
            ratings_dict[t] = {
                "sport_key": sport_key,
                "active": True
            }

    # Also map common API naming conventions to match football-data names
    aliases = {
        "Manchester United": "Man United",
        "Manchester City": "Man City",
        "Newcastle United": "Newcastle",
        "Tottenham Hotspur": "Tottenham",
        "Wolverhampton Wanderers": "Wolves",
        "Nottingham Forest": "Nott'm Forest",
        "Brighton and Hove Albion": "Brighton",
        "West Ham United": "West Ham",
        "Sheffield United": "Sheffield United",
        "Atletico Madrid": "Ath Madrid",
        "Athletic Bilbao": "Ath Bilbao",
        "Real Betis": "Betis",
        "Celta Vigo": "Celta",
        "Espanyol Barcelona": "Espanyol"
    }

    for full_name, short_name in aliases.items():
        if short_name in ratings_dict:
            ratings_dict[full_name] = ratings_dict[short_name]

    return ratings_dict

if __name__ == "__main__":
    print("Testing ratings build...")
    ratings = calculate_team_ratings()
    print(f"Loaded {len(ratings)} team entries into rating index.")