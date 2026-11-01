import pandas as pd

# Free, updated EPL match results feed for the current season
CSV_URL = "https://www.football-data.co.uk/mmz4252/2425/E0.csv"

def get_dynamic_team_ratings():
    """
    Downloads current season results and computes attack/defense strengths.
    """
    try:
        df = pd.read_csv(CSV_URL)
    except Exception:
        # Fallback if offline
        return {}, 1.50, 1.20

    # Filter to completed matches with goals recorded
    df = df.dropna(subset=['FTHG', 'FTAG'])

    total_matches = len(df)
    if total_matches == 0:
        return {}, 1.50, 1.20

    league_home_goals = df['FTHG'].mean()
    league_away_goals = df['FTAG'].mean()

    # Calculate home/away scored and conceded per team
    home_stats = df.groupby('HomeTeam').agg(
        home_games=('FTHG', 'count'),
        home_goals_scored=('FTHG', 'sum'),
        home_goals_conceded=('FTAG', 'sum')
    )

    away_stats = df.groupby('AwayTeam').agg(
        away_games=('FTAG', 'count'),
        away_goals_scored=('FTAG', 'sum'),
        away_goals_conceded=('FTHG', 'sum')
    )

    # Combine stats
    teams = list(set(home_stats.index).union(set(away_stats.index)))
    ratings = {}

    for team in teams:
        h_games = home_stats.loc[team, 'home_games'] if team in home_stats.index else 0
        a_games = away_stats.loc[team, 'away_games'] if team in away_stats.index else 0
        total_games = h_games + a_games

        if total_games == 0:
            continue

        h_scored = home_stats.loc[team, 'home_goals_scored'] if team in home_stats.index else 0
        a_scored = away_stats.loc[team, 'away_goals_scored'] if team in away_stats.index else 0
        h_conceded = home_stats.loc[team, 'home_goals_conceded'] if team in home_stats.index else 0
        a_conceded = away_stats.loc[team, 'away_goals_conceded'] if team in away_stats.index else 0

        avg_scored = (h_scored + a_scored) / total_games
        avg_conceded = (h_conceded + a_conceded) / total_games
        league_avg_total = (league_home_goals + league_away_goals) / 2.0

        # Relative strength ratios
        att_rating = avg_scored / league_avg_total
        def_rating = avg_conceded / league_avg_total

        ratings[team] = {"att": round(att_rating, 2), "def": round(def_rating, 2)}

    return ratings, league_home_goals, league_away_goals

# Load ratings once at startup
TEAM_RATINGS, LEAGUE_AVG_HOME, LEAGUE_AVG_AWAY = get_dynamic_team_ratings()

def calculate_match_lambdas(home_team, away_team):
    # If a newly promoted or unknown club appears, default to below-average profile
    default_rating = {"att": 0.85, "def": 1.25}

    h_rating = TEAM_RATINGS.get(home_team, default_rating)
    a_rating = TEAM_RATINGS.get(away_team, default_rating)

    lambda_home = h_rating["att"] * a_rating["def"] * LEAGUE_AVG_HOME
    lambda_away = a_rating["att"] * h_rating["def"] * LEAGUE_AVG_AWAY

    return lambda_home, lambda_away, (lambda_home + lambda_away)