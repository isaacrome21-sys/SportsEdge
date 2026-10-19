#!/usr/bin/env python3
"""Pull NBA player game logs (PTS etc.) via nba_api. Seasons one at a time with pause.
Draft: has not been run from this environment."""
from nba_api.stats.endpoints import playergamelog
import pandas as pd
import time
import sys

SEASONS = ["2023-24", "2024-25", "2025-26"]  # adjust as needed

def main():
    all_logs = []
    for season in SEASONS:
        print(f"Pulling {season}...")
        try:
            # Example: pull for a known player; expand to roster or league in production
            log = playergamelog.PlayerGameLog(player_id="2544", season=season)  # LeBron as smoke test
            df = log.get_data_frames()[0]
            df["season"] = season
            all_logs.append(df)
            print(f"  {len(df)} games")
        except Exception as e:
            print(f"  Failed {season}: {e}")
        time.sleep(3)
    
    if all_logs:
        out = pd.concat(all_logs, ignore_index=True)
        out.to_parquet("nba_player_logs.parquet", index=False)
        print(f"Saved {len(out)} rows to nba_player_logs.parquet")
    else:
        print("No data pulled")

if __name__ == "__main__":
    main()
