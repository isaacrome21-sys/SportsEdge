#!/usr/bin/env python3
"""Rehydrate immutable NRFI/YRFI V6 captures, settle outcomes, and score frozen gates.

Prediction artifacts are never modified. This scorer deterministically chooses the
first valid pregame V6 pair per game, attaches MLB first-inning outcomes in a
separate settlement ledger, and recomputes cumulative promotion evidence.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any
from urllib.request import urlopen

EXPECTED_MODEL_SHA = os.getenv(
    "SPORTSEDGE_NRFI_V6_SHA256",
    "0bdf71e272e406611e241e2427904f3c8e3a9405700f440bedacf0b74ed1580e",
)
EXPECTED_FEATURE_SHA = os.getenv(
    "SPORTSEDGE_NRFI_V6_FEATURE_SHA256",
    "f38df78312de2fbcbd64824a1d5c2fb4d5c96b51e758da30e55a001f445fbda2",
)
SHADOW_START = date(2026, 8, 13)
MIN_AGE_DAYS = 14
MIN_GAMES = 200
MIN_COVERAGE = 0.90
MAX_ABS_Z = 2.50
BRIER_TOL = 0.0010
LOGLOSS_TOL = 0.0020
BUCKETS = ((0.0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.0000000001))


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def fetch_first_inning(game_id: str) -> dict[str, Any] | None:
    url = f"https://statsapi.mlb.com/api/v1.1/game/{int(game_id)}/feed/live"
    try:
        with urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    status = (((payload.get("gameData") or {}).get("status") or {}).get("abstractGameState"))
    if status != "Final":
        return None
    innings = (((payload.get("liveData") or {}).get("linescore") or {}).get("innings") or [])
    if not innings:
        return None
    first = innings[0] or {}
    if int(first.get("num") or 0) != 1:
        return None
    teams = first.get("teams") or {}
    try:
        away = int(((teams.get("away") or {}).get("runs")) or 0)
        home = int(((teams.get("home") or {}).get("runs")) or 0)
    except (TypeError, ValueError):
        return None
    return {
        "game_id": str(game_id),
        "away_first_inning_runs": away,
        "home_first_inning_runs": home,
        "yrfi_outcome": int((away + home) > 0),
        "nrfi_outcome": int((away + home) == 0),
        "source": "MLB_STATSAPI_LIVE_FEED",
        "settled_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def calibration_z(ps: list[float], ys: list[int]) -> float | None:
    if not ps:
        return None
    denom = sum(p * (1.0 - p) for p in ps)
    if denom <= 0:
        return None
    return sum(y - p for p, y in zip(ps, ys)) / math.sqrt(denom)


def brier(ps: list[float], ys: list[int]) -> float | None:
    return None if not ps else sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def logloss(ps: list[float], ys: list[int]) -> float | None:
    if not ps:
        return None
    total = 0.0
    for p, y in zip(ps, ys):
        q = min(max(float(p), 1e-12), 1 - 1e-12)
        total += -(y * math.log(q) + (1 - y) * math.log(1 - q))
    return total / len(ps)


def valid_prediction(row: dict[str, Any], violations: list[str]) -> bool:
    try:
        generated = parse_dt(row["generated_at_utc"])
        cutoff = parse_dt(row["cutoff_at_utc"])
    except Exception:
        violations.append(f"BAD_TIME:{row.get('game_id')}:{row.get('market')}")
        return False
    if generated >= cutoff:
        violations.append(f"CHRONOLOGY:{row.get('game_id')}:{row.get('market')}")
        return False
    if row.get("model_artifact_sha256") != EXPECTED_MODEL_SHA:
        violations.append(f"MODEL_SHA:{row.get('game_id')}:{row.get('market')}")
        return False
    if row.get("feature_contract_sha256") != EXPECTED_FEATURE_SHA:
        violations.append(f"FEATURE_SHA:{row.get('game_id')}:{row.get('market')}")
        return False
    if row.get("outcome") is not None or row.get("outcome_attached_at_utc") is not None:
        violations.append(f"MUTATED_PREDICTION:{row.get('game_id')}:{row.get('market')}")
        return False
    market = str(row.get("market") or "").upper()
    if market not in {"NRFI", "YRFI"}:
        return False
    try:
        p = float(row["model_p"])
    except Exception:
        violations.append(f"BAD_MODEL_P:{row.get('game_id')}:{market}")
        return False
    if not 0.0 < p < 1.0:
        violations.append(f"BAD_MODEL_P:{row.get('game_id')}:{market}")
        return False
    return True


def main() -> int:
    input_root = Path(os.getenv("SPORTSEDGE_NRFI_V6_INPUT", "artifacts/forward-shadow-input"))
    out_root = Path(os.getenv("SPORTSEDGE_NRFI_V6_SCORE_OUT", "artifacts/forward-shadow-scored"))
    out_root.mkdir(parents=True, exist_ok=True)

    prediction_files = sorted(input_root.rglob("nrfi_v6_predictions.json"))
    status_files = sorted(input_root.rglob("nrfi_v6_status.json"))
    if not prediction_files:
        raise SystemExit("NRFI_V6_NO_CAPTURE_ARTIFACTS")

    violations: list[str] = []
    by_game_market: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    scheduled_games: set[str] = set()
    sportsbook_claims: list[bool] = []

    for path in prediction_files:
        payload = load_json(path)
        if not isinstance(payload, list):
            violations.append(f"BAD_LEDGER:{path}")
            continue
        for row in payload:
            if not isinstance(row, dict) or not valid_prediction(row, violations):
                continue
            gid = str(row["game_id"])
            market = str(row["market"]).upper()
            scheduled_games.add(gid)
            by_game_market[(gid, market)].append(row)

    for path in status_files:
        try:
            status = load_json(path)
        except Exception:
            violations.append(f"BAD_STATUS:{path}")
            continue
        sportsbook_claims.append(bool(status.get("sportsbook_data_used")))
        for item in status.get("blocked") or []:
            gid = str((item or {}).get("game_id") or "")
            if gid:
                scheduled_games.add(gid)

    if any(sportsbook_claims):
        violations.append("SPORTSBOOK_CONTAMINATION_STATUS_TRUE")

    selected: dict[str, dict[str, dict[str, Any]]] = {}
    for gid in sorted({g for g, _ in by_game_market}):
        markets: dict[str, dict[str, Any]] = {}
        for market in ("YRFI", "NRFI"):
            rows = by_game_market.get((gid, market), [])
            if rows:
                rows.sort(key=lambda r: (parse_dt(r["generated_at_utc"]), str(r.get("row_id") or "")))
                markets[market] = rows[0]
        if set(markets) != {"YRFI", "NRFI"}:
            violations.append(f"PAIR_MISSING:{gid}")
            continue
        if abs(float(markets["YRFI"]["model_p"]) + float(markets["NRFI"]["model_p"]) - 1.0) > 1e-9:
            violations.append(f"COMPLEMENT_MISMATCH:{gid}")
            continue
        selected[gid] = markets

    settlement_path = out_root / "nrfi_v6_settlements.json"
    prior: dict[str, dict[str, Any]] = {}
    if settlement_path.exists():
        try:
            prior = {str(x["game_id"]): x for x in load_json(settlement_path)}
        except Exception:
            prior = {}
    settlements = dict(prior)
    for gid in sorted(selected):
        if gid not in settlements:
            outcome = fetch_first_inning(gid)
            if outcome is not None:
                settlements[gid] = outcome
    settled_rows = [settlements[k] for k in sorted(settlements) if k in selected]
    settlement_path.write_bytes(canonical(settled_rows))

    ps: list[float] = []
    ys: list[int] = []
    v5_ps: list[float] = []
    paired_ps: list[float] = []
    paired_ys: list[int] = []
    game_rows: list[dict[str, Any]] = []
    for gid in sorted(selected):
        outcome = settlements.get(gid)
        if outcome is None:
            continue
        row = selected[gid]["YRFI"]
        p = float(row["model_p"])
        y = int(outcome["yrfi_outcome"])
        ps.append(p); ys.append(y)
        v5 = (row.get("provenance") or {}).get("base_v5_yrfi_p")
        paired = False
        if v5 is not None:
            try:
                q = float(v5)
                if 0.0 < q < 1.0:
                    v5_ps.append(q); paired_ps.append(p); paired_ys.append(y); paired = True
            except Exception:
                pass
        game_rows.append({
            "game_id": gid,
            "generated_at_utc": row["generated_at_utc"],
            "cutoff_at_utc": row["cutoff_at_utc"],
            "v6_yrfi_p": p,
            "v5_yrfi_p": float(v5) if paired else None,
            "yrfi_outcome": y,
            "row_id_yrfi": row.get("row_id"),
            "row_id_nrfi": selected[gid]["NRFI"].get("row_id"),
        })

    bucket_report = []
    bucket_gate = True
    for lo, hi in BUCKETS:
        idx = [i for i, p in enumerate(ps) if lo <= p < hi]
        bps = [ps[i] for i in idx]; bys = [ys[i] for i in idx]
        z = calibration_z(bps, bys)
        applicable = len(idx) >= 75
        passed = (not applicable) or (z is not None and abs(z) <= MAX_ABS_Z)
        bucket_gate = bucket_gate and passed
        bucket_report.append({"range": [lo, min(hi, 1.0)], "n": len(idx), "z": z, "applicable": applicable, "pass": passed})

    z = calibration_z(ps, ys)
    v6_brier = brier(paired_ps, paired_ys)
    v5_brier = brier(v5_ps, paired_ys)
    v6_ll = logloss(paired_ps, paired_ys)
    v5_ll = logloss(v5_ps, paired_ys)
    coverage = (len(selected) / len(scheduled_games)) if scheduled_games else 0.0
    age_days = (datetime.now(timezone.utc).date() - SHADOW_START).days

    gates = {
        "age_days": {"value": age_days, "minimum": MIN_AGE_DAYS, "pass": age_days >= MIN_AGE_DAYS},
        "settled_unique_games": {"value": len(ps), "minimum": MIN_GAMES, "pass": len(ps) >= MIN_GAMES},
        "overall_calibration": {"z": z, "max_abs": MAX_ABS_Z, "pass": z is not None and abs(z) <= MAX_ABS_Z},
        "qualifying_buckets": {"pass": bucket_gate, "buckets": bucket_report},
        "paired_brier": {"v6": v6_brier, "v5": v5_brier, "tolerance": BRIER_TOL, "n": len(paired_ps), "pass": v6_brier is not None and v5_brier is not None and v6_brier <= v5_brier + BRIER_TOL},
        "paired_logloss": {"v6": v6_ll, "v5": v5_ll, "tolerance": LOGLOSS_TOL, "n": len(paired_ps), "pass": v6_ll is not None and v5_ll is not None and v6_ll <= v5_ll + LOGLOSS_TOL},
        "coverage": {"value": coverage, "minimum": MIN_COVERAGE, "predicted_unique_games": len(selected), "observed_scheduled_unique_games": len(scheduled_games), "pass": coverage >= MIN_COVERAGE},
        "integrity": {"violations": sorted(set(violations)), "pass": not violations},
    }
    eligible = all(g["pass"] for g in gates.values())
    report = {
        "schema_version": "nrfi_v6_forward_shadow_evaluation_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_sha256": EXPECTED_MODEL_SHA,
        "feature_contract_sha256": EXPECTED_FEATURE_SHA,
        "prediction_artifact_files": len(prediction_files),
        "status_artifact_files": len(status_files),
        "selected_unique_games": len(selected),
        "settled_unique_games": len(ps),
        "settlement_ledger_sha256": sha256(canonical(settled_rows)),
        "sportsbook_data_used": False,
        "markets": {"NRFI": {"eligible": eligible}, "YRFI": {"eligible": eligible}},
        "gates": gates,
        "game_evidence": game_rows,
        "state": "MODEL_ELIGIBLE" if eligible else "MODEL_NOT_ELIGIBLE",
    }
    report_path = out_root / "nrfi_v6_forward_shadow_report.json"
    report_path.write_bytes(canonical(report))
    manifest = {
        "report_sha256": sha256(report_path.read_bytes()),
        "settlement_sha256": sha256(settlement_path.read_bytes()),
        "candidate_sha256": EXPECTED_MODEL_SHA,
        "eligible": eligible,
        "generated_at_utc": report["generated_at_utc"],
    }
    (out_root / "nrfi_v6_forward_shadow_manifest.json").write_bytes(canonical(manifest))
    print(json.dumps({"state": report["state"], "settled_unique_games": len(ps), "coverage": coverage, "violations": len(set(violations))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
