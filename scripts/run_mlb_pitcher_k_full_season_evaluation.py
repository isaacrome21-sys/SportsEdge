#!/usr/bin/env python3
"""Consume the frozen full-season MLB pitcher-K candidate test exactly once."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.mlb_pitcher_k_probability_evaluator import evaluate_pitcher_k_candidate

ROWS_SCHEMA = "MLB_PITCHER_K_HISTORICAL_EVALUATION_ROWS_V1"
OUTPUT_SCHEMA = "MLB_PITCHER_K_FULL_SEASON_EVALUATION_V1"
FROZEN_SEASONS = [2023, 2024, 2025]
MIN_TEST_STARTS = 500


class PitcherKFullSeasonEvalError(ValueError):
    pass


def _canonical_sha(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load_rows(path: Path) -> tuple[dict[str, Any], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != ROWS_SCHEMA:
        raise PitcherKFullSeasonEvalError("unexpected materialized rows schema")
    if payload.get("seasons") != FROZEN_SEASONS:
        raise PitcherKFullSeasonEvalError("materialized rows must contain frozen 2023-2025 seasons")
    if payload.get("historical_reconstruction") is not True or payload.get("backfill") is not True:
        raise PitcherKFullSeasonEvalError("historical reconstruction identity required")
    if payload.get("forward_evidence_eligible") is not False:
        raise PitcherKFullSeasonEvalError("historical rows cannot be forward evidence")
    if payload.get("promotion_authority") is not False:
        raise PitcherKFullSeasonEvalError("historical rows cannot grant promotion authority")
    authority = payload.get("authority") or {}
    if any(bool(authority.get(k)) for k in ("model_p","truth_gate","promotion","staking","official","bettor_facing_release")):
        raise PitcherKFullSeasonEvalError("materialized rows carry forbidden authority")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise PitcherKFullSeasonEvalError("materialized rows missing")
    if int(payload.get("row_count") or -1) != len(rows):
        raise PitcherKFullSeasonEvalError("materialized row_count mismatch")
    seen = set()
    counts = {2023: 0, 2024: 0, 2025: 0}
    for row in rows:
        if not isinstance(row, Mapping):
            raise PitcherKFullSeasonEvalError("materialized row must be object")
        season = int(row.get("season") or 0)
        if season not in counts:
            raise PitcherKFullSeasonEvalError("row season outside frozen split")
        if row.get("historical_reconstruction") is not True or row.get("forward_evidence_eligible") is not False:
            raise PitcherKFullSeasonEvalError("row historical authority identity invalid")
        if row.get("promotion_authority") is not False:
            raise PitcherKFullSeasonEvalError("row cannot grant promotion authority")
        key = (season, str(row.get("target_date")), int(row.get("game_id")), str(row.get("pitcher_id")))
        if key in seen:
            raise PitcherKFullSeasonEvalError("duplicate evaluation row")
        seen.add(key)
        counts[season] += 1
    if any(counts[y] <= 0 for y in (2023, 2024, 2025)):
        raise PitcherKFullSeasonEvalError("every frozen season requires eligible rows")
    if counts[2025] < MIN_TEST_STARTS:
        raise PitcherKFullSeasonEvalError(
            f"candidate test requires at least {MIN_TEST_STARTS} eligible 2025 starts"
        )
    return payload, _canonical_sha(payload)


def run(rows_path: Path, *, out_dir: Path, consume_candidate_test: bool) -> dict[str, Any]:
    if not consume_candidate_test:
        raise PitcherKFullSeasonEvalError("explicit --consume-candidate-test required")
    materialized, rows_sha = load_rows(rows_path)
    evaluation = evaluate_pitcher_k_candidate(materialized["rows"])
    payload = {
        "schema": OUTPUT_SCHEMA,
        "rows_sha256": rows_sha,
        "candidate_test_consumed": True,
        "historical_reconstruction": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
        "authority": {
            "model_p": False, "truth_gate": False, "promotion": False,
            "staking": False, "official": False, "bettor_facing_release": False,
        },
        "season_receipts": materialized.get("season_receipts") or [],
        "evaluation": evaluation,
    }
    payload["report_sha256"] = _canonical_sha(payload)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evaluation.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    ev = evaluation
    m = ev["metrics"]
    ci = m["candidate_minus_incumbent_rps_ci"]
    report = "\n".join([
        "## MLB pitcher-K full-season historical candidate evaluation v1",
        "",
        f"Rows artifact SHA-256: \`{rows_sha}\`.",
        f"Rows: 2023={ev['split']['training_rows']}, 2024={ev['split']['validation_rows']}, 2025={ev['split']['candidate_test_rows']}.",
        "",
        f"Candidate mean RPS: **{m['candidate_mean_rps']:.6f}**; incumbent: **{m['incumbent_mean_rps']:.6f}**.",
        f"Candidate-incumbent RPS: **{ci['value']:.6f}**, 95% CI [{ci['lo']:.6f}, {ci['hi']:.6f}].",
        f"Typical-line log loss: candidate **{m['candidate_typical_line_log_loss']:.6f}**, incumbent **{m['incumbent_typical_line_log_loss']:.6f}**.",
        f"Typical-line ECE: candidate **{m['candidate_typical_line_ece']:.6f}**, incumbent **{m['incumbent_typical_line_ece']:.6f}**.",
        f"Development gate: **{'PASS' if ev['passes_development_gate'] else 'FAIL'}**.",
        ("Blockers: " + "; ".join(ev["blockers"]) + ".") if ev.get("blockers") else "Blockers: none.",
        "",
        "Historical candidate-test readout only. No Model_P, promotion, staking, OFFICIAL, or bettor-facing authority is created.",
        "",
    ])
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_pitcher_k_full_season_eval"))
    parser.add_argument("--consume-candidate-test", action="store_true")
    args = parser.parse_args()
    run(args.rows, out_dir=args.out_dir, consume_candidate_test=args.consume_candidate_test)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
