#!/usr/bin/env python3
"""Free four-sport research with a truthful per-selection factor checklist.

Game ML/spread/total estimates delegate to the existing UNVALIDATED free_models
engine. Player/pitcher props call the real research_model_adapters only when
the required verified history or simulation inputs are present on the row.
Missing provenance yields an explicit NO_MODEL_OR_MARKET research row — never
a league-prior probability and never a silent drop. All network calls are to
existing free ESPN/Open-Meteo endpoints.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifacts import free_models as engine
from sportsedge import research_model_adapters as adapters

FIELDS = (
    "team_quality", "injuries", "rest_travel", "home_park", "weather",
    "recent_form", "matchups", "coaching", "key_numbers",
    "market_context", "sport_specific", "player_props",
)
UNWIRED = "NOT_WIRED"
MISSING = "MISSING_UNVERIFIED"
HEURISTIC = "HEURISTIC_NOT_VALIDATED"


def _is_prop_market(market: str) -> bool:
    m = str(market or "").upper().strip()
    m = {"MONEYLINE": "ML", "H2H": "ML", "RUN_LINE": "SPREAD",
         "GAME_TOTAL": "TOTAL", "TOTALS": "TOTAL"}.get(m, m)
    return m not in {"ML", "SPREAD", "TOTAL"}


def _try_real_adapter(row: dict, now_iso: str) -> dict | None:
    """Call the real adapter when the required provenance fields are present.

    Returns a research row (PRICED_RESEARCH or NO_MODEL_OR_MARKET) or None if
    this is a game market that should go through free_models.
    """
    market = str(row.get("market") or "").upper().strip()
    if not _is_prop_market(market):
        return None
    sport = str(row.get("sport") or "").upper().strip()
    game_id = str(row.get("game_id") or row.get("game") or "")
    player_id = row.get("player_id")
    side = str(row.get("side") or "").upper().strip()
    line = row.get("line")
    home = row.get("home") or row.get("home_team")
    away = row.get("away") or row.get("away_team")
    kickoff = row.get("kickoff_utc") or row.get("start_utc")
    source_as_of = row.get("source_as_of_utc")
    as_of = row.get("as_of_utc") or now_iso

    # MLB pitcher path
    if sport == "MLB" and market.startswith("PITCHER_"):
        features = row.get("features") or {}
        prior_times = row.get("prior_start_times_utc") or []
        starter_ok = row.get("starting_pitcher_verified") is True
        rows = adapters.mlb_pitcher_to_bridge_rows(
            game_id=game_id, player_id=str(player_id or ""),
            market=market, side=side, line=line,
            features=features, prior_start_times_utc=prior_times,
            source_as_of_utc=str(source_as_of or ""),
            as_of_utc=str(as_of), kickoff_utc=str(kickoff or ""),
            starting_pitcher_verified=starter_ok,
            home_team=str(home or ""), away_team=str(away or ""),
        )
        return rows[0] if rows else None

    # NFL/CFB player path
    if sport in {"NFL", "CFB"} and (market.startswith("PLAYER_") or row.get("stat")):
        paths = row.get("paths") or []
        stat = row.get("stat") or market.replace("PLAYER_", "", 1)
        verified = row.get("market_blind_simulation_verified") is True
        rows = adapters.football_player_stat_to_bridge_rows(
            sport=sport, game_id=game_id, player_id=str(player_id or ""),
            stat=stat, line=line, side=side, paths=paths,
            source_as_of_utc=str(source_as_of or ""),
            as_of_utc=str(as_of), kickoff_utc=str(kickoff or ""),
            home_team=str(home or ""), away_team=str(away or ""),
            market_blind_simulation_verified=verified,
        )
        return rows[0] if rows else None

    # Team / first-inning / other props with no real engine yet
    return {
        "sport": sport, "game_id": game_id, "market": market,
        "selection": side, "player_id": player_id,
        "status": "NO_MODEL_OR_MARKET",
        "reason": "NO_REAL_ENGINE_FOR_MARKET_MISSING_VERIFIED_INPUTS",
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }


def audit_row(source, result):
    sport = str(source.get("sport") or "").upper()
    market = str(source.get("market") or "").upper()
    market = {"MONEYLINE": "ML", "H2H": "ML", "RUN_LINE": "SPREAD",
              "GAME_TOTAL": "TOTAL", "TOTALS": "TOTAL"}.get(market, market)
    context = result.get("context") or {}
    notes = [str(x).upper() for x in result.get("context_notes") or []]
    n = " ".join(notes)
    has = bool(context) and result.get("status") not in (
        "BLOCKED_INVALID", "BLOCKED_STARTED", "BLOCKED_CONTEXT_UNVERIFIED",
        "BLOCKED_KICKOFF_UNVERIFIED", "BLOCKED_IL_COLLEGE",
        "BLOCKED_UNPAIRED_ML", "NO_MODEL_OR_MARKET",
    )
    out = {f: {"status": UNWIRED, "detail": "No independently priced input wired"} for f in FIELDS}
    history = (has and "NO_FETCH_MANUAL_MODE" not in n
               and "HOME_HISTORY_COUNT:" in n and "AWAY_HISTORY_COUNT:" in n
               and not any(x in n for x in ("HISTORY_MISSING", "TEAM_IDENTITY_UNMATCHED")))
    out["team_quality"] = {"status": HEURISTIC if history else MISSING,
                           "detail": "Bounded prior-five-game scoring-margin proxy" if history else "Missing independently verified two-team history"}
    if sport in ("NFL", "CFB", "NBA"):
        recognized = has and n.count("INJURIES:HEURISTIC_OUT_DOUBTFUL") == 2
        out["injuries"] = {"status": HEURISTIC if recognized else MISSING,
                           "detail": "ESPN out/doubtful + bounded heuristic" if recognized else
                           "Injury data unavailable/unrecognized for at least one team; do not interpret zero as healthy"}
    else:
        out["injuries"]["detail"] = "MLB roster/injury impact is not modeled"
    if has and "HOME_REST_DAYS:" in n and "AWAY_REST_DAYS:" in n:
        out["rest_travel"] = {
            "status": "SCHEDULE_REST_OBSERVED_NO_PRICE_EFFECT",
            "detail": "Last-game-to-kickoff days for both teams verified from completed ESPN schedule; "
                      "travel/fatigue model and calibrated rest adjustment not wired",
        }
    else:
        out["rest_travel"]["detail"] = "No verified schedule rest for both teams or calibrated travel/fatigue pricing; NBA rest_adj manual-only"
    out["home_park"] = {"status": "LEAGUE_BASELINE_ONLY" if has else MISSING,
                        "detail": "Static home advantage; no verified park-specific coefficients"}
    if sport in ("NFL", "CFB", "MLB"):
        state = HEURISTIC if "WEATHER:HEURISTIC_FORECAST" in n and has else (
            "VERIFIED_INDOOR" if "WEATHER:INDOOR_VERIFIED" in n else MISSING)
        out["weather"] = {"status": state, "detail": "Verified venue + free Open-Meteo wind/rain required; unresolved means unknown"}
    else:
        out["weather"] = {"status": "NOT_APPLICABLE", "detail": "NBA indoor league"}
    out["recent_form"] = {"status": "PARTIAL_HEURISTIC" if history else MISSING,
                          "detail": "Short prior-game scoring trend; MLB form subsumed into rating"}
    out["matchups"]["detail"] = "No independently estimated player-vs-coverage, trenches, style or opponent fit"
    out["coaching"]["detail"] = "No independently estimated coaching, scheme or motivation effect"
    out["key_numbers"] = {"status": "PUSH_AWARE_ONLY" if market in ("SPREAD", "TOTAL") and has else MISSING,
                          "detail": "Integer push refund modeled; separate NFL 3/7 distribution not trained"}
    out["market_context"] = {"status": HEURISTIC if result.get("market_anchor") else MISSING,
                             "detail": "15% unfitted residual anchored to supplied DK line, no contemporaneous sharp reference"}
    sport_specific = {
        "NFL": "Score approximation only; QB/trenches and Next Gen measures not wired",
        "CFB": "Score approximation only; talent/portal effects not wired",
        "NBA": "Score approximation only; pace, rotations, stars and verified rest not independently wired",
        "MLB": "Poisson run approximation; Statcast, SP/bullpen, park not automatically wired",
    }
    out["sport_specific"] = {"status": "PARTIAL_HEURISTIC" if has else MISSING,
                              "detail": sport_specific.get(sport, "Unsupported sport")}
    if _is_prop_market(market):
        status = result.get("status")
        if status == "PRICED_RESEARCH":
            out["player_props"] = {
                "status": "REAL_ENGINE_ADAPTER",
                "detail": "Priced via research_model_adapters from verified engine inputs",
            }
        else:
            out["player_props"] = {
                "status": "NO_MODEL_OR_MARKET",
                "detail": result.get("reason") or "Missing verified player history or simulation paths; no probability assigned",
            }
    else:
        out["player_props"] = {"status": "NOT_APPLICABLE", "detail": "Game-level market"}
    return out


def run_full(payload, *, now=None, getter=None, auto_context=True, min_ev=0.02):
    rows = payload if isinstance(payload, list) else payload.get("lines")
    if not isinstance(rows, list):
        raise ValueError("LINES_MUST_BE_LIST")
    from datetime import datetime, timezone
    now_iso = (now or datetime.now(timezone.utc)).isoformat()

    # Split: game markets go through free_models; props go through adapters
    game_rows = []
    prop_results = []  # (index, result)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            game_rows.append(row)
            continue
        adapted = _try_real_adapter(row, now_iso)
        if adapted is not None:
            prop_results.append((i, adapted))
        else:
            game_rows.append(row)

    # Run free engine only on game markets
    if game_rows:
        game_payload = {"lines": game_rows} if isinstance(payload, dict) else game_rows
        if isinstance(payload, dict):
            game_payload = dict(payload)
            game_payload["lines"] = game_rows
        card = engine.run(game_payload, now=now, getter=getter,
                          auto_context=auto_context, min_ev=min_ev)
        game_evaluated = card.get("evaluated_rows") or []
    else:
        card = {"evaluated_rows": [], "research_only": True}
        game_evaluated = []

    # Reassemble full evaluated list in original order
    evaluated = [None] * len(rows)
    g_idx = 0
    for i, row in enumerate(rows):
        if any(pi == i for pi, _ in prop_results):
            continue
        if g_idx < len(game_evaluated):
            evaluated[i] = game_evaluated[g_idx]
            g_idx += 1
    for i, result in prop_results:
        evaluated[i] = result
    # Fill any gaps (should not happen)
    for i, ev in enumerate(evaluated):
        if ev is None:
            evaluated[i] = {
                "status": "NO_MODEL_OR_MARKET",
                "reason": "INTERNAL_SPLIT_MISMATCH",
                "research_only": True,
            }
    card["evaluated_rows"] = evaluated

    default_sport = payload.get("sport") if isinstance(payload, dict) else None
    audit = []
    totals = Counter()
    for i, (row, result) in enumerate(zip(rows, evaluated)):
        source = dict(row) if isinstance(row, dict) else {}
        if not source.get("sport") and default_sport:
            source["sport"] = default_sport
        factors = audit_row(source, result)
        totals.update(v["status"] for v in factors.values())
        audit.append({"input_index": i, "status": result.get("status"),
                      "sport": source.get("sport"), "market": source.get("market"),
                      "factors": factors})
    card["factor_coverage"] = {
        "schema": "SPORTSEDGE_FACTOR_COVERAGE_V1",
        "coverage_is_not_validation": True,
        "by_input_index": audit,
        "status_counts": dict(sorted(totals.items())),
        "advanced_metrics": {
            "statcast": UNWIRED, "next_gen": UNWIRED, "coaching": UNWIRED,
            "travel": UNWIRED, "player_props": UNWIRED,
        },
    }
    card["runner"] = "RUN_IT_FULL_FREE_RESEARCH_ONLY_V1"
    return card


def main(argv=None):
    p = argparse.ArgumentParser(description="Free research card plus complete truthful factor-coverage audit")
    p.add_argument("--lines", required=True, type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--min-ev", type=float, default=0.02)
    args = p.parse_args(argv)
    if not 0 <= args.min_ev <= 0.15:
        p.error("min-ev must be between 0 and 0.15")
    card = run_full(json.loads(args.lines.read_text(encoding="utf-8")),
                    auto_context=not args.no_fetch, min_ev=args.min_ev)
    rendered = json.dumps(card, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
