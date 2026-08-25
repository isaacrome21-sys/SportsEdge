#!/usr/bin/env python3
"""Build hash-bound NFL forward CLV promotion evidence from JSONL logs.

Every decision and close row must carry the same exact production code SHA.
Promotion evidence therefore resets across code changes instead of silently
combining forward CLV from different executable implementations.

For spread/total markets, ``closing_novig_prob`` must be measured at the same
threshold as ``line_at_decision``. A moved market close may therefore carry a
separate ``probability_line`` identifying the alternate closing quote used to
measure the original threshold. Incomparable thresholds fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from sportsedge.core.clv.football import CLVClose, CLVDecision, score_clv, summarize_clv
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"NFL_CLV_JSON_INVALID:{path}:{number}") from exc
        if not isinstance(row, dict):
            raise SystemExit(f"NFL_CLV_ROW_NOT_OBJECT:{path}:{number}")
        rows.append(row)
    if not rows:
        raise SystemExit(f"NFL_CLV_LOG_EMPTY:{path}")
    return rows


def _identity(row: dict, *, path: Path, number: int, expected_git_sha: str) -> None:
    if str(row.get("sport") or "").lower() != "nfl":
        raise SystemExit(f"NFL_CLV_SPORT_MISMATCH:{path}:{number}")
    if row.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise SystemExit(f"NFL_CLV_MODEL_ID_MISMATCH:{path}:{number}")
    if row.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise SystemExit(f"NFL_CLV_FEATURE_CONTRACT_MISMATCH:{path}:{number}")
    code_git_sha = str(row.get("code_git_sha") or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(code_git_sha):
        raise SystemExit(f"NFL_CLV_CODE_SHA_INVALID:{path}:{number}")
    if code_git_sha != expected_git_sha:
        raise SystemExit(f"NFL_CLV_CODE_SHA_MISMATCH:{path}:{number}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--closes", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_clv_evidence.json"))
    args = parser.parse_args()

    git_sha = str(args.git_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(git_sha):
        raise SystemExit("NFL_CLV_EXPECTED_CODE_SHA_INVALID")

    decision_rows = _jsonl(args.decisions)
    close_rows = _jsonl(args.closes)
    for i, row in enumerate(decision_rows, 1):
        _identity(row, path=args.decisions, number=i, expected_git_sha=git_sha)
    for i, row in enumerate(close_rows, 1):
        _identity(row, path=args.closes, number=i, expected_git_sha=git_sha)

    decisions = [CLVDecision(
        decision_ts=str(row["decision_ts"]), game_id=str(row["game_id"]), sport="nfl",
        market=str(row["market"]).lower(), side=str(row["side"]), book=str(row["book"]),
        line_at_decision=None if row.get("line_at_decision") is None else float(row["line_at_decision"]),
        price_at_decision=float(row["price_at_decision"]), model_prob=float(row["model_prob"]),
        novig_prob=float(row["novig_prob"]), ev=float(row["ev"]), kelly_frac=float(row["kelly_frac"]),
        stake_units=float(row["stake_units"]), gate_result=str(row["gate_result"]),
    ) for row in decision_rows]
    closes = [CLVClose(
        game_id=str(row["game_id"]), market=str(row["market"]).lower(), side=str(row["side"]),
        closing_line=None if row.get("closing_line") is None else float(row["closing_line"]),
        closing_price=float(row["closing_price"]), closing_novig_prob=float(row["closing_novig_prob"]),
        probability_line=None if row.get("probability_line") is None else float(row["probability_line"]),
    ) for row in close_rows]

    summaries = summarize_clv(score_clv(decisions, closes))
    official: dict[str, dict] = {}
    rejected: dict[str, dict] = {}
    for (sport, market, bucket), summary in sorted(summaries.items()):
        if sport != "nfl":
            raise SystemExit("NFL_CLV_INTERNAL_SPORT_MISMATCH")
        row = {
            "logged_plays": summary.n,
            "mean_clv": summary.mean_clv,
            "beat_close_rate": summary.beat_close_rate,
            "clv_t_stat": summary.t_stat,
        }
        (official if bucket == "OFFICIAL" else rejected)[market] = row

    payload = {
        "schema_version": 3,
        "sport": "nfl",
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "code_git_sha": git_sha,
        "decision_log_sha256": _sha(args.decisions),
        "close_log_sha256": _sha(args.closes),
        "decision_count": len(decisions),
        "close_count": len(closes),
        "clv_probability_reference": "DECISION_THRESHOLD",
        "markets": official,
        "rejected_markets": rejected,
        "promotion_note": (
            "Only OFFICIAL decisions from this exact code SHA populate promotion markets; "
            "line-market closing probabilities must be measured at the original decision threshold. "
            "Rejected decisions are reported separately for gate diagnostics."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
