#!/usr/bin/env python3
"""Run the research-only context-adjusted MLB full-game lane.

Output probabilities are `research_p`, never `model_p`. Production files and
registries are not modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.canonical_manual_mlb import _resolve_game
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_context_adjusted_research import (
    RESEARCH_VERSION,
    context_adjusted_means,
    recent_starter_profile,
    recent_team_run_profile,
    weather_adjustment,
)
from sportsedge.mlb_run_it_pregame import acquire_mlb_run_it_pregame
from sportsedge.manual_quote import validate_manual_quote
from sportsedge.shared_game_engine import build_shared_game_engine_session
from sportsedge.source_lineage import canonical_json_sha256

SUPPORTED = frozenset({"MONEYLINE", "RUN_LINE", "GAME_TOTAL", "TEAM_TOTALS"})
MARKET_MAP = {"MONEYLINE": "MONEYLINE", "RUN_LINE": "RUN_LINE", "GAME_TOTAL": "TOTALS", "TEAM_TOTALS": "TEAM_TOTALS"}
MLB_LIVE_FEED_SOURCE = "MLB_STATSAPI_LIVE_FEED"
MLB_GAME_LOG_SOURCE = "MLB_STATSAPI_GAME_LOG_STRICTLY_PRIOR"
MLB_TEAM_SCHEDULE_SOURCE = "MLB_STATSAPI_SCHEDULE_STRICTLY_PRIOR"


def american_decimal(odds: int) -> float:
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / (-odds))


def economics(*, win_p: float, push_p: float, odds: int) -> dict[str, float]:
    dec = american_decimal(int(odds))
    loss_p = max(0.0, 1.0 - float(win_p) - float(push_p))
    ev = float(win_p) * (dec - 1.0) - loss_p
    settled = float(win_p) / (1.0 - float(push_p)) if push_p < 1.0 else 0.0
    return {
        "raw_break_even_p": 1.0 / dec,
        "settled_research_p": settled,
        "raw_edge_points": 100.0 * (settled - 1.0 / dec),
        "ev_per_dollar": ev,
    }


def _side_pair(row) -> list[tuple[str, int, float]]:
    paired_line = -float(row.line) if row.market_type == "RUN_LINE" else float(row.line)
    return [(str(row.side).upper(), int(row.price), float(row.line)), (str(row.paired_side).upper(), int(row.paired_price), paired_line)]


def _context_as_of(rows) -> datetime:
    # Context is a pregame diagnostic captured at execution time. Never pretend
    # it existed at the earlier sportsbook timestamp.
    latest_quote = max(row.observed_at for row in rows).astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    return max(latest_quote, now)


def _incorporation(applied: bool, reason: Any) -> dict[str, Any]:
    return {
        "incorporated": bool(applied),
        "status": "incorporated" if applied else "not incorporated",
        "reason": str(reason or ("APPLIED" if applied else "SOURCE_OR_TRANSFORM_UNAVAILABLE")),
    }


def _starter_provenance(
    *,
    pitcher: Mapping[str, Any] | None,
    profile: Mapping[str, Any],
    applied: bool,
    reason: Any,
    game_pk: int,
    target_date: str,
    context_payload_sha256: Any,
    retrieved_at_utc: str,
) -> dict[str, Any]:
    pitcher = pitcher if isinstance(pitcher, Mapping) else {}
    player_id = pitcher.get("player_id")
    source_retrieved = bool(player_id)
    out = {
        "probable_pitcher_source": MLB_LIVE_FEED_SOURCE if source_retrieved else "NOT_RETRIEVED",
        "probable_pitcher_source_url": (
            f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live" if source_retrieved else None
        ),
        "probable_pitcher_context_payload_sha256": context_payload_sha256,
        "player_id": player_id,
        "player_name": pitcher.get("player_name"),
        "history_source": MLB_GAME_LOG_SOURCE if source_retrieved else "NOT_RETRIEVED",
        "history_source_endpoint": (
            "https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
            "?stats=gameLog&group=pitching&season=<year>&gameType=R"
            if source_retrieved else None
        ),
        "history_retrieved_at_utc": retrieved_at_utc if source_retrieved else None,
        "strictly_prior_to": target_date if source_retrieved else None,
        "profile": dict(profile),
        "profile_sha256": canonical_json_sha256(profile) if profile else None,
        "source_retrieved": source_retrieved,
        **_incorporation(bool(applied and source_retrieved), reason if source_retrieved else "PROBABLE_PITCHER_SOURCE_NOT_RETRIEVED"),
    }
    return out


def _row_provenance(
    *,
    context: Mapping[str, Any],
    game_pk: int,
    target_date: str,
    context_as_of_utc: str,
    away_pitcher: Mapping[str, Any] | None,
    home_pitcher: Mapping[str, Any] | None,
    adjusted: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind every emitted row to the exact contextual inputs actually used.

    Missing or gated sources are represented explicitly as ``not incorporated``;
    they are never displayed as if they changed the research probability.
    """
    components = adjusted.get("components") if isinstance(adjusted, Mapping) else {}
    components = components if isinstance(components, Mapping) else {}
    weather_component = components.get("weather") or {}
    weather_component = weather_component if isinstance(weather_component, Mapping) else {}
    weather_lane = context.get("weather_roof") or {}
    weather_lane = weather_lane if isinstance(weather_lane, Mapping) else {}
    weather_source_retrieved = bool(weather_lane.get("source")) and str(weather_lane.get("status") or "").upper() == "AVAILABLE"
    weather_applied = bool(weather_component.get("applied")) and weather_source_retrieved
    weather_reason = weather_component.get("reason")
    if not weather_source_retrieved:
        weather_reason = "WEATHER_ROOF_SOURCE_NOT_RETRIEVED"

    away_profile = components.get("away_probable_starter") or {}
    home_profile = components.get("home_probable_starter") or {}
    away_profile = away_profile if isinstance(away_profile, Mapping) else {}
    home_profile = home_profile if isinstance(home_profile, Mapping) else {}

    # The away starter suppresses/amplifies HOME scoring; the home starter
    # suppresses/amplifies AWAY scoring.
    away_starter_reason = components.get("home_scoring_starter_reason")
    home_starter_reason = components.get("away_scoring_starter_reason")
    away_starter_applied = away_starter_reason == "APPLIED"
    home_starter_applied = home_starter_reason == "APPLIED"

    return {
        "context_bundle": {
            "source": context.get("source") or "NOT_RETRIEVED",
            "as_of_utc": context.get("as_of_utc") or context_as_of_utc,
            "payload_sha256": context.get("payload_sha256"),
            "status": context.get("status") or context.get("acquisition_status") or "UNKNOWN",
        },
        "team_run_baseline": {
            "source": MLB_TEAM_SCHEDULE_SOURCE,
            "source_endpoint": "https://statsapi.mlb.com/api/v1/schedule",
            "strictly_prior_to": target_date,
            "away_profile": dict(components.get("away_team") or {}),
            "home_profile": dict(components.get("home_team") or {}),
            "incorporated": True,
            "status": "incorporated",
            "reason": "STRICTLY_PRIOR_RECENT_RUNS_FOR_AND_AGAINST",
        },
        "weather_roof": {
            "source": weather_lane.get("source") if weather_source_retrieved else "NOT_RETRIEVED",
            "source_retrieved": weather_source_retrieved,
            "as_of_utc": weather_lane.get("as_of_utc") if weather_source_retrieved else None,
            "payload_sha256": weather_lane.get("payload_sha256") if weather_source_retrieved else None,
            "status_from_source": weather_lane.get("status") or "UNAVAILABLE",
            "points_url": weather_lane.get("points_url") if weather_source_retrieved else None,
            "forecast_hourly_url": weather_lane.get("forecast_hourly_url") if weather_source_retrieved else None,
            "forecast_grid_data_url": weather_lane.get("forecast_grid_data_url") if weather_source_retrieved else None,
            "roof_type": weather_lane.get("roof_type") if weather_source_retrieved else None,
            "roof_state": weather_lane.get("roof_state") if weather_source_retrieved else None,
            "roof_state_reason": weather_lane.get("roof_state_reason") if weather_source_retrieved else None,
            "forecast": weather_lane.get("forecast") if weather_source_retrieved else None,
            "research_adjustment": dict(weather_component),
            **_incorporation(weather_applied, weather_reason),
        },
        "pitchers": {
            "away": _starter_provenance(
                pitcher=away_pitcher,
                profile=away_profile,
                applied=away_starter_applied,
                reason=away_starter_reason,
                game_pk=game_pk,
                target_date=target_date,
                context_payload_sha256=context.get("payload_sha256"),
                retrieved_at_utc=context_as_of_utc,
            ),
            "home": _starter_provenance(
                pitcher=home_pitcher,
                profile=home_profile,
                applied=home_starter_applied,
                reason=home_starter_reason,
                game_pk=game_pk,
                target_date=target_date,
                context_payload_sha256=context.get("payload_sha256"),
                retrieved_at_utc=context_as_of_utc,
            ),
        },
    }


