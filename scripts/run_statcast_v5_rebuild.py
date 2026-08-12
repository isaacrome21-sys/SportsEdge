#!/usr/bin/env python3
"""Source-bounded entrypoint for the predeclared Statcast V5 rebuild.

Unlike the initial probe, this derives each Savant season range from the actual
first/last regular-season final present in MLB StatsAPI, avoiding preseason and
postseason calendar ranges entirely.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib, json, os, sys
from pathlib import Path

import pandas as pd

# Allow importing the sibling rebuild module when this file is executed directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rebuild_statcast_v5 as r
from sportsedge.statcast_v5_pipeline import apply_contact_transformer, fetch_savant_events, fit_contact_transformer, save_joblib_hashed


def main() -> None:
    cache = Path(os.getenv("SPORTSEDGE_STATCAST_V5_CACHE", ".cache/sportsedge/statcast-v5"))
    out_dir = Path(os.getenv("SPORTSEDGE_STATCAST_V5_OUT", "artifacts/statcast-v5"))
    games = r.fetch_games(cache / "schedule")
    dates_by_year: dict[int, list[date]] = defaultdict(list)
    for g in games:
        dates_by_year[int(g["year"])].append(date.fromisoformat(g["officialDate"]))
    frames = []
    source_ranges = {}
    for year in r.YEARS:
        ds = dates_by_year.get(year) or []
        if not ds:
            raise SystemExit(f"NO_REGULAR_SEASON_GAMES_FOR_YEAR:{year}")
        lo, hi = min(ds), max(ds)
        source_ranges[str(year)] = {"start": lo.isoformat(), "end": hi.isoformat()}
        frames.append(fetch_savant_events(lo, hi, cache / "savant" / str(year)))
    raw = pd.concat(frames, ignore_index=True)
    train_raw = raw[pd.to_datetime(raw["game_date"]).dt.year <= 2023].copy()
    transformer = fit_contact_transformer(train_raw)
    transformer_path = out_dir / "sportsedge_contact_x_v1.joblib"
    transformer_sha = save_joblib_hashed(transformer, transformer_path)
    contact = apply_contact_transformer(raw, transformer)
    f = r.build_rows(games, raw, contact, transformer["global_prior"])
    validation = r.train_and_score(f, transformer_sha, out_dir)
    validation["savant_source_ranges"] = source_ranges
    (out_dir / "statcast_v5_validation.json").write_text(json.dumps(validation, indent=2, sort_keys=True))
    manifest_paths = [transformer_path, out_dir / "sportsedge_game_score_v5_statcast.joblib", out_dir / "sportsedge_nrfi_v5_statcast.joblib", out_dir / "statcast_v5_validation.json"]
    manifest = {"schema_version": 1, "files": []}
    for p in manifest_paths:
        b = p.read_bytes(); manifest["files"].append({"path": str(p), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(validation, indent=2, sort_keys=True))
    failed = [m for m, v in validation["markets"].items() if not v["pass"]]
    if failed:
        raise SystemExit("STATCAST_V5_HOLDOUT_FAILED:" + ",".join(failed))
    print("STATCAST_V5_HOLDOUT_PASS")


if __name__ == "__main__":
    main()
