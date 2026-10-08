#!/usr/bin/env python3
"""Resume the fixed CFB SDV placebo experiment; never change candidate bytes.

Feature and fit memoization only remove repeated calls with identical inputs.
Every checkpoint binds the complete inputs and its replicate. Partial results
cannot select a winner. This is reconstruction/selection research, not PIT.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import random
import time

from sportsedge.sports.cfb import sportsdataverse_bakeoff as bakeoff
from sportsedge.sports.cfb import sportsdataverse_candidate_model as model
from sportsedge.sports.cfb.sportsdataverse_prereg_hash import CODE_PATHS, CONFIG_PATHS, verify

COUNT = 200
LABELS = {"home_points", "away_points"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def features(row):
    return {k: v for k, v in row.items() if k not in LABELS}


@contextmanager
def memoized_calls(rows, config):
    """Keep all fitting/math in the frozen functions, with exact input keys."""
    original_vector = model.feature_vector
    original_fit = bakeoff.fit_native_score_model
    fixed = {}
    vectors = {}
    fitted = {}
    constants = {f: dict(config["candidates"][f].get("constants") or {}) for f in model.FAMILIES}
    for row in rows:
        key = (row["season"], row["game_id"])
        if key in fixed:
            raise ValueError("CFB_NULL_DUPLICATE_GAME_ID")
        fixed[key] = copy.deepcopy(features(row))
        for family in model.FAMILIES:
            vector = original_vector(family, row, constants[family])
            vector.flags.writeable = False
            vectors[(family, key)] = vector

    def check(row):
        key = (row["season"], row["game_id"])
        if features(row) != fixed.get(key):
            raise ValueError("CFB_NULL_FEATURES_CHANGED")
        return key

    def vector(family, row, supplied=None):
        if dict(supplied or {}) != constants[family]:
            raise ValueError("CFB_NULL_CONSTANTS_CHANGED")
        return vectors[(family, check(row))]

    def fit(rows, *, family, ridge_alpha, constants=None):
        identities = tuple((check(r), r["home_points"], r["away_points"]) for r in rows)
        key = (family, ridge_alpha, digest(constants or {}), identities)
        if key not in fitted:
            fitted[key] = original_fit(rows, family=family, ridge_alpha=ridge_alpha, constants=constants)
        return fitted[key]

    model.feature_vector = vector
    bakeoff.fit_native_score_model = fit
    try:
        yield fitted
    finally:
        model.feature_vector = original_vector
        bakeoff.fit_native_score_model = original_fit


def shuffled_rows(rows, rep):
    shuffled = copy.deepcopy(rows)
    by_season = {}
    for i, row in enumerate(shuffled):
        by_season.setdefault(int(row["season"]), []).append(i)
    for season, indices in sorted(by_season.items()):
        raw = f"SportsEdge|CFB_MODEL_SELECTION_POLICY_V1|PLACEBO_V1|{rep}|{season}".encode()
        seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
        pairs = [(shuffled[i]["home_points"], shuffled[i]["away_points"]) for i in indices]
        random.Random(seed).shuffle(pairs)
        for i, pair in zip(indices, pairs):
            shuffled[i]["home_points"], shuffled[i]["away_points"] = pair
    return shuffled


def write_once(path, payload):
    raw = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text() != raw:
            raise ValueError("CFB_NULL_CHECKPOINT_COLLISION")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        handle.write(raw)


def checkpoint(rep, result, binding):
    data = {"replicate": rep, "binding": binding, "result": result}
    return {**data, "sha256": digest(data)}


def read_checkpoint(path, rep, binding):
    data = json.loads(path.read_text())
    sha = data.pop("sha256")
    if data.get("replicate") != rep or data.get("binding") != binding or digest(data) != sha:
        raise ValueError("CFB_NULL_CHECKPOINT_IDENTITY_INVALID")
    return data["result"]


def aggregate(observed, results, policy):
    if set(results) != set(range(COUNT)):
        raise ValueError("CFB_NULL_ALL_200_REPLICATES_REQUIRED")
    families = policy["candidate_families_predeclared"]
    baseline, *challengers = families
    gates = {}
    for family in challengers:
        values = sorted(float(results[i]["observed"][baseline]["selection_metric"]) -
                        float(results[i]["observed"][family]["selection_metric"]) for i in range(COUNT))
        # Identical interpolation to the frozen workflow (199 * .95 = 189.05).
        pos = (len(values) - 1) * .95
        lo = int(pos)
        frac = pos - lo
        threshold = values[lo] * (1 - frac) + values[min(lo + 1, len(values) - 1)] * frac
        improvement = float(observed["observed"][baseline]["selection_metric"]) - float(observed["observed"][family]["selection_metric"])
        gates[family] = {"observed_improvement_vs_equal_weight": improvement,
                         "null_q95": threshold, "passes": improvement > threshold}
    passing = [f for f in challengers if gates[f]["passes"]]
    winner = min(passing, key=lambda f: (observed["observed"][f]["selection_metric"], families.index(f))) if passing else None
    out = copy.deepcopy(observed)
    out["pre_null_selected_family"] = out["selected_family"]
    out["selected_family"] = winner
    out["selection_status"] = "WINNER_SELECTED" if winner else "NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE"
    out["null_control"] = {"shuffle_count": COUNT, "candidate_gates": gates,
                           "seed_policy": "SHA256_FIRST8_BIG_ENDIAN_PER_REP_SEASON_V1"}
    out["governance"] = {"attempts_consumed": 4, "additional_candidate_attempts": 0,
                         "null_control_enforced": True, "model_p_created": False,
                         "promotion_authority": False, "official_authority": False}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stop", type=int, default=COUNT)
    args = parser.parse_args()
    if not 0 <= args.start <= args.stop <= COUNT:
        raise ValueError("CFB_NULL_REPLICATE_RANGE_INVALID")
    config = json.loads(Path("config/cfb_sportsdataverse_candidate_prereg_v1.json").read_text())
    policy = json.loads(Path("config/cfb_model_selection_policy_v1.json").read_text())
    hashes = config["hash_binding"]
    verify(hashes["code_manifest_sha256"], hashes["config_bundle_sha256"],
           {p: Path(p).read_text() for p in (*CODE_PATHS, *CONFIG_PATHS)})
    if policy["placebo_policy"]["shuffle_count"] != COUNT or policy["candidate_attempt_budget"] != 4:
        raise ValueError("CFB_NULL_POLICY_CHANGED")
    if policy["candidate_families_predeclared"] != config["candidate_selection_policy"]["family_order"]:
        raise ValueError("CFB_NULL_FAMILIES_CHANGED")
    rows = json.loads(args.rows.read_text())
    binding = {"rows_sha256": digest(rows), "prereg_sha256": digest(config), "policy_sha256": digest(policy),
               "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "numpy_version": __import__("numpy").__version__, "frozen_hashes": hashes}
    # Validate existing identities before doing any expensive work.
    for rep in [-1, *range(COUNT)]:
        path = args.output_dir / f"replicate_{rep:03}.json"
        if path.exists():
            read_checkpoint(path, rep, binding)
    with memoized_calls(rows, config) as fits:
        for rep in [-1, *range(args.start, args.stop)]:
            path = args.output_dir / f"replicate_{rep:03}.json"
            if path.exists():
                continue
            began = time.monotonic()
            fits.clear()  # No fits are shared between shuffled labels.
            result = bakeoff.evaluate_native_candidates(rows if rep == -1 else shuffled_rows(rows, rep), config)
            write_once(path, checkpoint(rep, result, binding))
            print(json.dumps({"replicate": rep, "seconds": round(time.monotonic() - began, 2)}), flush=True)
    paths = {i: args.output_dir / f"replicate_{i:03}.json" for i in range(COUNT)}
    if all(p.exists() for p in paths.values()):
        observed = read_checkpoint(args.output_dir / "replicate_-01.json", -1, binding)
        result = aggregate(observed, {i: read_checkpoint(p, i, binding) for i, p in paths.items()}, policy)
        result["replay_binding"] = binding
        write_once(args.output_dir / "completed_null_control.json", result)
        print(json.dumps({"status": result["selection_status"], "selected_family": result["selected_family"]}), flush=True)
    else:
        print(json.dumps({"status": "INCOMPLETE_NULL_CONTROL", "completed": sum(p.exists() for p in paths.values())}), flush=True)


if __name__ == "__main__":
    main()
