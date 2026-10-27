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


def check_b8_active_runtime(data: Path, evaluator) -> dict:
    """Require a single corrected 2025 input in the active pricing directory.

    This runs before evaluator.load: a legacy 2025 file alongside B8 would
    otherwise be silently double-loaded by the evaluator's sp_* glob.
    """
    if (data / "sp_2025.csv.gz").exists():
        raise SystemExit("B8_RUNTIME_LEGACY_2025_FILE_FORBIDDEN")
    season_files = sorted(
        path.name
        for pattern in ("ps_2025*.csv.gz", "sp_2025*.csv.gz")
        for path in data.glob(pattern)
    )
    if season_files != ["sp_2025_played_v2.csv.gz"]:
        raise SystemExit("B8_RUNTIME_CORRECTED_2025_FILE_SET_REQUIRED")
    return evaluator.check_hashes(data)


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
        # Clamp the index into the grid (capture-contract repair B2): a
        # below-grid count line must not wrap the array via a negative
        # index. The clamp is exact, not approximate — count outcomes are
        # >= 0, so CDF(GRID_LO) = CDF(-60) = 0 and a line below the grid
        # prices at p_over = 1.0, its true value. Above-grid lines are
        # refused per-row (LINE_ABOVE_GRID) before ever reaching here;
        # the upper clamp is defense-in-depth only.
        idx = min(max(int(math.floor(line)) - ev.GRID_LO, 0), len(cdf) - 1)
        return 1.0 - float(cdf[idx])
    return 1.0 - float(np.interp(line, grid, cdf))


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# --- capture-contract repair (B1/B3/B5-B7, E2): per-row fault isolation ---
# A malformed capture row is emitted as a REFUSED row (status="REFUSED",
# verbatim reason code, row_id preserved) and the rest of the slate still
# prices and commits. Slate-level failures (hash pins, missing data files,
# and this package's fail-closed MARKET_OUT_OF_SCOPE_2B guard) still fail
# closed exactly as before.
#
# --- owner acceptance repair (PR #2759 review): fault-class separation ---
# Per-row isolation covers malformed CAPTURE INPUT only, and every such
# fault is an explicit deterministic check: _validate_capture_row below
# plus the named in-body refusals (LINE_ABOVE_GRID,
# NON_FINITE_STAT_INPUT). Model/config/build failures — anything raised
# by the evaluator (ev.build, ev.league_pool, mu_for, candidate_cdf), by
# qualification over the season data, or by an incompatible
# season/training data schema — are NOT capture faults: they propagate
# out of price_rows and abort the run before cmd_price writes any
# record, so a systemic failure can never commit as a completed run of
# REFUSED rows. The MARKET_OUT_OF_SCOPE_2B SystemExit guard is unchanged:
# a BaseException, it never was and still is not caught per-row.
REQUIRED_ROW_FIELDS = ("game_id", "player_id", "market", "line",
                       "over_price", "under_price", "captured_at", "kickoff")


