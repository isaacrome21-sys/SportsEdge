"""Pull per-game player stats (PTS/REB/AST) from stats.nba.com via nba_api. Read-only."""
import argparse, os, time
from nba_api.stats.endpoints import playergamelogs

COLS = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GAME_ID",
        "GAME_DATE", "MATCHUP", "MIN", "PTS", "REB", "AST"]

TIMEOUT_SECONDS = 240
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 5


def fetch_season(season: str):
    """Fetch one season, retrying read timeouts with exponential backoff."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return playergamelogs.PlayerGameLogs(
                season_nullable=season, timeout=TIMEOUT_SECONDS
            ).get_data_frames()[0]
        except Exception as exc:  # nba_api raises requests/urllib3 errors
            last_error = exc
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            print(f"{season}: attempt {attempt}/{MAX_ATTEMPTS} failed: {exc!r}; "
                  f"retrying in {wait}s" if attempt < MAX_ATTEMPTS else
                  f"{season}: attempt {attempt}/{MAX_ATTEMPTS} failed: {exc!r}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(wait)
    raise RuntimeError(
        f"NBA stats pull failed for {season} after {MAX_ATTEMPTS} attempts; "
        f"last error: {last_error!r}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for season in [s.strip() for s in args.seasons.split(",") if s.strip()]:
        df = fetch_season(season)
        out = os.path.join(args.out, f"nba_player_games_{season}.csv")
        df[[c for c in COLS if c in df.columns]].to_csv(out, index=False)
        print(f"{season}: {len(df)} player-games -> {out}")
        time.sleep(3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
