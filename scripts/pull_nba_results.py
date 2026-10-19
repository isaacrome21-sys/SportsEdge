"""Pull per-game NBA player box scores (PTS/REB/AST) from the
sportsdataverse nba_stats_player_boxscores release asset. Read-only.

The live nba_api / stats.nba.com path failed four consecutive times from
GitHub runners (runs 39189944292, 39190353182, 39191026493) and is replaced
by this static release asset. The release names files by season key, which
is the ending year: 2025-26 -> 2026.
"""
import argparse, csv, io, os, time
import urllib.request

RELEASE_URL = ("https://github.com/sportsdataverse/sportsdataverse-data/"
               "releases/download/nba_stats_player_boxscores/"
               "player_boxscores_{key}.csv")

# Output contract (same names as before). GAME_DATE and MATCHUP are not in
# this asset, so they are not emitted; game_id links to other sources.
OUT_COLS = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GAME_ID",
            "MIN", "PTS", "REB", "AST", "SEASON", "SEASON_TYPE_ID"]

TIMEOUT_SECONDS = 240
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 5


def season_key(season: str) -> str:
    """'2025-26' -> '2026'; a bare '2026' is passed through."""
    head = season.split("-")[0].strip()
    return str(int(head) + 1) if "-" in season else head


def download(url: str) -> bytes:
    """Fetch the release asset with retry and exponential backoff."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
                return resp.read()
        except Exception as exc:
            last_error = exc
            wait = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            print(f"attempt {attempt}/{MAX_ATTEMPTS} failed for {url}: {exc!r}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(wait)
    raise RuntimeError(
        f"release download failed after {MAX_ATTEMPTS} attempts: {last_error!r}"
    )


def rows_for(season: str):
    key = season_key(season)
    text = download(RELEASE_URL.format(key=key)).decode("utf-8", errors="replace")
    for row in csv.DictReader(io.StringIO(text)):
        yield {
            "PLAYER_ID": row.get("person_id", ""),
            "PLAYER_NAME": f"{row.get('first_name', '')} {row.get('family_name', '')}".strip(),
            "TEAM_ABBREVIATION": row.get("team_tricode", ""),
            "GAME_ID": row.get("game_id", ""),
            "MIN": row.get("minutes", ""),
            "PTS": row.get("points", ""),
            "REB": row.get("rebounds_total", ""),
            "AST": row.get("assists", ""),
            "SEASON": row.get("season", ""),
            "SEASON_TYPE_ID": row.get("season_type_id", ""),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for season in [s.strip() for s in args.seasons.split(",") if s.strip()]:
        out = os.path.join(args.out, f"nba_player_games_{season}.csv")
        n = 0
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=OUT_COLS)
            w.writeheader()
            for row in rows_for(season):
                w.writerow(row)
                n += 1
        if n == 0:
            raise RuntimeError(f"{season}: release asset produced 0 rows")
        print(f"{season}: {n} player-games -> {out}")
        time.sleep(3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
