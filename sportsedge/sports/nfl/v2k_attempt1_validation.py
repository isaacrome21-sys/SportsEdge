"""NFL V2K Attempt-1 development-validation runner logic.

Wraps the frozen V2K core/adapter (exact blobs frozen in
NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V1.json) with:

* nflverse PBP -> one market-blind record per drive (REG season only);
* official schedule home/away identity and official final scores;
* per-game simulated margin/total histograms (sharded, order-independent seeds);
* the pre-registered structural and predictive gates.

Market fields (spread/total lines and prices) are read ONLY in ``evaluate``,
after every fold's model is fitted and simulated. They never reach the fit.

This module grants no Model_P, pricing, promotion, staking, RUN IT, OFFICIAL or
untouched-readout authority.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sportsedge.core.validation.calibration_truth_gate import evaluate_calibration_truth_gate
from .historical_validation import build_calibration_evidence, calibrate_nfl_evaluations, no_vig_two_way
from .v2k_drive_core import derive_path_seed, fit_hierarchical_strength, simulate_joint_game
from .v2k_drive_source import build_drive_rows_from_pbp

NFL = Path(__file__).resolve().parent
ROOT = NFL.parents[2]
CONTRACT_PATH = NFL / "NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V1.json"
LEDGER_PATH = NFL / "NFL_V2K_ATTEMPT_LEDGER_V1.json"
REFERENCE_PATH = NFL / "NFL_V2K_EMPIRICAL_KEY_REFERENCE_V1.json"

SHARD_SCHEMA = "NFL_V2K_ATTEMPT1_SHARD_V1"
RESULT_SCHEMA = "NFL_V2K_ATTEMPT1_DEVELOPMENT_VALIDATION_V2"
KEYS = (-7, -3, 3, 7)

# Predictive-gate parameters inherited verbatim from the frozen V2J readout
# (m2_v2j_validation.build_nfl_m2_v2j_candidate_evidence defaults), which the
# preattempt contract names as the provenance of the predictive gate.
MIN_CALIBRATION_FIT_SEASONS = 2
CALIBRATION_BINS = 10
CALIBRATION_MIN_BIN_N = 25

# nflverse fixed_drive_result -> adapter vocabulary (all map to the frozen
# canonical outcome; "Turnover" is any lost fumble/interception).
_RESULT_TO_ADAPTER = {
    "Touchdown": "touchdown",
    "Field goal": "field_goal",
    "Punt": "punt",
    "Turnover": "fumble",
    "Turnover on downs": "turnover_on_downs",
    "Missed field goal": "missed_field_goal",
    "Opp touchdown": "defensive_touchdown",
    "Safety": "safety",
}

AUTHORITY = {
    "model_p": False, "pricing": False, "promotion": False, "staking": False,
    "run_it": False, "official": False, "untouched_readout": False,
}


# --------------------------------------------------------------------- utils

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _int(value: Any) -> int | None:
    if value in (None, "", "NA"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value in (None, "", "NA"):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# ----------------------------------------------------------- pre-run checks

def preflight(*, paths: int, smoke: bool) -> dict:
    """Fail closed unless the frozen identity, budget and runtime all match."""
    import numpy

    contract = _load_json(CONTRACT_PATH)
    ledger = _load_json(LEDGER_PATH)
    ident = contract["unresolved_required_freezes"]["final_hardened_implementation_identity"]
    binding = contract["attempt1_issue_binding"]
    problems = []
    if contract["status"] != "FROZEN_ATTEMPT1_READY_FOR_DEVELOPMENT_VALIDATION" or contract["blocker_codes"]:
        problems.append("V2K_PREATTEMPT_NOT_READY")
    if not contract["attempt_budget"]["attempt_1_scoring_allowed"]:
        problems.append("V2K_ATTEMPT1_SCORING_NOT_ALLOWED")
    if ledger["attempts_used"] != 0 or ledger["attempts"]:
        problems.append("V2K_ATTEMPT1_ALREADY_CONSUMED")
    for key, rel in (("core_git_blob_sha1", "core_path"), ("source_adapter_git_blob_sha1", "source_adapter_path")):
        if git_blob_sha1(ROOT / ident[rel]) != ident[key]:
            problems.append("V2K_FROZEN_CODE_IDENTITY_MISMATCH:" + ident[rel])
    if numpy.__version__ != ident["runtime"]["numpy"]:
        problems.append("V2K_RUNTIME_NUMPY_MISMATCH:" + numpy.__version__)
    floor = int(binding["absolute_simulation_floor_paths_per_game"])
    frozen_paths = int(binding["simulation_count_paths_per_game"])
    if not smoke and paths != frozen_paths:
        problems.append(f"V2K_PATH_COUNT_NOT_FROZEN:{paths}!={frozen_paths}")
    if smoke and paths >= floor:
        problems.append("V2K_SMOKE_MUST_STAY_BELOW_FLOOR")
    if problems:
        raise SystemExit("PREFLIGHT_FAILED:" + ";".join(problems))
    return contract


def verify_sources(pbp_dir: Path, schedule_path: Path, contract: Mapping) -> dict:
    expected = contract["source_binding"]["pbp_sha256_by_season"]
    actual = {}
    for season, sha in expected.items():
        path = pbp_dir / f"play_by_play_{season}.csv.gz"
        if not path.exists():
            raise SystemExit(f"V2K_PBP_MISSING:{season}")
        actual[season] = sha256_file(path)
        if actual[season] != sha:
            raise SystemExit(f"V2K_PBP_SHA_MISMATCH:{season}")
    source = _load_json(ROOT / contract["source_binding"]["source_freeze_path"])
    sched_sha = sha256_file(schedule_path)
    if sched_sha != source["sources"]["schedule"]["expected_sha256"]:
        raise SystemExit("V2K_SCHEDULE_SHA_MISMATCH")
    return {"pbp_sha256_by_season": actual, "schedule_sha256": sched_sha}


# ------------------------------------------------------------- schedule

def load_schedule(path: Path) -> dict[str, dict]:
    """Official REG-season identity, final score and (evaluation-only) market lines."""
    out = {}
    for r in read_csv(path):
        season = _int(r.get("season"))
        if season is None or not 2018 <= season <= 2025 or r.get("game_type") != "REG":
            continue
        hs, as_ = _int(r.get("home_score")), _int(r.get("away_score"))
        if hs is None or as_ is None:
            raise SystemExit("V2K_FINAL_SCORE_MISSING:" + r["game_id"])
        out[r["game_id"]] = {
            "game_id": r["game_id"], "season": season, "week": _int(r.get("week")),
            "home_team": r["home_team"], "away_team": r["away_team"],
            "home_score": hs, "away_score": as_,
            # Evaluation-only market fields; never passed to fit or simulation.
            "_market": {
                "spread_line": _float(r.get("spread_line")), "total_line": _float(r.get("total_line")),
                "home_spread_odds": r.get("home_spread_odds"), "away_spread_odds": r.get("away_spread_odds"),
                "over_odds": r.get("over_odds"), "under_odds": r.get("under_odds"),
            },
        }
    return out


def schedule_identity(schedule: Mapping[str, Mapping]) -> dict[str, dict]:
    """Market-blind view of the schedule (safe for the fit/simulation path)."""
    return {g: {k: v for k, v in row.items() if k != "_market"} for g, row in schedule.items()}


# ------------------------------------------------------------- PBP -> drives

def pbp_game_drive_records(plays: Sequence[Mapping[str, str]], identity: Mapping) -> list[dict]:
    """Collapse one game's nflverse plays to one adapter record per fixed drive."""
    gid = identity["game_id"]
    home, away = identity["home_team"], identity["away_team"]
    # ``plays`` must be in nflverse file order (== order_sequence); play_id is
    # NOT chronological for late-inserted rows.
    ordered = [dict(p) for p in plays]
    pbp_pairs = {(p.get("home_team"), p.get("away_team")) for p in ordered}
    if len(pbp_pairs) != 1:
        raise ValueError("V2K_PBP_HOME_AWAY_INCONSISTENT:" + gid)
    pbp_home, pbp_away = next(iter(pbp_pairs))
    # nflverse PBP uses current franchise codes (e.g. LV for 2018 OAK); the
    # official schedule designation is authoritative for home/away identity.
    team_map = {pbp_home: home, pbp_away: away}
    for p in ordered:
        for col in ("posteam", "defteam"):
            if p.get(col):
                if p[col] not in team_map:
                    raise ValueError("V2K_PBP_TEAM_NOT_IN_GAME:" + gid)
                p[col] = team_map[p[col]]

    drives: dict[int, list] = defaultdict(list)
    for p in ordered:
        d = _int(p.get("fixed_drive"))
        if d is None or not p.get("posteam") or not p.get("defteam"):
            continue
        drives[d].append(p)
    if not drives:
        raise ValueError("V2K_GAME_HAS_NO_DRIVES:" + gid)

    last_drive = max(drives)
    records = []
    for d in sorted(drives):
        dplays = drives[d]
        conv = [p for p in dplays if p.get("play_type") == "extra_point" or p.get("two_point_attempt") == "1"]
        core = [p for p in dplays if p not in conv and p.get("play_type") not in ("", "NA", None)]
        scrimmage = [p for p in core if p.get("play_type") != "kickoff"] or core
        if not scrimmage:
            continue  # orphan conversion rows only
        teams = Counter((p["posteam"], p["defteam"]) for p in scrimmage)
        (offense, defense), _ = teams.most_common(1)[0]
        if {offense, defense} != {home, away}:
            raise ValueError("V2K_DRIVE_TEAMS_NOT_IN_GAME:" + gid)
        first = scrimmage[0]
        result = (first.get("fixed_drive_result") or "").strip()
        if not result and all(p.get("play_type") == "no_play" for p in scrimmage):
            continue  # phantom drive: only a nullified play (e.g. re-kick after penalty)
        # Drive start time = first live row (the kickoff when present); field
        # position = first scrimmage snap.
        start = core[0] if core else first
        period = _int(start.get("qtr"))
        if result == "End of half":
            if d == last_drive:
                adapter_result = "end_of_game"
            elif period is not None and period <= 2:
                adapter_result = "end_of_half"
            else:  # regulation expired tied; overtime follows
                adapter_result = "punt"
        elif result in _RESULT_TO_ADAPTER:
            adapter_result = _RESULT_TO_ADAPTER[result]
        else:
            raise ValueError(f"V2K_DRIVE_RESULT_UNMAPPED:{gid}:{d}:{result!r}")

        def team_scores(p):
            th, ta = _int(p.get("total_home_score")), _int(p.get("total_away_score"))
            if th is None or ta is None:
                return None
            return (th, ta) if offense == home else (ta, th)

        before_play = next((p for p in core if _int(p.get("posteam_score")) is not None), first)
        if before_play["posteam"] == offense:
            off_before, def_before = _int(before_play["posteam_score"]), _int(before_play["defteam_score"])
        else:
            off_before, def_before = _int(before_play["defteam_score"]), _int(before_play["posteam_score"])
        after = None
        for p in reversed(dplays):
            after = team_scores(p)
            if after is not None:
                break
        if off_before is None or def_before is None or after is None:
            raise ValueError(f"V2K_DRIVE_SCORE_STATE_MISSING:{gid}:{d}")

        conversion = 0
        if adapter_result == "touchdown":
            for p in conv:
                if p.get("posteam") != offense:
                    continue
                if p.get("extra_point_result") == "good":
                    conversion = 1
                elif p.get("two_point_conv_result") == "success":
                    conversion = 2

        records.append({
            "game_id": gid, "season": identity["season"], "week": identity["week"],
            "kickoff_utc": str(first.get("game_date") or ""), "drive_id": d,
            "play_index": int(first["_seq"]), "offense": offense, "defense": defense,
            "start_yardline_100": float(_float(first.get("yardline_100")) if _float(first.get("yardline_100")) is not None else 75.0),
            "drive_result": adapter_result,
            "offense_score_before": off_before, "defense_score_before": def_before,
            "offense_score_after": after[0], "defense_score_after": after[1],
            "period": period, "clock_seconds_remaining_period": _int(start.get("quarter_seconds_remaining")),
            "conversion_points": conversion, "drive_order": d,
        })
    return records


