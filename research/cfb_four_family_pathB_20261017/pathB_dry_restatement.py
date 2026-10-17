"""Path B matched-count restatement (dry run, NOT_RUN, zero probabilities).
Uses the frozen bindings loaders + build_dry_run_manifest on the rebuilt,
byte-verified snapshots, filtering games to the regular season. The draft
config is NOT edited."""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])  # repo root (freeze branch worktree)
from sportsedge.research import cfb_four_family_bindings_v1 as bindings
out = Path(sys.argv[2])
cfg = json.load(open(Path(sys.argv[1]) / "config/research/cfb_four_family_bindings_v1.json"))
results_payload, games = bindings.load_results_snapshot((out / "results_snapshot.json").read_bytes())
idx = {r["game_id"]: r for r in results_payload["games"]}
lines = bindings.load_lines_snapshot((out / "lines_snapshot.json").read_bytes(), results_index=idx)
directory = bindings.DirectorySnapshot(json.loads((out / "directory_snapshot.json").read_bytes()))
st = {r["game_id"]: str(r.get("season_type") or "") for r in results_payload["games"]}
res = {}
for label, keep in (("PATH_A_AS_FROZEN", lambda g: True),
                    ("PATH_B_BLANK_AS_REGULAR", lambda g: st[g.game_id] != "3"),
                    ("PATH_B_STRICT_TYPE2", lambda g: st[g.game_id] == "2")):
    m = bindings.build_dry_run_manifest(bindings_cfg=cfg, results_snapshot_id=results_payload.get("snapshot_id", ""),
        lines_snapshot_id="", games=[g for g in games if keep(g)], lines_load=lines, directory=directory)
    assert m["probabilities_computed"] is False and m["attempts_consumed"] == 0
    res[label] = {"population": m["population"]["population_games"],
                  "burn_in": m["population"]["burn_in_population_games"],
                  "folds": {s: {"pop": f["population_games"], **{k: v["matched_games"] for k, v in f["families"].items()},
                                "ml_cov": round(f["families"]["moneyline"]["coverage"], 4),
                                "ml_floor_ok": f["families"]["moneyline"]["would_pass_fold_floor"]}
                            for s, f in m["folds"].items()},
                  "pooled": {k: v["matched_games"] for k, v in m["pooled"].items()},
                  "pooled_floor_ok": {k: v["would_pass_pooled_floor"] for k, v in m["pooled"].items()}}
print(json.dumps(res, indent=1))
