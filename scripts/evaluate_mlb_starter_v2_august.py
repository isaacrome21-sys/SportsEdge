#!/usr/bin/env python3
"""One-shot August 2026 evaluation of starter v2 vs defense blend.

Do not re-run after reading results. See mlb_starter_spec_v2_prelock.md.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.mlb_context_adjusted_research import TeamRunProfile, recent_team_run_profile
from sportsedge.mlb_context_adjusted_validation import (
    GAME_TOTAL_LINES,
    actual_events,
    distribution_event_probabilities,
    summarize_predictions,
)
from sportsedge.mlb_generic_features import MLBGenericHistorySource, _outs_from_ip
from sportsedge.mlb_starter_v2 import (
    CONSTANTS_SHA256,
    STARTER_IDENTITY_SOURCE,
    LeagueRateBaseline,
    constants_receipt,
    peripheral_profile_from_start_rows,
    starter_v2_means,
)
from sportsedge.source_lineage import canonical_json_sha256

EVAL_START = date(2026, 8, 1)
EVAL_END = date(2026, 8, 31)
LEAGUE_START = date(2026, 6, 1)
LEAGUE_END = date(2026, 7, 31)
USER_AGENT = "SportsEdge-StarterV2-Research/1.0"


def _get(url: str, *, attempts: int = 5) -> Mapping[str, Any]:
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            with urlopen(req, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise RuntimeError(f"not object: {url}")
            return payload
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(min(8.0, 0.75 * attempt))
    raise RuntimeError(f"FETCH_FAILED:{url}:{type(last).__name__}:{last}") from last


def _starter_id(side: Mapping[str, Any]) -> int | None:
    probable = side.get("probablePitcher")
    if isinstance(probable, Mapping) and probable.get("id") not in (None, ""):
        try:
            return int(probable["id"])
        except (TypeError, ValueError):
            return None
    return None


def _schedule(start: date, end: date) -> list[dict[str, Any]]:
    query = urlencode({
        "sportId": 1,
        "gameType": "R",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "hydrate": "probablePitcher",
    })
    payload = _get(f"https://statsapi.mlb.com/api/v1/schedule?{query}")
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
            away_team = away.get("team") if isinstance(away.get("team"), Mapping) else {}
            home_team = home.get("team") if isinstance(home.get("team"), Mapping) else {}
            try:
                official = date.fromisoformat(str(raw.get("officialDate") or block.get("date") or "")[:10])
                games.append({
                    "game_pk": int(raw["gamePk"]),
                    "date": official,
                    "away_id": int(away_team["id"]),
                    "home_id": int(home_team["id"]),
                    "away_runs": int(away["score"]),
                    "home_runs": int(home["score"]),
                    "away_starter_id": _starter_id(away),
                    "home_starter_id": _starter_id(home),
                })
            except (KeyError, TypeError, ValueError):
                continue
    return games


def _start_rows(history: MLBGenericHistorySource, player_id: int, target_date: date) -> list[dict[str, Any]]:
    rows = history.player_rows(player_id=int(player_id), group="pitching", target_date=target_date)
    out: list[dict[str, Any]] = []
    for row in rows:
        stat = row.get("stat") or {}
        if not isinstance(stat, Mapping):
            continue
        try:
            if float(stat.get("gamesStarted", 0) or 0) < 1:
                continue
            outs = float(_outs_from_ip(stat.get("inningsPitched")))
            so = float(stat.get("strikeOuts", 0) or 0)
            bb = float(stat.get("baseOnBalls", 0) or 0)
            hr = float(stat.get("homeRuns", 0) or 0)
        except Exception:
            continue
        if outs <= 0:
            continue
        out.append({"outs": outs, "strikeouts": so, "walks": bb, "home_runs": hr, "date": row.get("date")})
    return out


def _league_baseline(history: MLBGenericHistorySource, june_july: list[dict[str, Any]]) -> LeagueRateBaseline:
    starter_ids: set[int] = set()
    for game in june_july:
        if game.get("away_starter_id"):
            starter_ids.add(int(game["away_starter_id"]))
        if game.get("home_starter_id"):
            starter_ids.add(int(game["home_starter_id"]))
    total_outs = total_k = total_bb = total_hr = 0.0
    cutoff = date(2026, 8, 1)
    for index, player_id in enumerate(sorted(starter_ids), 1):
        try:
            rows = _start_rows(history, player_id, cutoff)
        except Exception as exc:
            print(f"league starter skip {player_id}: {type(exc).__name__}", flush=True)
            continue
        for row in rows:
            row_date = row.get("date")
            if not isinstance(row_date, date):
                continue
            if row_date < LEAGUE_START or row_date > LEAGUE_END:
                continue
            total_outs += float(row["outs"])
            total_k += float(row["strikeouts"])
            total_bb += float(row["walks"])
            total_hr += float(row["home_runs"])
        if index % 25 == 0:
            print(f"league pitchers {index}/{len(starter_ids)} outs={total_outs:.0f}", flush=True)
    if total_outs <= 0:
        raise RuntimeError("LEAGUE_RATES_EMPTY")
    return LeagueRateBaseline(
        k_rate=total_k / total_outs,
        bb_rate=total_bb / total_outs,
        hr_rate=total_hr / total_outs,
        total_outs=total_outs,
    )


def _prediction(game_pk: int, label: str, away_mean: float, home_mean: float, simulations: int) -> dict[str, Any]:
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


def run(*, simulations: int) -> dict[str, Any]:
    retrieved_at = datetime.now(timezone.utc)
    print("loading schedules", flush=True)
    august = _schedule(EVAL_START, EVAL_END)
    june_july = _schedule(LEAGUE_START, LEAGUE_END)
    print(f"august={len(august)} june_july={len(june_july)}", flush=True)
    history = MLBGenericHistorySource(retrieved_at=retrieved_at)
    league = _league_baseline(history, june_july)
    print(f"league outs={league.total_outs:.0f} k={league.k_rate:.4f} bb={league.bb_rate:.4f} hr={league.hr_rate:.4f}", flush=True)
    team_cache: dict[tuple[int, date], TeamRunProfile] = {}
    included: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, game in enumerate(august, 1):
        away_starter_id = game.get("away_starter_id")
        home_starter_id = game.get("home_starter_id")
        if not away_starter_id or not home_starter_id:
            skipped.append({"game_pk": game["game_pk"], "date": game["date"].isoformat(), "reason": "ACTUAL_STARTER_MISSING"})
            continue
        try:
            away_key = (int(game["away_id"]), game["date"])
            home_key = (int(game["home_id"]), game["date"])
            if away_key not in team_cache:
                team_cache[away_key] = recent_team_run_profile(team_id=away_key[0], target_date=away_key[1])
            if home_key not in team_cache:
                team_cache[home_key] = recent_team_run_profile(team_id=home_key[0], target_date=home_key[1])
            away = team_cache[away_key]
            home = team_cache[home_key]
            away_rows = _start_rows(history, int(away_starter_id), game["date"])
            home_rows = _start_rows(history, int(home_starter_id), game["date"])
            away_starter = peripheral_profile_from_start_rows(player_id=int(away_starter_id), rows=away_rows)
            home_starter = peripheral_profile_from_start_rows(player_id=int(home_starter_id), rows=home_rows)
            blend_away = 0.5 * away.runs_for_mean + 0.5 * home.runs_against_mean
            blend_home = 0.5 * home.runs_for_mean + 0.5 * away.runs_against_mean
            v2 = starter_v2_means(
                away_runs_for=away.runs_for_mean,
                away_runs_against=away.runs_against_mean,
                home_runs_for=home.runs_for_mean,
                home_runs_against=home.runs_against_mean,
                away_starter=away_starter,
                home_starter=home_starter,
                league=league,
            )
            included.append({
                "game_pk": game["game_pk"],
                "date": game["date"].isoformat(),
                "away_team_id": game["away_id"],
                "home_team_id": game["home_id"],
                "away_starter_id": int(away_starter_id),
                "home_starter_id": int(home_starter_id),
                "starter_identity_source": STARTER_IDENTITY_SOURCE,
                "starter_identity_pit_verified": False,
                "away_starter_status": away_starter.status,
                "home_starter_status": home_starter.status,
                "actual_away_runs": game["away_runs"],
                "actual_home_runs": game["home_runs"],
                "actual_events": actual_events(away_runs=game["away_runs"], home_runs=game["home_runs"]),
                "predictions": {
                    "defense_blend": _prediction(game["game_pk"], "defense_blend", blend_away, blend_home, simulations),
                    "starter_v2": _prediction(game["game_pk"], "starter_v2", v2["away_mean_runs"], v2["home_mean_runs"], simulations),
                },
            })
        except Exception as exc:
            skipped.append({"game_pk": game["game_pk"], "date": game["date"].isoformat(), "reason": f"{type(exc).__name__}:{exc}"})
        if index % 25 == 0:
            print(f"[{index}/{len(august)}] included={len(included)} skipped={len(skipped)}", flush=True)
    if not included:
        raise RuntimeError("NO_AUGUST_GAMES_INCLUDED")
    summaries = {
        label: summarize_predictions(included, model_label=label)
        for label in ("defense_blend", "starter_v2")
    }

    def _line_gap(summary: Mapping[str, Any]) -> float:
        gaps = []
        for line in GAME_TOTAL_LINES:
            event = f"GAME_TOTAL_OVER_{line:g}"
            row = summary["by_event"][event]
            gaps.append(abs(float(row["mean_predicted_p"]) - float(row["observed_rate"])))
        return float(sum(gaps) / len(gaps) * 100.0)

    def _line_brier(summary: Mapping[str, Any]) -> float:
        scores = [float(summary["by_event"][f"GAME_TOTAL_OVER_{line:g}"]["brier"]) for line in GAME_TOTAL_LINES]
        return float(sum(scores) / len(scores))

    blend_gap = _line_gap(summaries["defense_blend"])
    v2_gap = _line_gap(summaries["starter_v2"])
    blend_brier = _line_brier(summaries["defense_blend"])
    v2_brier = _line_brier(summaries["starter_v2"])
    gate = {
        "mean_abs_calibration_gap_pp": {"defense_blend": blend_gap, "starter_v2": v2_gap, "starter_better": v2_gap < blend_gap},
        "mean_brier": {"defense_blend": blend_brier, "starter_v2": v2_brier, "starter_better": v2_brier < blend_brier},
        "passes": (v2_gap < blend_gap) and (v2_brier < blend_brier),
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "evaluation": "MLB_STARTER_V2_AUGUST_ONE_SHOT",
        "state": "DIAGNOSTIC_STAND_IN_STARTERS_PROVISIONAL_IF_PASS",
        "label": "NOT_MODEL_P",
        "promotion_authority": False,
        "constants_receipt": constants_receipt(),
        "constants_sha256": CONSTANTS_SHA256,
        "coverage_start": EVAL_START.isoformat(),
        "coverage_end": EVAL_END.isoformat(),
        "league_rate_window": {"start": LEAGUE_START.isoformat(), "end": LEAGUE_END.isoformat()},
        "retrieved_at_utc": retrieved_at.isoformat(),
        "simulations_per_game_model": simulations,
        "evaluation_game_count": len(august),
        "included_game_count": len(included),
        "skipped_game_count": len(skipped),
        "league_baseline": {
            "k_rate": league.k_rate,
            "bb_rate": league.bb_rate,
            "hr_rate": league.hr_rate,
            "total_outs": league.total_outs,
        },
        "gate": gate,
        "summaries": summaries,
        "skipped": skipped,
        "blockers": [
            "ACTUAL_STARTER_STAND_IN_NO_PREGAME_PIT_ARCHIVE",
            "HISTORICAL_SCHEDULE_PROBABLE_PITCHER_FIELD",
            "HISTORICAL_PIT_WEATHER_FORECAST_ARCHIVE_MISSING",
        ],
    }
    payload["payload_sha256"] = canonical_json_sha256({k: v for k, v in payload.items() if k != "games"})
    payload["games"] = included
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulations", type=int, default=20000)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.simulations < 1000:
        raise SystemExit("simulations must be >= 1000")
    payload = run(simulations=args.simulations)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "constants_sha256": payload["constants_sha256"],
        "included": payload["included_game_count"],
        "skipped": payload["skipped_game_count"],
        "gate": payload["gate"],
        "league_baseline": payload["league_baseline"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
