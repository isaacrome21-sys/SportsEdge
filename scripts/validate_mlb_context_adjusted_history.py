#!/usr/bin/env python3
"""Retrospective diagnostic for the MLB context-adjusted research lane.

The run is intentionally NOT promotion evidence. Historical StatsAPI schedule data
can reconstruct final scores and current probable-pitcher fields, but it does not
prove that those pitcher identities were archived before the original decision.
The repository also lacks a historical point-in-time NWS forecast/roof archive, so
weather is held neutral in this validation rather than leaked retrospectively.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping
from urllib.parse import urlencode

from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_context_adjusted_research import (
    StarterProfile,
    TeamRunProfile,
    WeatherAdjustment,
    context_adjusted_means,
    recent_starter_profile,
)
from sportsedge.mlb_context_adjusted_validation import (
    VALIDATION_VERSION,
    actual_events,
    distribution_event_probabilities,
    summarize_predictions,
)
from sportsedge.mlb_context_adjusted_research import _read_json
from sportsedge.source_lineage import canonical_json_sha256


def _schedule_url(start: date, end: date) -> str:
    query = urlencode({
        "sportId": 1,
        "gameType": "R",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "hydrate": "probablePitcher",
    })
    return f"https://statsapi.mlb.com/api/v1/schedule?{query}"


def _final_games(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in payload.get("dates") or []:
        if not isinstance(block, Mapping):
            continue
        for raw in block.get("games") or []:
            if not isinstance(raw, Mapping):
                continue
            status = raw.get("status") or {}
            if not isinstance(status, Mapping) or str(status.get("abstractGameState") or "") != "Final":
                continue
            if str(raw.get("gameType") or "R") != "R":
                continue
            teams = raw.get("teams") or {}
            away = teams.get("away") if isinstance(teams, Mapping) else None
            home = teams.get("home") if isinstance(teams, Mapping) else None
            if not isinstance(away, Mapping) or not isinstance(home, Mapping):
                continue
            try:
                game_pk = int(raw["gamePk"])
                official = date.fromisoformat(str(raw.get("officialDate") or block.get("date"))[:10])
                away_id = int((away.get("team") or {})["id"])
                home_id = int((home.get("team") or {})["id"])
                away_runs = int(away["score"])
                home_runs = int(home["score"])
            except (KeyError, TypeError, ValueError):
                continue
            away_probable = away.get("probablePitcher") or {}
            home_probable = home.get("probablePitcher") or {}
            try:
                away_starter_id = int(away_probable.get("id")) if away_probable.get("id") else None
                home_starter_id = int(home_probable.get("id")) if home_probable.get("id") else None
            except (TypeError, ValueError):
                away_starter_id = home_starter_id = None
            out.append({
                "game_pk": game_pk,
                "date": official,
                "away_id": away_id,
                "home_id": home_id,
                "away_runs": away_runs,
                "home_runs": home_runs,
                "away_starter_id": away_starter_id,
                "home_starter_id": home_starter_id,
            })
    out.sort(key=lambda row: (row["date"], row["game_pk"]))
    return out


def _team_profile(games: list[Mapping[str, Any]], *, team_id: int, target_date: date, window: int = 30, minimum: int = 10) -> TeamRunProfile:
    rows: list[tuple[int, int]] = []
    for game in games:
        if game["date"] >= target_date:
            continue
        if int(game["away_id"]) == int(team_id):
            rows.append((int(game["away_runs"]), int(game["home_runs"])))
        elif int(game["home_id"]) == int(team_id):
            rows.append((int(game["home_runs"]), int(game["away_runs"])))
    rows = rows[-window:]
    if len(rows) < minimum:
        raise ValueError(f"team:{team_id}: insufficient strict-prior games {len(rows)}<{minimum}")
    return TeamRunProfile(
        team_id=int(team_id),
        games=len(rows),
        runs_for_mean=float(fmean(row[0] for row in rows)),
        runs_against_mean=float(fmean(row[1] for row in rows)),
    )


def _neutral_weather() -> WeatherAdjustment:
    return WeatherAdjustment(
        multiplier=1.0,
        applied=False,
        reason="VALIDATION_WEATHER_NEUTRAL_HISTORICAL_PIT_FORECAST_ARCHIVE_MISSING",
        temperature_f=None,
        roof_type=None,
        roof_state=None,
    )


def _prediction(*, game_pk: int, label: str, away_mean: float, home_mean: float, simulations: int) -> dict[str, Any]:
    return {
        "away_mean_runs": float(away_mean),
        "home_mean_runs": float(home_mean),
        "events": distribution_event_probabilities(
            game_id=str(game_pk),
            away_mean_runs=float(away_mean),
            home_mean_runs=float(home_mean),
            model_label=label,
            simulations=simulations,
        ),
    }


def run(*, start: date, end: date, simulations: int) -> dict[str, Any]:
    if start > end:
        raise ValueError("start must be <= end")
    if (end - start).days > 31:
        raise ValueError("validation window may not exceed 32 calendar days")
    retrieved_at = datetime.now(timezone.utc)
    lookback_start = start - timedelta(days=180)
    schedule_url = _schedule_url(lookback_start, end)
    schedule = _read_json(schedule_url)
    all_games = _final_games(schedule)
    evaluation = [game for game in all_games if start <= game["date"] <= end]
    history = MLBAllMarketHistorySource(retrieved_at=retrieved_at)
    included: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for game in evaluation:
        if not game["away_starter_id"] or not game["home_starter_id"]:
            skipped.append({"game_pk": game["game_pk"], "date": game["date"].isoformat(), "reason": "RETROSPECTIVE_PROBABLE_STARTER_MISSING"})
            continue
        try:
            away = _team_profile(all_games, team_id=game["away_id"], target_date=game["date"])
            home = _team_profile(all_games, team_id=game["home_id"], target_date=game["date"])
            away_starter = recent_starter_profile(
                history=history,
                player_id=int(game["away_starter_id"]),
                target_date=game["date"],
            )
            home_starter = recent_starter_profile(
                history=history,
                player_id=int(game["home_starter_id"]),
                target_date=game["date"],
            )
            weather = _neutral_weather()
            adjusted = context_adjusted_means(
                away=away,
                home=home,
                away_starter=away_starter,
                home_starter=home_starter,
                weather=weather,
            )
            blend_away = 0.5 * away.runs_for_mean + 0.5 * home.runs_against_mean
            blend_home = 0.5 * home.runs_for_mean + 0.5 * away.runs_against_mean
            predictions = {
                "offense_only": _prediction(
                    game_pk=game["game_pk"], label="offense_only",
                    away_mean=away.runs_for_mean, home_mean=home.runs_for_mean,
                    simulations=simulations,
                ),
                "defense_blend": _prediction(
                    game_pk=game["game_pk"], label="defense_blend",
                    away_mean=blend_away, home_mean=blend_home,
                    simulations=simulations,
                ),
                "starter_adjusted": _prediction(
                    game_pk=game["game_pk"], label="starter_adjusted",
                    away_mean=float(adjusted["away_mean_runs"]), home_mean=float(adjusted["home_mean_runs"]),
                    simulations=simulations,
                ),
            }
            included.append({
                "game_pk": game["game_pk"],
                "date": game["date"].isoformat(),
                "away_team_id": game["away_id"],
                "home_team_id": game["home_id"],
                "away_starter_id": game["away_starter_id"],
                "home_starter_id": game["home_starter_id"],
                "starter_identity_source": "CURRENT_HISTORICAL_STATSAPI_SCHEDULE_PROBABLE_PITCHER_FIELD",
                "starter_identity_pit_verified": False,
                "weather_pit_verified": False,
                "weather_handling": weather.reason,
                "away_starter_status": away_starter.status,
                "home_starter_status": home_starter.status,
                "actual_away_runs": game["away_runs"],
                "actual_home_runs": game["home_runs"],
                "actual_events": actual_events(away_runs=game["away_runs"], home_runs=game["home_runs"]),
                "predictions": predictions,
            })
        except Exception as exc:
            skipped.append({"game_pk": game["game_pk"], "date": game["date"].isoformat(), "reason": f"{type(exc).__name__}:{exc}"})

    if not included:
        raise RuntimeError("NO_VALIDATION_GAMES_INCLUDED")
    summaries = {
        label: summarize_predictions(included, model_label=label)
        for label in ("offense_only", "defense_blend", "starter_adjusted")
    }
    base = summaries["offense_only"]
    adjusted = summaries["starter_adjusted"]
    comparison = {
        "binary_brier_delta_adjusted_minus_offense_only": adjusted["binary"]["brier"] - base["binary"]["brier"],
        "binary_log_loss_delta_adjusted_minus_offense_only": adjusted["binary"]["log_loss"] - base["binary"]["log_loss"],
        "binary_ece_delta_adjusted_minus_offense_only": adjusted["binary"]["ece"] - base["binary"]["ece"],
        "total_rmse_delta_adjusted_minus_offense_only": adjusted["runs"]["total"]["rmse"] - base["runs"]["total"]["rmse"],
        "total_mean_error_delta_adjusted_minus_offense_only": adjusted["runs"]["total"]["mean_error"] - base["runs"]["total"]["mean_error"],
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "validation_version": VALIDATION_VERSION,
        "state": "DIAGNOSTIC_ONLY_PIT_EVIDENCE_INCOMPLETE",
        "label": "NOT_MODEL_P",
        "truth_gate": False,
        "official": False,
        "promotion_authority": False,
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "retrieved_at_utc": retrieved_at.isoformat(),
        "schedule_source_url": schedule_url,
        "schedule_source_sha256": canonical_json_sha256(schedule),
        "simulations_per_game_model": simulations,
        "evaluation_game_count": len(evaluation),
        "included_game_count": len(included),
        "skipped_game_count": len(skipped),
        "blockers": [
            "HISTORICAL_STARTER_IDENTITY_NOT_ARCHIVED_AT_DECISION_TIME",
            "HISTORICAL_PIT_WEATHER_FORECAST_ARCHIVE_MISSING",
            "HISTORICAL_GAME_DAY_ROOF_STATE_ARCHIVE_MISSING",
        ],
        "summaries": summaries,
        "comparison": comparison,
        "games": included,
        "skipped": skipped,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--simulations", type=int, default=10000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = run(start=date.fromisoformat(args.start), end=date.fromisoformat(args.end), simulations=args.simulations)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "evaluation_games": payload["evaluation_game_count"],
        "included_games": payload["included_game_count"],
        "skipped_games": payload["skipped_game_count"],
        "comparison": payload["comparison"],
        "blockers": payload["blockers"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
