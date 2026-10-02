#!/usr/bin/env python3
"""Assemble one fail-closed CFB research board for game markets and player props.

The board accepts already-produced artifacts only:
- canonical CFB game-model report, when a legitimate model run exists;
- cross-book PAPER market card for ML/spread/total fallback context;
- frozen CFB prop research-candidate report.

No input is allowed to inherit authority from another lane. Numeric game/prop
probabilities remain MODEL_CANDIDATE/LEAN and BLOCKED unless separate production
promotion exists elsewhere. PAPER consensus rows never become Model_P.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

GAME_MARKETS = {"MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL"}


class CFBAllMarketResearchError(ValueError):
    pass


def _json(path: Path | None, code: str) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBAllMarketResearchError(code) from exc
    if not isinstance(value, dict):
        raise CFBAllMarketResearchError(code)
    return value


def _finite_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        return None
    return out


def _game_model_rows(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    report = payload.get("report") if isinstance(payload.get("report"), Mapping) else payload
    rows = report.get("results") if isinstance(report, Mapping) else None
    if not isinstance(rows, list):
        return []
    out = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        market = str(raw.get("market") or "").upper()
        model_p = _finite_probability(raw.get("model_p"))
        if market not in GAME_MARKETS or model_p is None:
            continue
        out.append({
            "lane": "GAME_MODEL",
            "market": market,
            "game_id": str(raw.get("game_id") or ""),
            "side": str(raw.get("side") or ""),
            "line": raw.get("line"),
            "american_odds": raw.get("american_odds"),
            "model_p": model_p,
            "fair_market_p": raw.get("fair_market_p"),
            "edge": raw.get("edge"),
            "ev_per_dollar": raw.get("ev_per_dollar"),
            "scorecard": raw.get("scorecard"),
            "presentation_label": "LEAN",
            "decision_tier": "MODEL_CANDIDATE",
            "bet_status": "BLOCKED",
            "official": False,
            "reason": "CFB_RESEARCH_GAME_MODEL_NOT_PROMOTED",
        })
    return out


def _paper_rows(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        return []
    out = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        market = str(raw.get("market") or "").upper()
        if market not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            continue
        out.append({
            "lane": "MARKET_CONSENSUS",
            "market": market,
            "game_id": str(raw.get("game_id") or ""),
            "side": str(raw.get("side") or ""),
            "line": raw.get("line"),
            "american_odds": raw.get("draftkings_odds"),
            "model_p": None,
            "fair_market_p": raw.get("market_consensus_no_vig_p"),
            "edge": raw.get("market_consensus_edge"),
            "ev_per_dollar": raw.get("market_consensus_ev_per_dollar"),
            "presentation_label": "PAPER",
            "decision_tier": "MARKET_CONTEXT",
            "bet_status": "BLOCKED",
            "official": False,
            "reason": "CFB_MARKET_CONSENSUS_NOT_MODEL_P",
        })
    return out


def _prop_rows(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    report = payload.get("report")
    rows = report.get("results") if isinstance(report, Mapping) else None
    if not isinstance(rows, list):
        return []
    out = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        model_p = _finite_probability(raw.get("model_p"))
        if model_p is None:
            continue
        out.append({
            "lane": "PLAYER_PROP_MODEL",
            "market": str(raw.get("provider_market") or raw.get("market") or "").upper(),
            "game_id": str(raw.get("game_id") or ""),
            "player_id": raw.get("player_id"),
            "player_name": raw.get("player_name"),
            "side": str(raw.get("side") or ""),
            "line": raw.get("line"),
            "american_odds": raw.get("american_odds"),
            "model_p": model_p,
            "fair_market_p": raw.get("fair_market_p"),
            "edge": raw.get("edge"),
            "ev_per_dollar": raw.get("ev_per_dollar"),
            "presentation_label": "LEAN",
            "decision_tier": "MODEL_CANDIDATE",
            "bet_status": "BLOCKED",
            "official": False,
            "reason": "CFB_PROP_RESEARCH_ONLY_INDEPENDENT_VALIDATION_REQUIRED",
        })
    return out


def build_board(
    *,
    game_model: Mapping[str, Any] | None,
    paper_market: Mapping[str, Any] | None,
    prop_candidate: Mapping[str, Any] | None,
    generated_at: datetime,
) -> dict[str, Any]:
    game_rows = _game_model_rows(game_model)
    # A real numeric game-model row outranks PAPER context for that exact offer
    # surface. PAPER remains available only when no game-model rows were supplied.
    selected_game_rows = game_rows if game_rows else _paper_rows(paper_market)
    prop_rows = _prop_rows(prop_candidate)
    rows = [*selected_game_rows, *prop_rows]
    rows.sort(key=lambda r: (
        str(r.get("game_id") or ""),
        str(r.get("lane") or ""),
        str(r.get("market") or ""),
        str(r.get("player_name") or ""),
        str(r.get("side") or ""),
    ))
    return {
        "schema_version": "CFB_ALL_MARKET_RESEARCH_BOARD_V1",
        "generated_at_utc": generated_at.astimezone(timezone.utc).isoformat(),
        "status": "RESEARCH_ONLY",
        "game_lane": "GAME_MODEL" if game_rows else (
            "MARKET_CONSENSUS" if selected_game_rows else "MISSING"
        ),
        "prop_lane": "PLAYER_PROP_MODEL" if prop_rows else "MISSING",
        "rows": rows,
        "summary": {
            "rows": len(rows),
            "game_rows": len(selected_game_rows),
            "prop_rows": len(prop_rows),
            "model_candidate_rows": sum(
                row["decision_tier"] == "MODEL_CANDIDATE" for row in rows
            ),
            "paper_context_rows": sum(
                row["decision_tier"] == "MARKET_CONTEXT" for row in rows
            ),
            "official_bets": 0,
        },
        "authority": {
            "creates_model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-model-report", type=Path)
    ap.add_argument("--paper-market-card", type=Path)
    ap.add_argument("--prop-candidate-report", type=Path)
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/run_it/cfb_all_market_research.json"),
    )
    args = ap.parse_args()

    try:
        board = build_board(
            game_model=_json(args.game_model_report, "CFB_GAME_MODEL_REPORT_INVALID"),
            paper_market=_json(args.paper_market_card, "CFB_PAPER_MARKET_CARD_INVALID"),
            prop_candidate=_json(args.prop_candidate_report, "CFB_PROP_CANDIDATE_REPORT_INVALID"),
            generated_at=datetime.now(timezone.utc),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(board, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": board["status"],
            "game_lane": board["game_lane"],
            "prop_lane": board["prop_lane"],
            "rows": board["summary"]["rows"],
            "official_bets": 0,
            "output": str(args.output),
        }, sort_keys=True))
        return 0
    except CFBAllMarketResearchError as exc:
        print(json.dumps({"status": "BLOCKED", "blocker": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