def _as_finite_float(value) -> float | None:
    """float(value) if it is a real, finite number, else None.
    Booleans and non-numeric values are not numbers for this contract."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _row_id_for(raw: dict) -> str:
    """The canonical row_id when the row is well-formed enough to build
    one; otherwise a deterministic id from the raw fields, so a REFUSED
    row still carries the identity of the capture row it came from."""
    line = _as_finite_float(raw.get("line"))
    if line is not None and raw.get("game_id") is not None \
            and raw.get("player_id") is not None and raw.get("market") is not None:
        return f"{raw['game_id']}|{raw['player_id']}|{raw['market']}|{line}"
    return f"{raw.get('game_id')}|{raw.get('player_id')}|{raw.get('market')}|{raw.get('line')}"


def _refused_row(ev, raw: dict, reason: str) -> dict:
    """A REFUSED row in the committed record's shape (scorers skip any
    status != PRICED). Non-finite line/prices are recorded as None — the
    verbatim offending value is named by the reason code, and no NaN/Inf
    is ever serialized into a committed record."""
    line = _as_finite_float(raw.get("line"))
    market = raw.get("market")
    # A non-string market is refused as INVALID_MARKET by validation;
    # never let it reach the MARKETS lookup here (an unhashable value
    # would raise inside the refusal path itself).
    cfg = (ev.MARKETS.get(market) or {}) if isinstance(market, str) else {}
    return {
        "row_id": _row_id_for(raw),
        "game_id": raw.get("game_id"), "player_id": raw.get("player_id"),
        "player_name": raw.get("player_name"),
        "market": raw.get("market"), "line": line,
        "over_price": _as_finite_float(raw.get("over_price")),
        "under_price": _as_finite_float(raw.get("under_price")),
        "captured_at": raw.get("captured_at"), "kickoff": raw.get("kickoff"),
        "status": "REFUSED", "reason": reason,
        "label": "SHADOW" if cfg.get("shadow") else "FORWARD_TEST",
        "close_status": "AWAITING_CLOSE",
        "close_over_price": None, "close_under_price": None,
        "close_captured_at": None, "close_novig_p_over": None,
        "close_novig_p_under": None,
    }


def _validate_capture_row(raw) -> str | None:
    """Static per-row contract checks that need no market config.
    Returns a verbatim refusal reason, or None if the row may proceed."""
    if not isinstance(raw, dict):
        return "ROW_NOT_AN_OBJECT"
    for field in REQUIRED_ROW_FIELDS:
        if field not in raw or raw[field] is None:
            return f"MISSING_FIELD_{field.upper()}"
    if _as_finite_float(raw["line"]) is None:
        return "NON_FINITE_LINE" if isinstance(raw["line"], float) else "INVALID_LINE"
    for field in ("over_price", "under_price"):
        price = _as_finite_float(raw[field])
        if price is None:
            return f"NON_FINITE_PRICE_{field.upper()}"
        if price == 0:
            return f"ZERO_PRICE_{field.upper()}"
    for field in ("captured_at", "kickoff"):
        try:
            ts = _parse_ts(raw[field])
        except (TypeError, ValueError, AttributeError):
            return f"INVALID_TIMESTAMP_{field.upper()}"
        if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
            # Never silently assume a timezone for a naive timestamp.
            return f"NAIVE_TIMESTAMP_{field.upper()}"
    # Type contract for the two fields the pricing body uses as dict
    # keys/members (market scope, player lookup): a non-string value is
    # malformed capture input, refused here deterministically instead of
    # surfacing as a TypeError deep inside the pricing body. Checked last
    # so every pre-existing refusal above keeps its exact precedence.
    if not isinstance(raw["market"], str):
        return "INVALID_MARKET"
    if not isinstance(raw["player_id"], str):
        return "INVALID_PLAYER_ID"
    return None


def _row_values_finite(value) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_row_values_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_row_values_finite(v) for v in value)
    return True


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


def _price_one_row(ev, data_by_season: dict, season: int, week: int,
                   raw: dict, cvs: dict, grid, built: dict, pools: dict) -> dict:
    """Price a single capture row (the original per-row body, unchanged
    for well-formed rows). Contract refusals return a REFUSED row. Any
    other exception — an evaluator/model/build failure or a season data
    schema failure — propagates to the caller and aborts the run; it is
    never converted into a per-row refusal. The 2B scope guard below
    still raises SystemExit — that fail-closed slate-level behavior is
    this package's frozen design, asserted by its test suite."""
    market = raw["market"]
    if market not in ev.MARKETS:
        # 2B §1: INTERCEPTIONS is OUT entirely; anything else is not a
        # 2B market. Fail closed — never price an out-of-scope market.
        raise SystemExit(f"MARKET_OUT_OF_SCOPE_2B: {market}")
    cfg = ev.MARKETS[market]
    line = float(raw["line"])
    if cfg["count"] and int(math.floor(line)) > ev.GRID_HI:
        return _refused_row(ev, raw, "LINE_ABOVE_GRID")
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
        return row
    priors = player_priors(data_by_season, season, week, pid)
    if any(not math.isfinite(float(g[2][cfg["stat"]]))
           or not math.isfinite(float(g[2][cfg["role"]])) for g in priors):
        return _refused_row(ev, raw, "NON_FINITE_STAT_INPUT")
    ok, why = qualification(ev, cfg, priors)
    if not ok:
        row.update(status="NOT_QUALIFIED", reason=why,
                   games_logged=len(priors))
        return row
    prior_values = [float(g[2][cfg["stat"]]) for g in priors]
    pool = pools[market]
    if not pool:
        row.update(status="NOT_PRICED", reason="EMPTY_LEAGUE_POOL",
                   games_logged=len(priors))
        return row
    if any(not math.isfinite(float(y)) for y in pool):
        return _refused_row(ev, raw, "NON_FINITE_STAT_INPUT")
    mu = float(ev.mu_for(prior_values, pool))
    cv = float(cvs[market])
    if not (math.isfinite(mu) and math.isfinite(cv)):
        return _refused_row(ev, raw, "NON_FINITE_STAT_INPUT")
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
    return row


def price_rows(ev, data_by_season: dict, capture: dict, cvs: dict) -> tuple[list, dict]:
    season, week = int(capture["season"]), int(capture["week"])
    grid = np.arange(ev.GRID_LO, ev.GRID_HI + 1, dtype=float)
    built: dict = {}
    pools: dict = {}
    rows: list = []
    seen_row_ids: set = set()
    for raw in capture["rows"]:
        if isinstance(raw, dict):
            # E2: an identical row_id priced twice double-counts
            # downstream. Keep the first, refuse subsequent duplicates.
            row_id = _row_id_for(raw)
            if row_id in seen_row_ids:
                rows.append(_refused_row(ev, raw, "DUPLICATE_ROW"))
                continue
            seen_row_ids.add(row_id)
        reason = _validate_capture_row(raw)
        if reason is not None:
            rows.append(_refused_row(ev, raw, reason) if isinstance(raw, dict)
                        else _refused_row(ev, {}, reason))
            continue
        # No catch-all here (owner acceptance repair, PR #2759):
        # malformed capture input is fully handled by the explicit
        # checks above and the named refusals inside _price_one_row, so
        # anything that raises past this point is a model/config/build
        # failure. Let it propagate and abort the run — cmd_price writes
        # its records only after this loop returns, so an abort commits
        # nothing. (The scope guard's SystemExit propagates exactly as
        # before.)
        rows.append(_price_one_row(ev, data_by_season, season, week,
                                   raw, cvs, grid, built, pools))
    # Final output assertion (B6): no committed PRICED row may contain
    # NaN/Inf anywhere. Any offender is downgraded to REFUSED, never
    # committed as PRICED, and the assertion then verifies the invariant.
    for row in rows:
        if row.get("status") == "PRICED" and not _row_values_finite(row):
            refused = _refused_row(ev, row, "NON_FINITE_OUTPUT")
            row.clear()
            row.update(refused)
    assert all(_row_values_finite(r) for r in rows if r.get("status") == "PRICED")
    return rows, pools


def write_create_only(path: Path, payload) -> None:
    if path.exists():
        raise SystemExit(f"REFUSING_TO_OVERWRITE_COMMITTED_RECORD: {path}")
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


def cmd_price(args) -> int:
    ev = load_evaluator()
    data_dir = Path(args.player_data)
    pins = check_training_pins(data_dir)
    check_b8_active_runtime(data_dir, ev)
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
