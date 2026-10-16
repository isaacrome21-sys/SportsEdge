"""Build the compact per-game metrics input from pmf_rows.jsonl.

One row per scored game: realized hits, the candidate's path_set_id and
readout hash, and for every scorer the per-side RPS values on the
preregistered grids and the typical-line over-probabilities. Every number
in results.json (means, best baseline, bootstrap CI, ECE, log loss, legs)
is recomputable from this file alone; verify_results.py does exactly that.

Usage: make_metrics_input.py <pmf_rows.jsonl> <manifest.json> <out.jsonl>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics as mx  # noqa: E402


def main() -> None:
    pmf_path, manifest_path, out_path = (Path(sys.argv[1]), Path(sys.argv[2]),
                                         Path(sys.argv[3]))
    manifest = json.loads(manifest_path.read_text())
    typical = manifest["folds"]["2025"]["typical_lines"]
    rows = [json.loads(x) for x in pmf_path.read_text().splitlines() if x.strip()]
    rows.sort(key=lambda r: (r["date"], r["game_id"]))
    with out_path.open("w") as fh:
        for row in rows:
            rec = {"game_id": row["game_id"], "date": row["date"],
                   "realized": row["realized"],
                   "path_set_id": row["path_set_id"],
                   "readout_sha256": row["readout_sha256"],
                   "rps": {}, "pover": {}}
            for s in mx.SCORERS:
                src = row["candidate"] if s == "candidate" else row["baselines"][s]
                rec["rps"][s] = {
                    "game": mx.rps(src["game"], row["realized"]["game"], mx.GAME_K),
                    "away": mx.rps(src["away"], row["realized"]["away"], mx.TEAM_K),
                    "home": mx.rps(src["home"], row["realized"]["home"], mx.TEAM_K)}
                rec["pover"][s] = {
                    "game": mx.p_over(src["game"], typical["GAME_TOTAL_HITS"]),
                    "away": mx.p_over(src["away"], typical["TEAM_TOTAL_HITS"]),
                    "home": mx.p_over(src["home"], typical["TEAM_TOTAL_HITS"])}
            fh.write(json.dumps(rec) + "\n")
    print(f"wrote {out_path}: {len(rows)} games")


if __name__ == "__main__":
    main()
