"""Postgame outcome attachment for immutable SportsEdge MLB decision ledgers.

Settlement is observability only.  It never rewrites the pregame ledger and must
never alter Model_P, wager status, deployment eligibility or sizing.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable, Mapping

from .mlb_source import GameSnapshot, fetch_boxscore, parse_game_start


class MLBDecisionSettlementError(ValueError):
    pass


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MLBDecisionSettlementError("TIMESTAMP_MISSING")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBDecisionSettlementError("TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLBDecisionSettlementError("TIMESTAMP_NOT_AWARE")
    return dt.astimezone(timezone.utc)


def _score_from_boxscore(boxscore: Mapping[str, Any], side: str) -> int:
    try:
        raw = (((boxscore.get("teams") or {}).get(side) or {}).get("teamStats") or {}).get("batting", {}).get("runs")
        score = int(raw)
    except (TypeError, ValueError, AttributeError) as exc:
        raise MLBDecisionSettlementError(f"FINAL_SCORE_MISSING_{side.upper()}") from exc
    if score < 0:
        raise MLBDecisionSettlementError("FINAL_SCORE_NEGATIVE")
    return score


def settle_moneyline_decisions(
    decision_ledger: Mapping[str, Any],
    schedule: list[GameSnapshot],
    *,
    boxscore_fetcher: Callable[[int], Mapping[str, Any]] = fetch_boxscore,
    settled_at: datetime | None = None,
) -> dict[str, Any]:
    """Attach final MLB outcomes to pregame MONEYLINE decisions in a new artifact."""
    if not isinstance(decision_ledger, Mapping):
        raise MLBDecisionSettlementError("LEDGER_NOT_MAPPING")
    decisions = decision_ledger.get("decisions") or []
    if not isinstance(decisions, list):
        raise MLBDecisionSettlementError("DECISIONS_NOT_LIST")
    settled_at = (settled_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    games = {str(g.game_pk): g for g in schedule}
    rows: list[dict[str, Any]] = []
    score_cache: dict[str, tuple[int, int]] = {}

    for raw in decisions:
        if not isinstance(raw, Mapping) or str(raw.get("market") or "").upper() != "MONEYLINE":
            continue
        game_id = str(raw.get("game_id") or "").strip()
        decision_id = str(raw.get("decision_id") or "").strip()
        side = str(raw.get("side") or "").upper().strip()
        if not game_id or not decision_id or side not in {"HOME", "AWAY"}:
            continue
        game = games.get(game_id)
        if game is None:
            continue
        if game.status != "Final":
            continue
        detail = str(game.detailed_status or "").upper()
        if any(x in detail for x in ("SUSPENDED", "POSTPONED", "DELAYED")):
            continue
        generated = _parse_utc(raw.get("generated_at_utc"))
        first_pitch = parse_game_start(game.game_date)
        if generated >= first_pitch:
            continue
        if game_id not in score_cache:
            box = boxscore_fetcher(int(game.game_pk))
            score_cache[game_id] = (_score_from_boxscore(box, "away"), _score_from_boxscore(box, "home"))
        away_score, home_score = score_cache[game_id]
        if away_score == home_score:
            # MLB final games should not tie. Fail closed rather than infer.
            continue
        home_win = home_score > away_score
        outcome_win = home_win if side == "HOME" else not home_win
        rows.append({
            "decision_id": decision_id,
            "wager_key": raw.get("wager_key"),
            "run_id": raw.get("run_id"),
            "slate_date_ct": raw.get("slate_date_ct"),
            "generated_at_utc": raw.get("generated_at_utc"),
            "game_id": game_id,
            "first_pitch_utc": first_pitch.isoformat(),
            "market": "MONEYLINE",
            "side": side,
            "book_key": raw.get("book_key"),
            "american_odds": raw.get("american_odds"),
            "model_p": raw.get("model_p"),
            "away_score": away_score,
            "home_score": home_score,
            "outcome_win": bool(outcome_win),
            "settled_at_utc": settled_at.isoformat(),
            "outcome_source": "MLB_STATSAPI_FINAL_BOXSCORE",
        })

    payload = {
        "schema_version": "sportsedge_mlb_ml_settlement_v1",
        "source_decision_ledger_run_id": decision_ledger.get("run_id"),
        "settled_at_utc": settled_at.isoformat(),
        "settlement_count": len(rows),
        "settlements": rows,
    }
    payload["settlement_sha256"] = hashlib.sha256(_stable_json(rows).encode("utf-8")).hexdigest()
    return payload