def run(input_path: Path) -> dict[str, Any]:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    rows_raw = raw.get("rows") if isinstance(raw, Mapping) else None
    if not isinstance(rows_raw, list) or not rows_raw:
        raise ValueError("input must contain non-empty rows")
    parsed = [validate_manual_quote(row) for row in rows_raw]

    by_game: dict[str, list[Any]] = {}
    for row in parsed:
        by_game.setdefault(str(row.game_id), []).append(row)

    output_games: list[dict[str, Any]] = []
    research_rows: list[dict[str, Any]] = []
    engine = build_shared_game_engine_session()

    for game_key, game_rows in by_game.items():
        anchor = max(game_rows, key=lambda row: row.observed_at)
        game = _resolve_game(anchor)
        target_date = datetime.fromisoformat(str(game.official_date)).date()
        context_as_of = _context_as_of(game_rows)
        context = acquire_mlb_run_it_pregame(game_pk=int(game.game_pk), as_of=context_as_of)
        history = MLBAllMarketHistorySource(retrieved_at=context_as_of)

        away_profile = recent_team_run_profile(team_id=int(game.away_id), target_date=target_date)
        home_profile = recent_team_run_profile(team_id=int(game.home_id), target_date=target_date)

        starters = context.get("starters") or {}
        probable = starters.get("probable_pitchers") if isinstance(starters, Mapping) else {}
        away_pitcher = probable.get("away") if isinstance(probable, Mapping) else None
        home_pitcher = probable.get("home") if isinstance(probable, Mapping) else None
        if not isinstance(away_pitcher, Mapping) or not away_pitcher.get("player_id"):
            raise ValueError(f"{game_key}: away probable starter unavailable")
        if not isinstance(home_pitcher, Mapping) or not home_pitcher.get("player_id"):
            raise ValueError(f"{game_key}: home probable starter unavailable")

        away_starter = recent_starter_profile(history=history, player_id=int(away_pitcher["player_id"]), target_date=target_date)
        home_starter = recent_starter_profile(history=history, player_id=int(home_pitcher["player_id"]), target_date=target_date)
        wx = weather_adjustment(context.get("weather_roof"))
        adjusted = context_adjusted_means(
            away=away_profile,
            home=home_profile,
            away_starter=away_starter,
            home_starter=home_starter,
            weather=wx,
        )
        feature_hash = canonical_json_sha256({
            "research_version": RESEARCH_VERSION,
            "game_pk": int(game.game_pk),
            "components": adjusted["components"],
        })
        row_provenance = _row_provenance(
            context=context,
            game_pk=int(game.game_pk),
            target_date=target_date.isoformat(),
            context_as_of_utc=context_as_of.isoformat(),
            away_pitcher=away_pitcher,
            home_pitcher=home_pitcher,
            adjusted=adjusted,
        )

        game_meta = {
            "game_id": game_key,
            "game_pk": int(game.game_pk),
            "away_team": str(game.away_name),
            "home_team": str(game.home_name),
            "target_date": target_date.isoformat(),
            "context_as_of_utc": context_as_of.isoformat(),
            "context_payload_sha256": context.get("payload_sha256"),
            "lineups_status": (context.get("lineups") or {}).get("status"),
            "adjusted_means": adjusted,
            "feature_source_hash": feature_hash,
            "provenance": row_provenance,
        }
        output_games.append(game_meta)

        for row in game_rows:
            if row.market_type not in SUPPORTED:
                continue
            market = MARKET_MAP[row.market_type]
            if row.market_type == "TEAM_TOTALS":
                if row.team_side == "AWAY":
                    entity_id = str(game.away_id)
                    team_side = "AWAY"
                elif row.team_side == "HOME":
                    entity_id = str(game.home_id)
                    team_side = "HOME"
                else:
                    raise ValueError("TEAM_TOTALS requires team_side")
            else:
                entity_id = str(game.game_pk)
                team_side = None

            for side, price, line in _side_pair(row):
                model_input = {
                    "game_id": str(game.game_pk),
                    "market": market,
                    "entity_id": entity_id,
                    "line": line,
                    "side": side,
                    "away_mean_runs": adjusted["away_mean_runs"],
                    "home_mean_runs": adjusted["home_mean_runs"],
                    "feature_source_hash": feature_hash,
                }
                if team_side is not None:
                    model_input["team_side"] = team_side
                result = engine(model_input)
                econ = economics(win_p=float(result["model_p"]), push_p=float(result.get("push_p") or 0.0), odds=price)
                research_rows.append({
                    "game_id": game_key,
                    "game_pk": int(game.game_pk),
                    "market_type": row.market_type,
                    "engine_market": market,
                    "entity_id": entity_id,
                    "team_side": team_side,
                    "side": side,
                    "line": line,
                    "american_odds": price,
                    "research_p": float(result["model_p"]),
                    "push_p": float(result.get("push_p") or 0.0),
                    **econ,
                    "label": "NOT_MODEL_P",
                    "truth_gate": False,
                    "official": False,
                    "promotion_evidence": False,
                    "engine_version": result.get("engine_version"),
                    "distribution_sha256": result.get("distribution_sha256"),
                    "mc_paths": result.get("mc_paths"),
                    "provenance": row_provenance,
                })

    research_rows.sort(key=lambda row: (row["game_pk"], row["market_type"], str(row.get("team_side")), row["side"], row["line"]))
    return {
        "schema_version": 2,
        "research_version": RESEARCH_VERSION,
        "label": "NOT_MODEL_P",
        "truth_gate": False,
        "official": False,
        "promotion_evidence": False,
        "input_path": str(input_path),
        "input_sha256": canonical_json_sha256(raw),
        "games": output_games,
        "results": research_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = run(Path(args.input))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}: games={len(payload['games'])} results={len(payload['results'])}")
    for game in payload["games"]:
        means = game["adjusted_means"]
        weather = means["components"]["weather"]
        print(
            f"{game['away_team']} @ {game['home_team']}: "
            f"research mean {means['away_mean_runs']:.3f}-{means['home_mean_runs']:.3f} "
            f"total={means['total_mean_runs']:.3f}; weather={weather['reason']} x{weather['multiplier']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())