def build_season_drives(pbp_path: Path, identity: Mapping[str, Mapping], *, season: int,
                        source_manifest_sha: str, code_sha: str) -> tuple:
    by_game: dict[str, list] = defaultdict(list)
    for seq, p in enumerate(read_csv(pbp_path)):
        if p.get("season_type") == "REG" and p.get("game_id"):
            p["_seq"] = seq
            by_game[p["game_id"]].append(p)
    expected = {g for g, r in identity.items() if r["season"] == season}
    if set(by_game) != expected:
        raise SystemExit(f"V2K_PBP_SCHEDULE_GAME_SET_MISMATCH:{season}:"
                         f"pbp_only={sorted(set(by_game)-expected)[:5]}:sched_only={sorted(expected-set(by_game))[:5]}")
    records = []
    for gid in sorted(by_game):
        records.extend(pbp_game_drive_records(by_game[gid], identity[gid]))
        # Final-score cross-check: PBP terminal state must equal the official result.
        last = max((p for p in by_game[gid] if _int(p.get("total_home_score")) is not None), key=lambda p: p["_seq"])
        if (_int(last["total_home_score"]), _int(last["total_away_score"])) != (identity[gid]["home_score"], identity[gid]["away_score"]):
            raise SystemExit(f"V2K_PBP_FINAL_SCORE_MISMATCH:{gid}")
    return build_drive_rows_from_pbp(records, source_manifest_sha256=source_manifest_sha, source_code_sha=code_sha)


