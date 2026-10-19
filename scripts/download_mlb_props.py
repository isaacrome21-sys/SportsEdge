#!/usr/bin/env python3
"""Stream SmartStake/mlb-player-props and save strikeouts/hits/total-bases lines.
Draft: prints schema on first run. Caps at 2M rows."""
from datasets import load_dataset
import pandas as pd
import sys

def main():
    print("Loading streaming dataset...")
    ds = load_dataset("SmartStake/mlb-player-props", split="train", streaming=True)
    
    # Print schema from first batch
    first = list(ds.take(100))
    if not first:
        print("Empty dataset")
        return
    df_first = pd.DataFrame(first)
    print("Schema columns:", df_first.columns.tolist())
    print(df_first.head(3).to_string())
    
    # Keyword filter (adjust after first run if needed)
    keywords = ["strikeout", "k's", "hits", "total bases", "tb", "bases"]
    market_cols = [c for c in df_first.columns if c.lower() in ("market", "market_name", "prop")]
    if not market_cols:
        print("No market column found. Update filter.")
        return
    market_col = market_cols[0]
    
    print(f"Filtering on {market_col} for {keywords}")
    rows = []
    cap = 2_000_000
    for i, row in enumerate(ds):
        if i >= cap:
            break
        market = str(row.get(market_col, "")).lower()
        if any(k in market for k in keywords):
            rows.append(row)
        if len(rows) % 100000 == 0 and rows:
            print(f"Collected {len(rows)} matching rows...")
    
    if rows:
        out = pd.DataFrame(rows)
        out.to_parquet("mlb_props_filtered.parquet", index=False)
        print(f"Saved {len(out)} rows to mlb_props_filtered.parquet")
    else:
        print("No matching rows")

if __name__ == "__main__":
    main()
