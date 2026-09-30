#!/usr/bin/env python3
"""One-shot August 2026 promotion gate for MLB starter v2.

The candidate, constants, dates, total lines, and gate were frozen before this
script is executed. This script deliberately has no date/tuning arguments.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping
from urllib.parse import urlencode

from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_context_adjusted_research import _read_json
from sportsedge.mlb_context_adjusted_validation import (
    actual_events,
    distribution_event_probabilities,
    summarize_predictions,
)
from sportsedge.mlb_generic_features import _number, _outs_from_ip, _splits
from sportsedge.mlb_starter_v2 import (
    CONSTANTS_SHA256,
    STARTER_IDENTITY_SOURCE,
    LeagueRateBaseline,
    peripheral_profile_from_start_rows,
    starter_v2_means,
)
from sportsedge.mlb_starter_v2_evaluation import (
    EVALUATION_CONFIG,
    EVALUATION_CONFIG_SHA256,
    EVALUATION_LINES,
    SIMULATIONS_PER_GAME_MODEL,
    promotion_gate,
)
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import DEFAULT_FULL_GAME_DISPERSION_R

EXPECTED_CONSTANTS_SHA256 = "c349df6bbb38c8507440e86421649100ae88a636adc683d975fe6853dbd0158c"
EXPECTED_DISPERSION_R = 5.217229403204152
COVERAGE_START = date(2026, 8, 1)
COVERAGE_END = date(2026, 8, 31)
LEAGUE_START = date(2026, 6, 1)
LEAGUE_END = date(2026, 7, 31)
HISTORY_START = date(2026, 2, 1)


def _schedule_url() -> str:
    query = urlencode({
        "sportId": 1,
        "gameType": "R",
        "startDate": HISTORY_START.isoformat(),
        "endDate": COVERAGE_END.isoformat(),
        "hydrate": "probablePitcher",
    })
    return f"https://statsapi.mlb.com/api/v1/schedule?{query}"


def _final_games(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
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
                official = date.fromisoformat(str(raw.get("officialDate") or block.get("date"))[:10])
                away_team = away.get("team") or {}
                home_team = home.get("team") or {}
                game = {
                    "game_pk": int(raw["gamePk"]),
                    "date": official,
                    "away_id": int(away_team["id"]),
                    "home_id": int(home_team["id"]),
                    "away_runs": int(away["score"]),
                    "home_runs": int(home["score"]),
                    "away_starter_id": int((away.get("probablePitcher") or {}).get("id")) if (away.get("probablePitcher") or {}).get("id") else None,
                    "home_starter_id": int((home.get("probablePitcher") or {}).get("id")) if (home.get("probablePitcher") or {}).get("id") else None,
                }
            except (KeyError, TypeError, ValueError):
                continue
            games.append(game)
    games.sort(key=lambda row: (row["date"], row["game_pk"]))
    return games


def _team_profile(games: list[Mapping[str, Any]], *, team_id: int, target_date: date) -> tuple[float, float, int]:
    rows: list[tuple[int, int]] = []
    for game in games:
        if game["date"] >= target_date:
            continue
        if int(game["away_id"]) == int(team_id):
            rows.append((int(game["away_runs"]), int(game["home_runs"])))
        elif int(game["home_id"]) == int(team_id):
            rows.append((int(game["home_runs"]), int(game["away_runs"])))
    rows = rows[-30:]
    if len(rows) < 10:
        raise ValueError(f"team:{team_id}: insufficient strict-prior games {len(rows)}<10")
    return float(fmean(r[0] for r in rows)), float(fmean(r[1] for r in rows)), len(rows)


def _season_rows(history: MLBAllMarketHistorySource, *, player_id: int, cache: dict[int, list[Mapping[str, Any]]]) -> list[Mapping[str, Any]]:
    pid = int(player_id)
    if pid not in cache:
        payload = history._player_season(pid, "pitching", 2026)
        cache[pid] = _splits(payload, target_date=date(2026, 9, 1))
    return cache[pid]


def _start_rows(rows: list[Mapping[str, Any]], *, before: date | None = None, start: date | None = None, end: date | None = None) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for row in rows:
        d = row.get("date")
        stat = row.get("stat")
        if not isinstance(d, date) or not isinstance(stat, Mapping):
            continue
        if before is not None and d >= before:
            continue
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        try:
            if _number(stat.get("gamesStarted", 0), "gamesStarted") < 1:
                continue
            outs = float(_outs_from_ip(stat.get("inningsPitched")))
            ks = float(_number(stat.get("strikeOuts", 0), "strikeOuts"))
            bb = float(_number(stat.get("baseOnBalls", 0), "baseOnBalls"))
            hr = float(_number(stat.get("homeRuns", 0), "homeRuns"))
        except Exception:
            continue
        if outs <= 0 or min(ks, bb, hr) < 0:
            continue
        out.append({"outs": outs, "strikeouts": ks, "walks": bb, "home_runs": hr, "date": d.isoformat()})
    return out


def _league_baseline(*, games: list[Mapping[str, Any]], history: MLBAllMarketHistorySource, cache: dict[int, list[Mapping[str, Any]]]) -> LeagueRateBaseline:
    pitcher_ids: set[int] = set()
    for game in games:
        if LEAGUE_START <= game["date"] <= LEAGUE_END:
            for key in ("away_starter_id", "home_starter_id"):
                if game.get(key):
                    pitcher_ids.add(int(game[key]))
    total_outs = total_k = total_bb = total_hr = 0.0
    for pitcher_id in sorted(pitcher_ids):
        rows = _season_rows(history, player_id=pitcher_id, cache=cache)
        for start in _start_rows(rows, start=LEAGUE_START, end=LEAGUE_END):
            total_outs += float(start["outs"])
            total_k += float(start["strikeouts"])
            total_bb += float(start["walks"])
            total_hr += float(start["home_runs"])
    if total_outs <= 0:
        raise RuntimeError("NO_JUNE_JULY_STARTER_OUTS")
    return LeagueRateBaseline(
        k_rate=total_k / total_outs,
        bb_rate=total_bb / total_outs,
        hr_rate=total_hr / total_outs,
        total_outs=total_outs,
    )


def _prediction(*, game_pk: int, label: str, away_mean: float, home_mean: float) -> dict[str, Any]:
    return {
        "away_mean_runs": float(away_mean),
        "home_mean_runs": float(home_mean),
        "events": distribution_event_probabilities(
            game_id=str(game_pk),
            away_mean_runs=float(away_mean),
            home_mean_runs=float(home_mean),
            model_label=label,
            simulations=SIMULATIONS_PER_GAME_MODEL,
        ),
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    gate = payload["gate"]
    lines = [
        "# MLB starter v2 — one-shot August 2026 gate result",
        "",
        f"**Decision: {gate['decision']}**",
        "",
        f"- Window: {payload['coverage_start']} → {payload['coverage_end']}",
        f"- Included games: {payload['included_game_count']} / {payload['evaluation_game_count']}",
        f"- Constants SHA256: `{payload['constants_sha256']}`",
        f"- Evaluation config SHA256: `{payload['evaluation_config_sha256']}`",
        f"- Stage-1 dispersion r: `{payload['stage1_dispersion_r']}`",
        f"- Starter identity: `{payload['starter_identity_source']}`; PIT verified = `{str(payload['starter_identity_pit_verified']).lower()}`",
        "",
        "## Locked dual gate",
        "",
        "| Metric | Defense blend | Starter v2 | Delta | Pass |",
        "|---|---:|---:|---:|:---:|",
        f"| Mean absolute calibration gap | {gate['mean_abs_calibration_gap']['defense_blend']:.6f} | {gate['mean_abs_calibration_gap']['starter_v2']:.6f} | {gate['mean_abs_calibration_gap']['delta_candidate_minus_baseline']:+.6f} | {'YES' if gate['mean_abs_calibration_gap']['pass'] else 'NO'} |",
        f"| Mean Brier | {gate['mean_brier']['defense_blend']:.6f} | {gate['mean_brier']['starter_v2']:.6f} | {gate['mean_brier']['delta_candidate_minus_baseline']:+.6f} | {'YES' if gate['mean_brier']['pass'] else 'NO'} |",
        "",
        "## Per-line calibration",
        "",
        "| Total | n | Observed over | Defense pred | Starter v2 pred | Defense gap | v2 gap | Defense Brier | v2 Brier |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in gate["lines"]:
        lines.append(
            f"| {row['line']:.1f} | {row['n']} | {row['observed_rate']:.4f} | {row['baseline_predicted_rate']:.4f} | {row['candidate_predicted_rate']:.4f} | {row['baseline_abs_calibration_gap']:.4f} | {row['candidate_abs_calibration_gap']:.4f} | {row['baseline_brier']:.4f} | {row['candidate_brier']:.4f} |"
        )
    lines.extend([
        "",
        "## Descriptive run metrics",
        "",
        f"- Defense-blend total MAE: {payload['summaries']['defense_blend']['runs']['total']['mae']:.4f}",
        f"- Starter-v2 total MAE: {payload['summaries']['starter_v2']['runs']['total']['mae']:.4f}",
        f"- Defense-blend total mean error: {payload['summaries']['defense_blend']['runs']['total']['mean_error']:+.4f}",
        f"- Starter-v2 total mean error: {payload['summaries']['starter_v2']['runs']['total']['mean_error']:+.4f}",
        "",
        "## Authority",
        "",
        "This is the single pre-registered August score. A pass grants only provisional production authority because August starter identity uses the disclosed actual-starter stand-in without a pregame PIT archive. A failure leaves production on defense blend and burns August for starter-v2 tuning.",
        "",
    ])
    return "\n".join(lines)


def run() -> dict[str, Any]:
    if CONSTANTS_SHA256 != EXPECTED_CONSTANTS_SHA256:
        raise RuntimeError(f"CONSTANTS_HASH_MISMATCH:{CONSTANTS_SHA256}")
    if abs(float(DEFAULT_FULL_GAME_DISPERSION_R) - EXPECTED_DISPERSION_R) > 1e-15:
        raise RuntimeError(f"DISPERSION_R_MISMATCH:{DEFAULT_FULL_GAME_DISPERSION_R}")
    if tuple(EVALUATION_LINES) != (6.5, 7.5, 8.5, 9.5):
        raise RuntimeError("EVALUATION_LINES_CHANGED")

    retrieved_at = datetime.now(timezone.utc)
    schedule_url = _schedule_url()
    schedule = _read_json(schedule_url)
    games = _final_games(schedule)
    evaluation = [g for g in games if COVERAGE_START <= g["date"] <= COVERAGE_END]
    if not evaluation:
        raise RuntimeError("NO_AUGUST_GAMES")

    history = MLBAllMarketHistorySource(retrieved_at=retrieved_at)
    player_cache: dict[int, list[Mapping[str, Any]]] = {}
    league = _league_baseline(games=games, history=history, cache=player_cache)
    included: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for game in evaluation:
        if not game.get("away_starter_id") or not game.get("home_starter_id"):
            skipped.append({"game_pk": game["game_pk"], "date": game["date"].isoformat(), "reason": "ACTUAL_STARTER_STAND_IN_MISSING"})
            continue
        try:
            away_for, away_against, away_n = _team_profile(games, team_id=game["away_id"], target_date=game["date"])
            home_for, home_against, home_n = _team_profile(games, team_id=game["home_id"], target_date=game["date"])
            away_rows = _season_rows(history, player_id=int(game["away_starter_id"]), cache=player_cache)
            home_rows = _season_rows(history, player_id=int(game["home_starter_id"]), cache=player_cache)
            away_starter = peripheral_profile_from_start_rows(
                player_id=int(game["away_starter_id"]),
                rows=_start_rows(away_rows, before=game["date"]),
            )
            home_starter = peripheral_profile_from_start_rows(
                player_id=int(game["home_starter_id"]),
                rows=_start_rows(home_rows, before=game["date"]),
            )
            v2 = starter_v2_means(
                away_runs_for=away_for,
                away_runs_against=away_against,
                home_runs_for=home_for,
                home_runs_against=home_against,
                away_starter=away_starter,
                home_starter=home_starter,
                league=league,
            )
            blend_away = 0.5 * away_for + 0.5 * home_against
            blend_home = 0.5 * home_for + 0.5 * away_against
            included.append({
                "game_pk": game["game_pk"],
                "date": game["date"].isoformat(),
                "away_team_id": game["away_id"],
                "home_team_id": game["home_id"],
                "away_starter_id": game["away_starter_id"],
                "home_starter_id": game["home_starter_id"],
                "away_profile_games": away_n,
                "home_profile_games": home_n,
                "starter_identity_source": STARTER_IDENTITY_SOURCE,
                "starter_identity_pit_verified": False,
                "actual_away_runs": game["away_runs"],
                "actual_home_runs": game["home_runs"],
                "actual_events": actual_events(away_runs=game["away_runs"], home_runs=game["home_runs"]),
                "predictions": {
                    "defense_blend": _prediction(game_pk=game["game_pk"], label="defense_blend", away_mean=blend_away, home_mean=blend_home),
                    "starter_v2": _prediction(game_pk=game["game_pk"], label="starter_v2", away_mean=float(v2["away_mean_runs"]), home_mean=float(v2["home_mean_runs"])),
                },
                "starter_v2_receipt": v2,
            })
        except Exception as exc:
            skipped.append({"game_pk": game["game_pk"], "date": game["date"].isoformat(), "reason": f"{type(exc).__name__}:{exc}"})

    if not included:
        raise RuntimeError("NO_EVALUATION_GAMES_INCLUDED")
    summaries = {
        "defense_blend": summarize_predictions(included, model_label="defense_blend"),
        "starter_v2": summarize_predictions(included, model_label="starter_v2"),
    }
    gate = promotion_gate(baseline=summaries["defense_blend"], candidate=summaries["starter_v2"])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "state": "ONE_SHOT_AUGUST_GATE_SCORED",
        "coverage_start": COVERAGE_START.isoformat(),
        "coverage_end": COVERAGE_END.isoformat(),
        "league_rate_window": {"start": LEAGUE_START.isoformat(), "end": LEAGUE_END.isoformat()},
        "retrieved_at_utc": retrieved_at.isoformat(),
        "constants_sha256": CONSTANTS_SHA256,
        "evaluation_config": EVALUATION_CONFIG,
        "evaluation_config_sha256": EVALUATION_CONFIG_SHA256,
        "stage1_dispersion_r": float(DEFAULT_FULL_GAME_DISPERSION_R),
        "starter_identity_source": STARTER_IDENTITY_SOURCE,
        "starter_identity_pit_verified": False,
        "league_baseline": {
            "k_rate_per_out": league.k_rate,
            "bb_rate_per_out": league.bb_rate,
            "hr_rate_per_out": league.hr_rate,
            "total_starter_outs": league.total_outs,
        },
        "schedule_source_url": schedule_url,
        "schedule_source_sha256": canonical_json_sha256(schedule),
        "evaluation_game_count": len(evaluation),
        "included_game_count": len(included),
        "skipped_game_count": len(skipped),
        "summaries": summaries,
        "gate": gate,
        "promotion_authority": "PROVISIONAL" if gate["gate_pass"] else "NONE",
        "production_decision": "ELIGIBLE_FOR_SEPARATE_PROMOTION_PR" if gate["gate_pass"] else "KEEP_DEFENSE_BLEND",
        "skipped": skipped,
        "games": included,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()
    payload = run()
    json_path = Path(args.output_json)
    md_path = Path(args.output_md)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "decision": payload["gate"]["decision"],
        "evaluation_games": payload["evaluation_game_count"],
        "included_games": payload["included_game_count"],
        "skipped_games": payload["skipped_game_count"],
        "constants_sha256": payload["constants_sha256"],
        "evaluation_config_sha256": payload["evaluation_config_sha256"],
        "gate": payload["gate"],
        "payload_sha256": payload["payload_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
