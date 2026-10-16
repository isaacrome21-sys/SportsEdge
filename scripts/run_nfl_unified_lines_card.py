#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# SUPERSEDED ROUTE (2026-10-12): the ONE canonical RUN IT card path is
# artifacts/run_it_full.py (run_full). This entry point is retained for
# reference/replay only and must not be treated as a canonical card source.
# ---------------------------------------------------------------------------
"""Run the unified NFL game + QB/RB/WR phone board.

The command discovers the upcoming schedule, pulls current PIT depth/injury
context and strictly-prior weekly player stats, then binds the already-pasted
two-sided prices after the model run.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from sportsedge.nfl_attempt9_live_forecast import load_runtime, raw_forecasts, recency_features
from sportsedge.sports.nfl.market_anchored_residual import ResidualQuoteError, price_game
from scripts.run_nfl_lines_card import _history_rows


from sportsedge.nfl_unified_phone import (
    UnifiedNflPhoneError,
    _match_schedule,
    _utc,
    build_unified_phone_card,
)
from sportsedge.nfl_scoring_composition_artifact import load_prior_file
from sportsedge.sports.nfl.v1_live_pin import V1LivePinError, require_verified_v1_live
from sportsedge.sports.nfl.auto_slate import discover_nfl_auto_games
from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.full_auto import fetch_nflverse_depth_charts
from sportsedge.sports.nfl.injury_report_source import fetch_nflverse_injuries
from sportsedge.sports.nfl.live_role_source import fetch_nflverse_player_stats


def _read(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _has_props(ticket: dict) -> bool:
    return any(
        str(row.get("player") or "").strip()
        for game in ticket.get("games") or []
        for row in game.get("markets") or []
        if isinstance(row, dict)
    )



def _validate_auto_prop_kickoffs(ticket: dict, schedule_games: list[dict]) -> None:
    """Reject an externally quoted kickoff contradicting independent schedule.

    Intake-only; never adjusts model outputs or frozen player-prop engine.
    Older manual tickets without provider kickoff use the existing unique-match rule.
    """
    observed = _utc(ticket.get("observed_at"), "observed_at")
    for game in ticket.get("games") or []:
        if not isinstance(game, dict):
            raise UnifiedNflPhoneError("GAME_OBJECT_REQUIRED")
        raw_kickoff = game.get("commence_time")
        if raw_kickoff is None:
            continue
        quote_kickoff = _utc(raw_kickoff, "quote_kickoff")
        away = str(game.get("away") or "").strip().upper()
        home = str(game.get("home") or "").strip().upper()
        independent = _match_schedule(
            schedule_games, away=away, home=home, observed_at=observed
        )
        verified_kickoff = _utc(independent["kickoff"], "kickoff")
        if abs((verified_kickoff - quote_kickoff).total_seconds()) > 900:
            raise UnifiedNflPhoneError(
                f"QUOTE_KICKOFF_INDEPENDENT_SCHEDULE_MISMATCH:{away}@{home}"
            )


def attach_residual_game_research(payload: dict, ticket: dict, history: object) -> dict:
    """Sidecar only; frozen unified prop/grid runtime and game disabled status stay unchanged.

    The only available independent game prediction for this lane is the
    strictly-prior Attempt-9 forecaster. No invented M2 score forecast.
    The shared residual adapter also accepts independent frozen M2 raw margin/
    total when callers supply them through run_it_market_anchored().
    """
    as_of = str(ticket.get("observed_at") or "")
    try:
        slate = date.fromisoformat(str(ticket.get("slate") or as_of[:10]))
    except (TypeError, ValueError):
        for row in payload.get("games") or []:
            row["residual_research_error"] = "SLATE_ASOF_REQUIRED"
        return payload
    prior = _history_rows(history)
    runtime = load_runtime()
    for input_game, output_game in zip(ticket.get("games") or [], payload.get("games") or []):
        features = recency_features(
            prior, home=str(input_game["home"]), away=str(input_game["away"]), asof=slate
        ) if prior else {"ok": False, "reason": "PIT_HISTORY_REQUIRED"}
        if not features.get("ok"):
            output_game["residual_research_error"] = str(features.get("reason"))
            continue
        raw = raw_forecasts(runtime, features["vector"])
        try:
            output_game["residual_game_prices"] = price_game(
                input_game, raw_model_margin=raw["margin"],
                raw_model_total=raw["total"], as_of=as_of,
            )
            output_game["residual_research_source"] = "ATTEMPT9_INDEPENDENT_PRIOR_SIDECAR"
        except ResidualQuoteError as exc:
            output_game["residual_research_error"] = str(exc)
    payload["residual_research_authority"] = {
        "research_only": True, "validated_markets": [], "promotion": False,
        "official": False, "staking": False, "forward_clv_proven": False,
    }
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--history", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--n-sims", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--horizon-days", type=int, default=10)
    ap.add_argument("--scoring-prior")
    args = ap.parse_args()
    try:
        require_verified_v1_live()
    except V1LivePinError as exc:
        # t214u Option A: refuse the entire execution; no fallback.
        raise SystemExit(f"NFL_V1_LIVE_PIN_REFUSED:{exc}") from None

    ticket = _read(args.input)
    history = _read(args.history)
    observed_at = ticket.get("observed_at")
    if not observed_at:
        raise SystemExit("NFL_UNIFIED_PHONE_OBSERVED_AT_REQUIRED")

    plan = discover_nfl_auto_games(
        as_of=observed_at,
        min_lead_minutes=0,
        horizon_minutes=max(1, int(args.horizon_days)) * 24 * 60,
        game_types=("REG", "POST"),
    )
    schedule_games = list(plan.get("games") or [])
    _validate_auto_prop_kickoffs(ticket, schedule_games)
    seasons = sorted({
        int(row["season"])
        for row in schedule_games
        if row.get("season") not in (None, "")
    })

    depth_rows = []
    player_rows = []
    injury_rows = []
    source_status = {
        "schedule": "AVAILABLE",
        "depth": "NOT_REQUIRED",
        "player_stats": "NOT_REQUIRED",
        "injuries": "NOT_REQUIRED",
    }
    injury_source_ready = False

    if _has_props(ticket):
        if not seasons:
            source_status["depth"] = "MISSING:NO_SCHEDULE_SEASON"
            source_status["player_stats"] = "MISSING:NO_SCHEDULE_SEASON"
            source_status["injuries"] = "MISSING:NO_SCHEDULE_SEASON"
        else:
            for season in seasons:
                try:
                    rows, _uri, _digest = fetch_nflverse_depth_charts(season=season)
                    depth_rows.extend(rows)
                    source_status["depth"] = "AVAILABLE"
                except NFLContextError as exc:
                    source_status["depth"] = f"MISSING:{exc}"

            stat_seasons = sorted({season for s in seasons for season in (s - 1, s)})
            try:
                player_rows, _receipts = fetch_nflverse_player_stats(seasons=stat_seasons)
                source_status["player_stats"] = "AVAILABLE"
            except NFLContextError as exc:
                source_status["player_stats"] = f"MISSING:{exc}"

            injury_ok = True
            for season in seasons:
                try:
                    rows, _uri, _digest = fetch_nflverse_injuries(season=season)
                    injury_rows.extend(rows)
                except NFLContextError as exc:
                    injury_ok = False
                    source_status["injuries"] = f"MISSING:{exc}"
            if injury_ok:
                source_status["injuries"] = "AVAILABLE"
                injury_source_ready = True

    scoring_prior = load_prior_file(args.scoring_prior) if args.scoring_prior else None

    payload = build_unified_phone_card(
        ticket,
        history=history,
        schedule_games=schedule_games,
        depth_rows=depth_rows,
        player_rows=player_rows,
        injury_rows=injury_rows,
        injury_source_ready=injury_source_ready,
        scoring_prior=scoring_prior,
        n_sims=int(args.n_sims),
        seed=int(args.seed),
    )
    payload = attach_residual_game_research(payload, ticket, history)
    payload["source_status"] = source_status
    payload["schedule_source_sha256"] = plan.get("schedule_source_sha256")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "OK",
        "games": len(payload.get("games") or []),
        "rows": len(payload.get("rows") or []),
        "selected_rows": len(payload.get("selected_rows") or []),
        "source_status": source_status,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