# ------------------------------------------------------------- simulation

def simulate_game_histograms(model, game: Mapping, *, root_seed: int, paths: int) -> dict:
    margins: Counter = Counter()
    totals: Counter = Counter()
    for idx in range(paths):
        seed = derive_path_seed(root_seed=root_seed, game_key=game["game_id"], path_index=idx)
        s = simulate_joint_game(model, game["home_team"], game["away_team"], season=game["season"], seed=seed)
        margins[s.margin] += 1
        totals[s.total] += 1
    return {"game_id": game["game_id"], "season": game["season"], "week": game["week"],
            "home_team": game["home_team"], "away_team": game["away_team"], "paths": paths,
            "margin_hist": {str(k): v for k, v in sorted(margins.items())},
            "total_hist": {str(k): v for k, v in sorted(totals.items())}}


def _sim_worker(args):
    model, game, root_seed, paths = args
    return simulate_game_histograms(model, game, root_seed=root_seed, paths=paths)


def run_fold_shard(*, fold: Mapping, drives_by_season: Mapping[int, tuple], identity: Mapping[str, Mapping],
                   root_seed: int, paths: int, shard_index: int, shard_count: int, workers: int) -> dict:
    train = [r for y in fold["train_seasons"] for r in drives_by_season[y]]
    model = fit_hierarchical_strength(train)
    games = sorted((g for g in identity.values() if g["season"] == fold["test_season"]), key=lambda g: g["game_id"])
    mine = [g for i, g in enumerate(games) if i % shard_count == shard_index]
    jobs = [(model, g, root_seed, paths) for g in mine]
    if workers > 1:
        from multiprocessing import get_context
        with get_context("fork").Pool(workers) as pool:
            results = pool.map(_sim_worker, jobs, chunksize=1)
    else:
        results = [_sim_worker(j) for j in jobs]
    return {"schema": SHARD_SCHEMA, "fold_id": fold["fold_id"], "train_seasons": list(fold["train_seasons"]),
            "test_season": fold["test_season"], "shard_index": shard_index, "shard_count": shard_count,
            "root_seed": root_seed, "paths_per_game": paths, "training_drive_rows": len(train),
            "fold_test_game_count": len(games), "games": results, "sportsbook_prices_consumed": False}


