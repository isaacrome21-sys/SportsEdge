#!/usr/bin/env python3
"""Free four-sport research with a truthful per-selection factor checklist.

Game ML/spread/total estimates delegate to the existing UNVALIDATED free_models
engine. MLB pitcher props use verified public StatsAPI starts. MLB batter props
use verified public StatsAPI game logs and an empirical pricer. NFL/CFB player
props and Statcast/Next Gen remain unpriced until verified collectors exist.
Issues are untrusted odds intake.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifacts import free_models as engine
from sportsedge.mlb_phone_pitcher_pricing import phone_pitcher_rows, blocked
from sportsedge.mlb_phone_batter_pricing import phone_batter_rows
from datetime import datetime, timezone

FIELDS = (
    "team_quality", "injuries", "rest_travel", "home_park", "weather",
    "recent_form", "matchups", "coaching", "key_numbers",
    "market_context", "sport_specific", "player_props",
)
UNWIRED = "NOT_WIRED"
MISSING = "MISSING_UNVERIFIED"
HEURISTIC = "HEURISTIC_NOT_VALIDATED"


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
    if market not in ("ML", "SPREAD", "TOTAL"):
        src = result.get("source") or ""
        if src in {"FREE_MLB_STATSAPI_GAMELOG", "FREE_MLB_STATSAPI_BATTER_GAMELOG"} and result.get("status") != "NO_MODEL_OR_MARKET":
            out["player_props"] = {
                "status": "REAL_PUBLIC_HISTORY_MODEL_UNVALIDATED",
                "detail": "Verified prior MLB StatsAPI game logs priced by real empirical engine; not validated vs closes",
            }
        else:
            out["player_props"] = {
                "status": "NO_MODEL_OR_MARKET",
                "detail": result.get("reason") or "Required real player-level history or simulated paths unavailable; no probability assigned",
            }
    else:
        out["player_props"] = {"status": "NOT_APPLICABLE", "detail": "Game-level market"}
    return out


def run_full(payload, *, now=None, getter=None, auto_context=True, min_ev=0.02):
    """Separate real game, pitcher, and batter models, preserving original row order.

    Issues are UNTRUSTED odds intake: NEVER use submitted features,
    probabilities, starter/participation verification flags or simulation paths.
    Trusted data comes only from free public MLB endpoints.
    """
    rows = payload if isinstance(payload, list) else payload.get("lines")
    if not isinstance(rows, list):
        raise ValueError("LINES_MUST_BE_LIST")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("MODEL_NOW_TIMEZONE_REQUIRED")
    default_sport = payload.get("sport") if isinstance(payload, dict) else None
    game_indices, games, prop_indices, props = [], [], [], []
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError("LINE_MUST_BE_OBJECT")
        line = dict(raw)
        line["sport"] = str(line.get("sport") or default_sport or "").upper()
        market = str(line.get("market") or "").upper().strip()
        market = {"MONEYLINE":"ML","H2H":"ML","RUN_LINE":"SPREAD",
                  "GAME_TOTAL":"TOTAL","TOTALS":"TOTAL"}.get(market,market)
        if market in {"ML","SPREAD","TOTAL"}:
            game_indices.append(i)
            games.append(line)
        else:
            prop_indices.append(i)
            props.append(line)

    if games:
        card = engine.run({"lines":games},now=clock,getter=getter,
                          auto_context=auto_context,min_ev=min_ev)
        priced_games = card.get("evaluated_rows") or []
        if len(priced_games) != len(games):
            raise ValueError("GAME_EVALUATED_ROWS_INCOMPLETE")
        for local, original in enumerate(game_indices):
            priced_games[local]["input_index"] = original
    else:
        priced_games = []
        card = {
            "schema":"SPORTSEDGE_FREE_RESEARCH_CARD_V1",
            "as_of_utc":clock.astimezone(timezone.utc).isoformat(),
            "min_ev":min_ev, "edges":[],
            "independent_candidates":[], "independent_watchlist":[],
            "diagnostics":[], "source_receipts":[],
            "summary":{"rows":0,"edges":0,"status_counts":{}},
            "research_only":True,
            "authority":{"research_only":True,"official":False,
                         "model_p":False,"staking":False},
        }
    pitcher_pos, pitcher_input = [], []
    batter_pos, batter_input = [], []
    others = {}
    for local, line in enumerate(props):
        market = str(line.get("market") or "").upper()
        if line["sport"] == "MLB" and market.startswith("PITCHER_"):
            pitcher_pos.append(local)
            pitcher_input.append(line)
        elif line["sport"] == "MLB" and market.startswith("BATTER_"):
            batter_pos.append(local)
            batter_input.append(line)
        else:
            others[local] = blocked(line, "NO_VERIFIED_MODEL_FOR_THIS_MARKET")
    pitcher_results, pitcher_receipts = phone_pitcher_rows(
        pitcher_input, now=clock, getter=getter if auto_context else (lambda url: None))
    batter_results, batter_receipts = phone_batter_rows(
        batter_input, now=clock, getter=getter if auto_context else (lambda url: None))
    if len(pitcher_results) != len(pitcher_input):
        raise ValueError("PITCHER_RESULT_COUNT_MISMATCH")
    if len(batter_results) != len(batter_input):
        raise ValueError("BATTER_RESULT_COUNT_MISMATCH")
    modeled_props = [None]*len(props)
    for local, result in zip(pitcher_pos, pitcher_results):
        modeled_props[local] = result
    for local, result in zip(batter_pos, batter_results):
        modeled_props[local] = result
    for local, result in others.items():
        modeled_props[local] = result
    if any(r is None for r in modeled_props):
        raise ValueError("PROP_RESULT_COUNT_MISMATCH")

    evaluated = [None]*len(rows)
    for i, result in zip(game_indices, priced_games):
        evaluated[i] = result
    for i, result in zip(prop_indices, modeled_props):
        result["input_index"] = i
        evaluated[i] = result
    if any(r is None for r in evaluated):
        raise ValueError("EVALUATED_ROWS_REQUIRED_TO_AVOID_FALSE_FACTOR_COVERAGE")
    card["evaluated_rows"] = evaluated
    card.setdefault("summary",{})
    card["summary"]["rows"] = len(rows)
    card["summary"]["status_counts"] = dict(sorted(Counter(
        r.get("status") or "MISSING_STATUS" for r in evaluated).items()))
    card["prop_candidates"] = sorted(
        [r for r in modeled_props if r.get("status")=="RESEARCH_CANDIDATE_NOT_VALIDATED"],
        key=lambda r:-r["ev_per_dollar"])
    card["prop_watchlist"] = sorted(
        [r for r in modeled_props if r.get("status","").startswith("WATCH_")],
        key=lambda r:-r.get("ev_per_dollar",-1))
    card["prop_unpriced"] = [r for r in modeled_props if r.get("status")=="NO_MODEL_OR_MARKET"]
    card["source_receipts"] = list(card.get("source_receipts") or []) + pitcher_receipts + batter_receipts
    card["prop_model_status"] = {
        "pitcher_engine":"MLB_PITCHER_JOINT_EMPIRICAL_BAYES",
        "batter_engine":"MLB_BATTER_EMPIRICAL_GAMELOG",
        "free_public_history":True,
        "model_vs_close_validated":False,
        "phone_odds_freshness_required":True,
        "no_generic_player_prior":True,
        "unsupported_player_markets_blocked":len(card["prop_unpriced"]),
        "statcast":"NOT_WIRED",
        "next_gen":"NOT_WIRED",
        "nfl_cfb_player":"NOT_WIRED",
    }

    audit, totals = [], Counter()
    for i, (source,result) in enumerate(zip(rows,evaluated)):
        source = dict(source)
        if not source.get("sport") and default_sport:
            source["sport"] = default_sport
        factors = audit_row(source,result)
        totals.update(v["status"] for v in factors.values())
        audit.append({"input_index":i, "status":result.get("status"),
                      "sport":source.get("sport"),"market":source.get("market"),
                      "factors":factors})
    card["factor_coverage"] = {
        "schema":"SPORTSEDGE_FACTOR_COVERAGE_V1",
        "coverage_is_not_validation":True,
        "by_input_index":audit,
        "status_counts":dict(sorted(totals.items())),
        "advanced_metrics":{
            "statcast":UNWIRED,"next_gen":UNWIRED,"coaching":UNWIRED,
            "travel":UNWIRED,"player_props":
            "MLB_PITCHER_AND_BATTER_PUBLIC_HISTORY_OTHERS_UNWIRED",
        },
    }
    card["runner"]="RUN_IT_FULL_REAL_MLB_PITCHER_BATTER_PREGAME_V1"
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
