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

    # 1. Primary standard data source (includes shots on target HS/AS and shots HST/AST)
    url = f"https://www.football-data.co.uk/mmz4281/2526/{league_code}.csv"
    content = None
    try:
        res = session.get(url, timeout=10)
        if res.status_code == 200 and len(res.content) > 1000:
            content = res.content
    except Exception:
        pass

    # 2. Fallback to mirror if football-data is slow/down
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
        df = pd.read_csv(io.StringIO(content.decode("utf-8", errors="ignore")))
        
        # Synthesize shot-quality Expected Goals (xG) if explicit xG column is not provided
        # Institutional benchmark shot-conversion:
        # Expected Goals = 0.30 * Shots On Target + 0.07 * Off-Target Shots + 0.76 * Penalty
        if "HST" in df.columns and "AST" in df.columns and "HS" in df.columns and "AS" in df.columns:
            # Home xG: On-target weight + general open play shot generation weight
            df["Home_xG"] = (df["HST"] * 0.32) + ((df["HS"] - df["HST"]).clip(lower=0) * 0.055)
            df["Away_xG"] = (df["AST"] * 0.32) + ((df["AS"] - df["AST"]).clip(lower=0) * 0.055)
        else:
            # Fallback to actual goals if detailed box scores are not in feed
            df["Home_xG"] = df["FTHG"].astype(float)
            df["Away_xG"] = df["FTAG"].astype(float)

        df.to_csv(cache_file, index=False)
        return df

    return pd.DataFrame()

def calculate_match_lambdas(home_team, away_team, sport_key="soccer_epl", rolling_window=10, xi=0.0077):
    """
    Calculates expected goals (lambdas) using Rolling xG and Exponential Time-Decay.
    Replaces actual goals with shot-derived expected goals to eliminate lucky scoreline bias.
    """
    df = load_league_data(sport_key)
    if df.empty or "Home_xG" not in df.columns or "Away_xG" not in df.columns:
        return 1.35, 1.15, 2.50

    df = df.dropna(subset=["Home_xG", "Away_xG", "HomeTeam", "AwayTeam"]).copy()

    # Apply exponential decay weighting to prioritize recent form
    try:
        df["MatchDate"] = pd.to_datetime(df["Date"], dayfirst=True)
        max_date = df["MatchDate"].max()
        days_diff = (max_date - df["MatchDate"]).dt.days
        weights = np.exp(-xi * days_diff)
    except Exception:
        weights = np.ones(len(df))

    df["Weight"] = weights

    # Baseline league expected goals averages
    total_weight = df["Weight"].sum()
    avg_home_xg = (df["Home_xG"] * df["Weight"]).sum() / total_weight
    avg_away_xg = (df["Away_xG"] * df["Weight"]).sum() / total_weight

    # Extract team matches
    home_matches = df[df["HomeTeam"] == home_team]
    away_matches = df[df["AwayTeam"] == away_team]

    if home_matches.empty or away_matches.empty:
        # Fallback to league baseline for newly promoted or mismatched name keys
        return round(float(avg_home_xg), 3), round(float(avg_away_xg), 3), round(float(avg_home_xg + avg_away_xg), 3)

    # Restrict to rolling window of matches if desired
    if len(home_matches) > rolling_window:
        home_matches = home_matches.tail(rolling_window)
    if len(away_matches) > rolling_window:
        away_matches = away_matches.tail(rolling_window)

    # Home Attack (xG created at home) / Defense (xG conceded at home)
    h_w = home_matches["Weight"].sum()
    h_att_xg = ((home_matches["Home_xG"] * home_matches["Weight"]).sum() / h_w) / avg_home_xg
    h_def_xg = ((home_matches["Away_xG"] * home_matches["Weight"]).sum() / h_w) / avg_away_xg

    # Away Attack (xG created away) / Defense (xG conceded away)
    a_w = away_matches["Weight"].sum()
    a_att_xg = ((away_matches["Away_xG"] * away_matches["Weight"]).sum() / a_w) / avg_away_xg
    a_def_xg = ((away_matches["Home_xG"] * away_matches["Weight"]).sum() / a_w) / avg_home_xg

    # Projected lambdas using xG regression
    lam_home = h_att_xg * a_def_xg * avg_home_xg
    lam_away = a_att_xg * h_def_xg * avg_away_xg

    # Apply sanity bounds to prevent extreme Poisson distortions
    lam_home = max(0.20, min(lam_home, 3.80))
    lam_away = max(0.20, min(lam_away, 3.50))

    return round(float(lam_home), 3), round(float(lam_away), 3), round(float(lam_home + lam_away), 3)

if __name__ == "__main__":
    print("=" * 65)
    print(" TESTING ROLLING xG ENGINE IN RATINGS.PY ")
    print("=" * 65)

    # Test EPL fixture
    lh_epl, la_epl, tot_epl = calculate_match_lambdas("Arsenal", "Chelsea", sport_key="soccer_epl")
    print(f"EPL [Arsenal vs Chelsea]       -> λ_Home (xG): {lh_epl:.2f} | λ_Away (xG): {la_epl:.2f} | Total: {tot_epl:.2f}")

    # Test La Liga fixture
    lh_esp, la_esp, tot_esp = calculate_match_lambdas("Real Madrid", "Barcelona", sport_key="soccer_spain_la_liga")
    print(f"La Liga [Real Madrid vs Barca] -> λ_Home (xG): {lh_esp:.2f} | λ_Away (xG): {la_esp:.2f} | Total: {tot_esp:.2f}")
    print("=" * 65)