# ------------------------------------------------------------- evaluation

def _hist(h: Mapping[str, int]) -> list[tuple[int, int]]:
    return [(int(k), int(v)) for k, v in h.items()]


def _over_prob(hist, line):
    if line is None:
        return None
    win = sum(c for v, c in hist if v > line)
    push = sum(c for v, c in hist if v == line)
    n = sum(c for _, c in hist)
    if n - push <= 0:
        return None
    return min(1 - 1e-9, max(1e-9, win / (n - push)))


def _novig(a, b):
    if a in (None, "", "NA") or b in (None, "", "NA"):
        return None
    try:
        return no_vig_two_way(a, b)[0]
    except ValueError:
        return None


def _log_loss(pairs):
    from math import log
    tot = 0.0
    for o, p in pairs:
        p = min(1 - 1e-9, max(1e-9, float(p)))
        tot += -(o * log(p) + (1 - o) * log(1 - p))
    return tot / len(pairs)


def evaluate(shards: Iterable[Mapping], schedule: Mapping[str, Mapping], contract: Mapping) -> dict:
    """Pre-registered gates. Market fields are read here and only here."""
    binding = contract["attempt1_issue_binding"]
    gates = contract["already_frozen_gates"]
    pred = contract["unresolved_required_freezes"]["predictive_acceptance_thresholds"]
    reference = _load_json(REFERENCE_PATH)["reference"]["signed_margin_mass"]

    games: dict[str, dict] = {}
    seen_shards = defaultdict(set)
    for s in shards:
        if s["schema"] != SHARD_SCHEMA or s["root_seed"] != binding["root_seed"]:
            raise SystemExit("V2K_SHARD_IDENTITY_INVALID")
        seen_shards[(s["fold_id"], s["shard_count"])].add(s["shard_index"])
        for g in s["games"]:
            if g["game_id"] in games:
                raise SystemExit("V2K_DUPLICATE_GAME:" + g["game_id"])
            if g["paths"] != s["paths_per_game"]:
                raise SystemExit("V2K_PATH_COUNT_INCONSISTENT")
            games[g["game_id"]] = g
    for (fold_id, count), idx in seen_shards.items():
        if idx != set(range(count)):
            raise SystemExit(f"V2K_SHARDS_INCOMPLETE:{fold_id}")
    expected = {g for g, r in schedule.items() if 2021 <= r["season"] <= 2025}
    if set(games) != expected:
        raise SystemExit(f"V2K_EVALUATED_GAME_SET_MISMATCH:missing={len(expected-set(games))}:extra={len(set(games)-expected)}")
    if {f["fold_id"] for f in binding["fold_plan"]["folds"]} != {k[0] for k in seen_shards}:
        raise SystemExit("V2K_FOLD_SET_MISMATCH")

    rows = []
    key_sum = {k: 0.0 for k in KEYS}
    for gid in sorted(games):
        g, sched = games[gid], schedule[gid]
        if (g["home_team"], g["away_team"]) != (sched["home_team"], sched["away_team"]):
            raise SystemExit("V2K_HOME_AWAY_DRIFT:" + gid)
        mh, th = _hist(g["margin_hist"]), _hist(g["total_hist"])
        n = sum(c for _, c in mh)
        for k in KEYS:
            key_sum[k] += sum(c for v, c in mh if v == k) / n
        m = sched["_market"]
        margin = sched["home_score"] - sched["away_score"]
        total = sched["home_score"] + sched["away_score"]
        sl, tl = m["spread_line"], m["total_line"]
        rows.append({
            "game_id": gid, "season": sched["season"], "week": sched["week"],
            "home_score": sched["home_score"], "away_score": sched["away_score"],
            "spread_line": sl, "total_line": tl,
            "home_cover_outcome": None if sl is None or margin == sl else int(margin > sl),
            "over_outcome": None if tl is None or total == tl else int(total > tl),
            "m1_home_cover_prob": _novig(m["home_spread_odds"], m["away_spread_odds"]),
            "m1_over_prob": _novig(m["over_odds"], m["under_odds"]),
            "m2_home_cover_prob": _over_prob(mh, sl),
            "m2_over_prob": _over_prob(th, tl),
            "sim_mean_margin": sum(v * c for v, c in mh) / n,
            "sim_mean_total": sum(v * c for v, c in th) / n,
        })

    calibrated = calibrate_nfl_evaluations(rows, min_fit_seasons=MIN_CALIBRATION_FIT_SEASONS)
    calibration = build_calibration_evidence(calibrated, bins=CALIBRATION_BINS, min_bin_n=CALIBRATION_MIN_BIN_N,
                                             max_bin_deviation_threshold=float(pred["calibration_max_nonempty_bin_deviation"]))

    specs = {"spread": ("home_cover_outcome", "m1_home_cover_prob", "m2_home_cover_calibrated_prob"),
             "total": ("over_outcome", "m1_over_prob", "m2_over_calibrated_prob")}
    fold_rows, predictive = [], {}
    for market, (ok, bk, ck) in specs.items():
        wins = total_folds = 0
        for season in sorted({r["season"] for r in calibrated}):
            comp = [r for r in calibrated if r["season"] == season and r.get(ok) in (0, 1)
                    and r.get(ck) is not None and r.get(bk) is not None]
            if not comp:
                continue
            bll = _log_loss([(r[ok], r[bk]) for r in comp])
            cll = _log_loss([(r[ok], r[ck]) for r in comp])
            beat = cll < bll
            wins += beat
            total_folds += 1
            fold_rows.append({"season": season, "market": market, "n": len(comp), "baseline_log_loss": bll,
                              "candidate_log_loss": cll, "candidate_beats_baseline": beat})
        rate = wins / total_folds if total_folds else 0.0
        cal = calibration[market]
        cal_pass = cal["max_bin_deviation"] is not None and cal["max_bin_deviation"] <= float(pred["calibration_max_nonempty_bin_deviation"])
        predictive[market] = {"fold_wins": wins, "fold_total": total_folds, "fold_win_rate": rate,
                              "required_fold_win_rate": float(pred["minimum_fold_win_rate"]),
                              "fold_win_pass": bool(total_folds and rate >= float(pred["minimum_fold_win_rate"])),
                              "calibration_max_bin_deviation": cal["max_bin_deviation"],
                              "calibration_pass": cal_pass}
        predictive[market]["pass"] = predictive[market]["fold_win_pass"] and cal_pass

    n_games = len(games)
    key_prob = {str(k): key_sum[k] / n_games for k in KEYS}
    key_err = {str(k): abs(key_prob[str(k)] - float(reference[str(k)])) for k in KEYS}
    key_rmse = sqrt(sum(e * e for e in key_err.values()) / len(KEYS))
    slope_gate = evaluate_calibration_truth_gate(calibration["spread"]).to_dict()
    slope = slope_gate.get("slope")
    slope_metric = None if slope is None else abs(float(slope) - 1.0)
    structural = {
        "candidate_signed_key_probability": key_prob,
        "reference_signed_key_probability": {str(k): float(reference[str(k)]) for k in KEYS},
        "abs_error_by_key": key_err,
        "per_key_tolerance": float(gates["absolute_signed_key_mass_error_max"]),
        "per_key_tolerance_pass": all(e <= float(gates["absolute_signed_key_mass_error_max"]) for e in key_err.values()),
        "candidate_signed_key_mass_rmse": key_rmse,
        "control_signed_key_mass_rmse": float(gates["control_signed_key_mass_rmse"]),
        "key_rmse_improves_on_control": key_rmse < float(gates["control_signed_key_mass_rmse"]),
        "candidate_spread_calibration_slope": slope,
        "candidate_calibration_slope_metric": slope_metric,
        "control_calibration_slope_metric": float(gates["control_calibration_slope_metric"]),
        "slope_improves_on_control": slope_metric is not None and slope_metric < float(gates["control_calibration_slope_metric"]),
        "slope_gate_detail": slope_gate,
    }
    structural["pass"] = (structural["per_key_tolerance_pass"] and structural["key_rmse_improves_on_control"]
                          and structural["slope_improves_on_control"])
    overall = structural["pass"] and all(p["pass"] for p in predictive.values())
    return {
        "schema": RESULT_SCHEMA,
        "candidate_family": contract["candidate_family"],
        "verdict": "ATTEMPT1_PASS" if overall else "ATTEMPT1_FAIL",
        "structural_gate": structural,
        "predictive_gate": predictive,
        "folds": fold_rows,
        "calibration_evidence": calibration,
        "evaluated_game_count": n_games,
        "parameters": {"min_calibration_fit_seasons": MIN_CALIBRATION_FIT_SEASONS, "calibration_bins": CALIBRATION_BINS,
                       "calibration_min_bin_n": CALIBRATION_MIN_BIN_N,
                       "gate_combination": "STRUCTURAL_AND_SPREAD_AND_TOTAL_CONJUNCTIVE"},
        "game_rows": rows,
        "sportsbook_prices_consumed_in_fit": False,
        "sportsbook_prices_consumed_in_evaluation_only": True,
        "authority": AUTHORITY,
    }
