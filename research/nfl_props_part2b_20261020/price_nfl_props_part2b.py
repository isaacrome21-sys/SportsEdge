"""NFL props Part 2B — forward-test pricing runner (PREREG_NFL_PROPS_PART2B_FORWARD_V1.md).

Wires the Part 2B construction (eval_nfl_props_part2b_v1.py — the Part 1
construction extended to the 2B counting markets, imported unchanged;
this module reimplements none of it) to live paired DraftKings captures
and emits the committed per-row records the Part 2B preregistration
requires. Mirrors price_nfl_props_part2.py; differences are only:
  * the evaluator / preregistration pins (2B package SPEC_HASHES.txt);
  * a fail-closed scope guard: any market outside the 2B evaluator's
    MARKETS — including INTERCEPTIONS, which is OUT under 2B §1 — is
    refused with MARKET_OUT_OF_SCOPE_2B, never priced;
  * PASS_TDS rows are SHADOW: priced and recorded like any row, labeled
    "SHADOW" in every output, and excluded by the scorer from every
    verdict, sample threshold, and gate (§1/§4);
  * priced PASS_ATTEMPTS / COMPLETIONS rows carry the §3 busiest-QB
    warning as an annotation field (no adjustment).

Usage:
  python3 price_nfl_props_part2b.py price --player-data DIR --capture FILE --out-dir DIR
  python3 price_nfl_props_part2b.py attach-close --run-dir DIR --close-capture FILE

Capture JSON contract (entry and close captures share the shape):
  {"season": 2026, "week": 8, "rows": [
      {"game_id": "...", "player_id": "<nflverse id>", "player_name": "...",
       "market": "RUSH_ATTEMPTS|PASS_ATTEMPTS|COMPLETIONS|PASS_TDS",
       "line": 33.5,
       "over_price": -112, "under_price": -108,
       "captured_at": "<ISO-8601 with offset>", "kickoff": "<ISO-8601 with offset>"}]}

Player data DIR: nflverse weekly player stats in the evaluator's own input
format (ps_*.csv.gz / sp_*.csv.gz). The hash-pinned 2018-2019 training files
(SPEC_HASHES.txt) must be present and matching — the per-market CVs are
computed from them, exactly as the evaluator computes them. The
runner refuses to price if the evaluator file or the training inputs do not
match their pins.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EVALUATOR_NAME = "eval_nfl_props_part2b_v1.py"
EVALUATOR_SHA256 = "a941164e10a66dd079daaed1593387987035a59a92a8b15d94d0366fa3e82417"
PREREG_NAME = "PREREG_NFL_PROPS_PART2B_FORWARD_V1.md"
# §4.5: a close older than this before kickoff is CLOSE_STALE (CLV_MISSING).
CLOSE_MAX_AGE_MINUTES = 60
CALIBRATION_PREREG_NAME = "PREREG_NFL_PROPS_PART2B_FORWARD_V1.md"
CV_SOURCE = "POOLED"  # 2B prereg §1/§5 (Part 2 rule carried forward): one pooled constant per market
QB_VOLUME_MARKETS = ("PASS_ATTEMPTS", "COMPLETIONS")
QB_VOLUME_WARNING = ("PREREG_2B_S3_BUSIEST_QB: construction runs HIGH for "
                     "high-volume QBs on pass attempts / completions "
                     "(annotation only — no adjustment)")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_evaluator():
    """Import the pinned evaluator module by path, after verifying its hash."""
    path = HERE / EVALUATOR_NAME
    digest = sha256_bytes(path.read_bytes())
    if digest != EVALUATOR_SHA256:
        raise SystemExit(f"EVALUATOR_HASH_MISMATCH: {digest} != pinned {EVALUATOR_SHA256}")
    spec = importlib.util.spec_from_file_location("nfl_props_part2b_evaluator", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_training_pins(data: Path) -> dict:
    """Verify the calibration prereg + 2018-2019 training inputs against
    SPEC_HASHES.txt (fail closed)."""
    want = {}
    for line in (HERE / "SPEC_HASHES.txt").read_text().splitlines():
        h, name = line.split()
        want[name] = h
    cal = sha256_bytes((HERE / CALIBRATION_PREREG_NAME).read_bytes())
    if cal != want[CALIBRATION_PREREG_NAME]:
        raise SystemExit("CALIBRATION_PREREG_HASH_MISMATCH")
    # B8 takes effect only when its corrected artifact is in the registry.
    # The frozen loader globs both ps_* and sp_*; checking a hash alone
    # cannot prevent a second 2025 file from being loaded alongside it.
    corrected = "sp_2025_played_v2.csv.gz"
    if corrected in want:
        active_2025 = sorted(
            p.name for pattern in ("ps_2025*.csv.gz", "sp_2025*.csv.gz")
            for p in data.glob(pattern)
        )
        if active_2025 != [corrected]:
            raise SystemExit("B8_DATA_COMPOSITION_INVALID: " + repr(active_2025))
        if sha256_bytes((data / corrected).read_bytes()) != want[corrected]:
            raise SystemExit("B8_CORRECTED_INPUT_HASH_MISMATCH")
    pins = {}
    for name in ("ps_2018.csv.gz", "ps_2019.csv.gz"):
        f = data / name
        if not f.exists():
            raise SystemExit(f"TRAINING_INPUT_MISSING: {name}")
        got = sha256_bytes(f.read_bytes())
        if got != want[name]:
            raise SystemExit(f"TRAINING_INPUT_HASH_MISMATCH: {name}")
        pins[name] = got
    return pins


def train_cv(ev, data_by_season: dict, cfg: dict) -> float:
    """Per-market pooled CV from the training seasons — the evaluator's own
    arithmetic (the training block of evaluate() in the Part 1 evaluator),
    factored out, not re-derived."""
    seasons = ev.build(data_by_season, cfg)
    ratios = []
    for s in ev.TRAIN:
        for w, _, prior, y in seasons.get(s, []):
            pool = ev.league_pool(seasons, s, w)
            if not pool:
                continue
            ratios.append(y / max(ev.mu_for(prior, pool), 1e-6))
    ratios = np.asarray(ratios)
    return float(ratios.std() / ratios.mean())


def american_to_decimal(price: float) -> float:
    price = float(price)
    if price > 0:
        return 1.0 + price / 100.0
    if price < 0:
        return 1.0 + 100.0 / abs(price)
    raise ValueError("american price of 0 is not a price")


def devig_pair(over_price: float, under_price: float) -> tuple[float, float]:
    """Multiplicative de-vig of a paired two-sided quote -> (p_over, p_under)."""
    qo = 1.0 / american_to_decimal(over_price)
    qu = 1.0 / american_to_decimal(under_price)
    tot = qo + qu
    return qo / tot, qu / tot


def fair_american(p: float) -> float | None:
    """Fair American odds for probability p (None at the degenerate edges)."""
    if p <= 0.0 or p >= 1.0:
        return None
    if p >= 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def p_over_for(ev, mu: float, cv: float, count: bool, line: float, grid) -> float:
    """Model P(stat > line) from the evaluator's candidate CDF.
    Yards: 1 - CDF interpolated at the line (the evaluator's own rule).
    Counts: 1 - CDF at floor(line) (P(Y > line) for a discrete stat)."""
    cdf = ev.candidate_cdf(mu, cv, count, grid)
    if count:
        return 1.0 - float(cdf[int(math.floor(line)) - ev.GRID_LO])
    return 1.0 - float(np.interp(line, grid, cdf))


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def player_priors(data_by_season: dict, season: int, week: int, pid: str):
    """Point-in-time priors: the player's games in `season` with week < `week`,
    as [(week, position, row)] sorted by week (evaluator.load's shape)."""
    games = data_by_season.get(season, {}).get(pid, [])
    return [g for g in games if g[0] < week]


def qualification(ev, cfg: dict, priors: list) -> tuple[bool, str]:
    """The construction's own role filter (evaluator.qualified_rows), applied
    to the priors available at pricing time."""
    if len(priors) < 3:
        return False, f"ONLY_{len(priors)}_PRIOR_GAMES"
    if cfg["qb"] and priors[-1][1] != "QB":
        return False, "NOT_QB"
    role_mean = float(np.mean([g[2][cfg["role"]] for g in priors]))
    if role_mean < cfg["thr"]:
        return False, f"ROLE_MEAN_{role_mean:.2f}_BELOW_{cfg['thr']}"
    return True, "QUALIFIED"


def price_rows(ev, data_by_season: dict, capture: dict, cvs: dict) -> tuple[list, dict]:
    season, week = int(capture["season"]), int(capture["week"])
    grid = np.arange(ev.GRID_LO, ev.GRID_HI + 1, dtype=float)
    built: dict = {}
    pools: dict = {}
    rows: list = []
    for raw in capture["rows"]:
        market = raw["market"]
        if market not in ev.MARKETS:
            # 2B §1: INTERCEPTIONS is OUT entirely; anything else is not a
            # 2B market. Fail closed — never price an out-of-scope market.
            raise SystemExit(f"MARKET_OUT_OF_SCOPE_2B: {market}")
        cfg = ev.MARKETS[market]
        if market not in built:
            built[market] = ev.build(data_by_season, cfg)
            pools[market] = [float(y) for y in ev.league_pool(built[market], season, week)]
        pid = raw["player_id"]
        row = {
            "row_id": f"{raw['game_id']}|{pid}|{market}|{float(raw['line'])}",
            "game_id": raw["game_id"], "player_id": pid,
            "player_name": raw.get("player_name"),
            "market": market, "line": float(raw["line"]),
            "over_price": raw["over_price"], "under_price": raw["under_price"],
            "captured_at": raw["captured_at"], "kickoff": raw["kickoff"],
            "label": "SHADOW" if cfg.get("shadow") else "FORWARD_TEST",
            "close_status": "AWAITING_CLOSE",
            "close_over_price": None, "close_under_price": None,
            "close_captured_at": None, "close_novig_p_over": None,
            "close_novig_p_under": None,
        }
        if _parse_ts(raw["captured_at"]) >= _parse_ts(raw["kickoff"]):
            row.update(status="EXCLUDED_LATE_CAPTURE",
                       reason="CAPTURED_AT_OR_AFTER_KICKOFF")
            rows.append(row)
            continue
        priors = player_priors(data_by_season, season, week, pid)
        ok, why = qualification(ev, cfg, priors)
        if not ok:
            row.update(status="NOT_QUALIFIED", reason=why,
                       games_logged=len(priors))
            rows.append(row)
            continue
        prior_values = [float(g[2][cfg["stat"]]) for g in priors]
        pool = pools[market]
        if not pool:
            row.update(status="NOT_PRICED", reason="EMPTY_LEAGUE_POOL",
                       games_logged=len(priors))
            rows.append(row)
            continue
        mu = float(ev.mu_for(prior_values, pool))
        cv = float(cvs[market])
        p_over = float(p_over_for(ev, mu, cv, cfg["count"], row["line"], grid))
        p_under = 1.0 - p_over
        ev_over = p_over * american_to_decimal(raw["over_price"]) - 1.0
        ev_under = p_under * american_to_decimal(raw["under_price"]) - 1.0
        nv_over, nv_under = devig_pair(raw["over_price"], raw["under_price"])
        if abs(ev_over - ev_under) < 1e-12:
            selected = "TIE"
        else:
            selected = "OVER" if ev_over > ev_under else "UNDER"
        if market in QB_VOLUME_MARKETS:
            # 2B §3 (binding annotation, not an adjustment): the
            # construction runs HIGH for high-volume QBs on these markets.
            row["warning"] = QB_VOLUME_WARNING
        row.update(
            status="PRICED", reason="QUALIFIED",
            mu=mu, cv=cv, cv_source=CV_SOURCE,
            games_logged=len(priors), shrink_weight=float(ev.K / (len(priors) + ev.K)),
            pool_mean=float(np.mean(pool)), prior_values=prior_values,
            p_over=p_over, p_under=p_under,
            fair_over_american=fair_american(p_over),
            fair_under_american=fair_american(p_under),
            ev_over=float(ev_over), ev_under=float(ev_under),
            selected_side=selected,
            entry_novig_p_over=float(nv_over), entry_novig_p_under=float(nv_under),
        )
        rows.append(row)
    return rows, pools


def write_create_only(path: Path, payload) -> None:
    if path.exists():
        raise SystemExit(f"REFUSING_TO_OVERWRITE_COMMITTED_RECORD: {path}")
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


def cmd_price(args) -> int:
    ev = load_evaluator()
    data_dir = Path(args.player_data)
    pins = check_training_pins(data_dir)
    data_by_season = ev.load(data_dir)
    capture = json.loads(Path(args.capture).read_text())
    season = int(capture["season"])
    season_files = sorted(data_dir.glob(f"ps_{season}.csv.gz")) + sorted(data_dir.glob(f"sp_{season}.csv.gz"))
    if not season_files:
        raise SystemExit(f"SEASON_DATA_MISSING: no ps_{season}/sp_{season} file in {data_dir}")
    cvs = {m: train_cv(ev, data_by_season, cfg) for m, cfg in ev.MARKETS.items()}
    rows, pools = price_rows(ev, data_by_season, capture, cvs)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run = {
        "label": "NFL PROPS PART 2B FORWARD TEST — prospective record (frozen prereg)",
        "prereg": PREREG_NAME,
        "prereg_sha256": sha256_bytes((HERE / PREREG_NAME).read_bytes()),
        "evaluator": EVALUATOR_NAME, "evaluator_sha256": EVALUATOR_SHA256,
        "training_input_sha256": pins,
        "season_data_sha256": {f.name: sha256_bytes(f.read_bytes()) for f in season_files},
        "capture_sha256": sha256_bytes(Path(args.capture).read_bytes()),
        "season": season, "week": int(capture["week"]),
        "K": ev.K, "cv_by_market": cvs, "cv_source_by_market": {m: CV_SOURCE for m in ev.MARKETS},
        "grid": {"lo": ev.GRID_LO, "hi": ev.GRID_HI},
        "n_rows": len(rows),
        "n_priced": sum(1 for r in rows if r["status"] == "PRICED"),
        "n_shadow_priced": sum(1 for r in rows
                               if r["status"] == "PRICED" and r.get("label") == "SHADOW"),
    }
    write_create_only(out_dir / "run_record.json", run)
    write_create_only(out_dir / "pools.json", pools)
    write_create_only(out_dir / "priced_rows.json", {"run": run, "rows": rows})
    print(json.dumps({"run_record": str(out_dir / "run_record.json"),
                      "n_rows": run["n_rows"], "n_priced": run["n_priced"],
                      "cv_by_market": cvs}, indent=1))
    return 0


def attach_close(run_dir: Path, close_capture_path: Path) -> dict:
    """Attach the final pre-kickoff capture's prices to a priced run.
    Frozen rule (§4.5): a row whose two-sided close is not readable in the
    close capture is CLV_MISSING, with exactly one reason:
      NO_CLOSE_ROW        - nothing for that player/market in the close capture
      LINE_MOVED          - the market closed at a different line than entry
      CLOSE_SINGLE_SIDED  - the entry line is present but one side is missing
      CLOSE_NOT_PREKICKOFF - the close is timestamped at/after kickoff
      CLOSE_STALE         - the close is more than CLOSE_MAX_AGE_MINUTES
                            before kickoff
    Closes are never taken from any other time, line, or source."""
    rows_path = run_dir / "priced_rows.json"
    payload = json.loads(rows_path.read_text())
    close = json.loads(close_capture_path.read_text())
    by_key = {}
    markets_seen = set()
    for raw in close["rows"]:
        key = (raw["game_id"], raw["player_id"], raw["market"], float(raw["line"]))
        by_key[key] = raw
        markets_seen.add((raw["game_id"], raw["player_id"], raw["market"]))
    summary = {"readable": 0, "clv_missing": 0}
    for row in payload["rows"]:
        if row["status"] != "PRICED":
            continue
        key = (row["game_id"], row["player_id"], row["market"], row["line"])
        raw = by_key.get(key)
        kickoff = _parse_ts(row["kickoff"])
        reason = None
        if raw is None:
            reason = ("LINE_MOVED" if (row["game_id"], row["player_id"], row["market"]) in markets_seen
                      else "NO_CLOSE_ROW")
        elif raw.get("over_price") is None or raw.get("under_price") is None:
            reason = "CLOSE_SINGLE_SIDED"
        else:
            captured = _parse_ts(raw["captured_at"])
            if captured >= kickoff:
                reason = "CLOSE_NOT_PREKICKOFF"
            elif (kickoff - captured).total_seconds() > CLOSE_MAX_AGE_MINUTES * 60:
                reason = "CLOSE_STALE"
        readable = reason is None
        if readable:
            nv_over, nv_under = devig_pair(raw["over_price"], raw["under_price"])
            row.update(close_status="READABLE",
                       close_over_price=raw["over_price"],
                       close_under_price=raw["under_price"],
                       close_captured_at=raw["captured_at"],
                       close_novig_p_over=float(nv_over),
                       close_novig_p_under=float(nv_under),
                       clv_missing_reason=None)
            summary["readable"] += 1
        else:
            row.update(close_status="CLV_MISSING", clv_missing_reason=reason)
            summary["clv_missing"] += 1
    payload["close_attach"] = {
        "close_capture_sha256": sha256_bytes(close_capture_path.read_bytes()),
        **summary,
    }
    rows_path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    write_create_only(run_dir / "close_attach_record.json", payload["close_attach"])
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("price")
    p.add_argument("--player-data", required=True)
    p.add_argument("--capture", required=True)
    p.add_argument("--out-dir", required=True)
    c = sub.add_parser("attach-close")
    c.add_argument("--run-dir", required=True)
    c.add_argument("--close-capture", required=True)
    args = ap.parse_args()
    if args.cmd == "price":
        return cmd_price(args)
    summary = attach_close(Path(args.run_dir), Path(args.close_capture))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
