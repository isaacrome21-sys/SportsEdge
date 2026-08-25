#!/usr/bin/env python3
"""Build hash-bound NFL forward CLV promotion evidence from JSONL logs.

Every decision and close row must carry the same exact production code SHA.
Promotion evidence therefore resets across code changes instead of silently
combining forward CLV from different executable implementations.

Promotion-grade CLV also has two non-negotiable comparability contracts:

* closing no-vig probability for a line market is measured at the original
  decision threshold, even when the market's headline closing line moved;
* a close is from the same sportsbook, after the decision, and still pregame.

Rows that cannot prove those contracts fail closed instead of being counted in
``n``. A game/market/side observation can count only once even if the same model
play was available at multiple books, preventing cross-book sample inflation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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


def _timestamp(value, *, error: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise SystemExit(error)
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise SystemExit(error) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit(error)
    return parsed.astimezone(timezone.utc)


def _book(value, *, error: str) -> str:
    book = str(value or "").strip().lower()
    if not book:
        raise SystemExit(error)
    return book


def _row_key(row: dict, *, book: str) -> tuple[str, str, str, str]:
    game_id = str(row.get("game_id") or "").strip()
    market = str(row.get("market") or "").strip().lower()
    side = str(row.get("side") or "").strip()
    if not game_id or not market or not side:
        raise SystemExit("NFL_CLV_PAIR_IDENTITY_MISSING")
    return game_id, market, side, book


def _validate_forward_pairs(decision_rows: list[dict], close_rows: list[dict]):
    decisions: dict[tuple[str, str, str, str], tuple[dict, datetime, datetime]] = {}
    seen_observations: set[tuple[str, str, str]] = set()
    for number, row in enumerate(decision_rows, 1):
        book = _book(row.get("book"), error=f"NFL_CLV_DECISION_BOOK_MISSING:{number}")
        key = _row_key(row, book=book)
        observation = key[:3]
        if observation in seen_observations:
            raise SystemExit(f"NFL_CLV_DUPLICATE_OBSERVATION:{observation}")
        seen_observations.add(observation)
        if key in decisions:
            raise SystemExit(f"NFL_CLV_DUPLICATE_DECISION:{key}")
        decision_ts = _timestamp(row.get("decision_ts"), error=f"NFL_CLV_DECISION_TS_INVALID:{number}")
        game_start = _timestamp(row.get("game_start_ts"), error=f"NFL_CLV_GAME_START_TS_INVALID:{number}")
        if decision_ts >= game_start:
            raise SystemExit(f"NFL_CLV_DECISION_NOT_PREGAME:{key}")
        decisions[key] = (row, decision_ts, game_start)

    closes: dict[tuple[str, str, str, str], tuple[dict, datetime, datetime]] = {}
    for number, row in enumerate(close_rows, 1):
        book = _book(row.get("book"), error=f"NFL_CLV_CLOSE_BOOK_MISSING:{number}")
        key = _row_key(row, book=book)
        if key in closes:
            raise SystemExit(f"NFL_CLV_DUPLICATE_CLOSE:{key}")
        close_ts = _timestamp(row.get("close_ts"), error=f"NFL_CLV_CLOSE_TS_INVALID:{number}")
        game_start = _timestamp(row.get("game_start_ts"), error=f"NFL_CLV_GAME_START_TS_INVALID:CLOSE:{number}")
        closes[key] = (row, close_ts, game_start)

    decision_identity_without_book = {(g, m, s): book for g, m, s, book in decisions}
    close_identity_without_book = {(g, m, s): book for g, m, s, book in closes}
    for identity, decision_book in decision_identity_without_book.items():
        close_book = close_identity_without_book.get(identity)
        if close_book is not None and close_book != decision_book:
            raise SystemExit(f"NFL_CLV_CLOSE_BOOK_MISMATCH:{identity}:{decision_book}:{close_book}")

    missing = sorted(set(decisions) - set(closes))
    if missing:
        raise SystemExit(f"NFL_CLV_CLOSE_MISSING:{missing[0]}")
    orphan = sorted(set(closes) - set(decisions))
    if orphan:
        raise SystemExit(f"NFL_CLV_ORPHAN_CLOSE:{orphan[0]}")

    for key, (_, decision_ts, decision_start) in decisions.items():
        _, close_ts, close_start = closes[key]
        if close_start != decision_start:
            raise SystemExit(f"NFL_CLV_GAME_START_MISMATCH:{key}")
        if close_ts <= decision_ts:
            raise SystemExit(f"NFL_CLV_CLOSE_NOT_AFTER_DECISION:{key}")
        if close_ts >= decision_start:
            raise SystemExit(f"NFL_CLV_CLOSE_NOT_PREGAME:{key}")

    first_decision = min(value[1] for value in decisions.values())
    last_close = max(value[1] for value in closes.values())
    return decisions, closes, first_decision, last_close


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

    _, _, first_decision, last_close = _validate_forward_pairs(decision_rows, close_rows)

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
        book=str(row["book"]),
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
        "schema_version": 4,
        "sport": "nfl",
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "code_git_sha": git_sha,
        "decision_log_sha256": _sha(args.decisions),
        "close_log_sha256": _sha(args.closes),
        "decision_count": len(decisions),
        "close_count": len(closes),
        "unique_observation_count": len(decisions),
        "first_decision_ts": first_decision.isoformat(),
        "last_close_ts": last_close.isoformat(),
        "clv_probability_reference": "DECISION_THRESHOLD",
        "forward_time_contract": "PREGAME_DECISION_TO_PREGAME_CLOSE",
        "close_book_contract": "SAME_BOOK_AS_DECISION",
        "markets": official,
        "rejected_markets": rejected,
        "promotion_note": (
            "Only OFFICIAL decisions from this exact code SHA populate promotion markets; "
            "line-market closing probabilities are measured at the original decision threshold, "
            "and every close is from the same book after the decision but before game start. "
            "A game/market/side observation counts once across books. Rejected decisions are "
            "reported separately for gate diagnostics."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
