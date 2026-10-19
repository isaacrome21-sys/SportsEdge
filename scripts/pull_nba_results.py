"""Pull per-game player stats (PTS/REB/AST) from stats.nba.com via nba_api. Read-only."""
import argparse, os, time
from nba_api.stats.endpoints import playergamelogs

COLS = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GAME_ID",
        "GAME_DATE", "MATCHUP", "MIN", "PTS", "REB", "AST"]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for season in [s.strip() for s in args.seasons.split(",") if s.strip()]:
        df = playergamelogs.PlayerGameLogs(season_nullable=season, timeout=60).get_data_frames()[0]
        out = os.path.join(args.out, f"nba_player_games_{season}.csv")
        df[[c for c in COLS if c in df.columns]].to_csv(out, index=False)
        print(f"{season}: {len(df)} player-games -> {out}")
        time.sleep(3)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
