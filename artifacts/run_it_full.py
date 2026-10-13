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
from sportsedge.mlb_phone_first_inning_pricing import (
    phone_first_inning_rows, FIRST_INNING_PHONE_MARKETS)
from sportsedge.nfl_phone_player_pricing import phone_nfl_player_rows
from sportsedge.cfb_phone_player_pricing import phone_cfb_player_rows
from sportsedge.prepricing.factor_ingestion import stage_games
from sportsedge.team_half_pricing import DERIVATIVES, price_team_half_rows
from sportsedge.pricing_provenance import (
    apply_play_gate, determine_provenance)
from sportsedge.canonical_coverage import (
    NFL_ANYTIME_TD_MARKETS, NFL_DERIVATIVE_MARKETS, NFL_FIRST_TD_MARKETS,
    blocked_row_for as coverage_blocked_row, coverage_summary)
from sportsedge.mlb_f5_quote_binding import (
    F5_MARKET_ALIASES as F5_INTAKE_ALIASES, F5_MARKETS as F5_CANONICAL_MARKETS,
    phone_f5_binding_rows)
from sportsedge.market_coverage import (
    COVERAGE_MARKETS,
    normalize_coverage_market,
    phone_coverage_rows,
)
from sportsedge.mlb_phone_f5_pricing import normalize_f5_market, phone_f5_rows
from sportsedge.f5_distribution import F5_MARKETS
from datetime import datetime, timezone

FIELDS = (
    "team_quality", "injuries", "rest_travel", "home_park", "weather",
    "recent_form", "matchups", "coaching", "key_numbers",
    "market_context", "manual_context", "sport_specific", "player_props",
)
UNWIRED = "NOT_WIRED"
MISSING = "MISSING_UNVERIFIED"
HEURISTIC = "HEURISTIC_NOT_VALIDATED"

# Owner ruling (Isaac, Oct 13, 2026): NFL full-game team totals and NFL
# first-half markets must NOT route to the team/half pricer. They reach
# the canonical derivative stage and fail closed NO_ENGINE until
# compliant engines exist, on DISTINCT grounds: full-game team totals
# for want of a verified team-score distribution (pricer guard
# NFL_TEAM_TOTAL_SCORE_DISTRIBUTION_EMPTY); first-half markets for want
# of a compliant period distribution (pricer guard SIMULATION_ROWS_EMPTY).
# Keys are the post-intake-rename market names; values are the
# derivative stage's canonical market names. NFL only: the team/half
# pricer keeps CFB and the other sports' rows, and MLB team totals keep
# the game-lane contract (#2074).
_NFL_RULING_DERIVATIVE_TRANSLATION = {
    "TEAM_TOTAL": "TEAM_TOTAL",
    "TOTAL_1H": "FIRST_HALF_TOTAL",
    "SPREAD_1H": "FIRST_HALF_SPREAD",
    "TEAM_TOTAL_1H": "FIRST_HALF_TEAM_TOTAL",
    "ML_1H": "FIRST_HALF_MONEYLINE",
}


def audit_row(source, result):
    sport = str(source.get("sport") or "").upper()
    market = str(source.get("market") or "").upper()
    market = {"MONEYLINE": "ML", "H2H": "ML", "RUN_LINE": "SPREAD",
              "GAME_TOTAL": "TOTAL", "TOTALS": "TOTAL",
              "TEAM_TOTAL": "TEAM_TOTALS"}.get(market, market)
    coverage_market = normalize_coverage_market(market)
    if coverage_market is not None:
        market = coverage_market
    elif sport == "MLB":
        f5_market = normalize_f5_market(market)
        if f5_market is not None:
            market = f5_market
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
    out["key_numbers"] = {"status": "PUSH_AWARE_ONLY" if market in ("SPREAD", "TOTAL", "TEAM_TOTALS") and has else MISSING,
                          "detail": "Integer push refund modeled; separate NFL 3/7 distribution not trained"}
    out["market_context"] = {"status": HEURISTIC if result.get("market_anchor") else MISSING,
                             "detail": "15% unfitted residual anchored to supplied DK line, no contemporaneous sharp reference"}
    # Repair 2: the factor audit says which lane produced the row's numbers.
    lane = str(result.get("pricing_lane") or "")
    if lane == "LANE_A_INDEPENDENT":
        out["market_context"] = {
            "status": "NOT_USED_LANE_A_INDEPENDENT",
            "detail": "Lane A (independent): the win probability used no market input; "
                      "the anchored Lane B view is available separately as lane_b_anchored",
        }
    elif lane == "LANE_B_ANCHORED":
        out["market_context"] = {
            "status": "ANCHORED_UNVALIDATED_LANE_B",
            "detail": "Lane B (anchored): Lane A shrunk 15% toward the supplied DK line; "
                      "unfitted hypothesis, must prove out-of-sample",
        }
    # Repair 1: manual context overrides must be visible in the factor audit.
    provenance = result.get("context_provenance") or {}
    user_keys = sorted(k for k, v in provenance.items() if v == "USER_SUPPLIED_MANUAL")
    if user_keys:
        out["manual_context"] = {
            "status": "USER_SUPPLIED_MANUAL",
            "detail": "Explicit manual overrides applied to: " + ", ".join(user_keys)
                      + ". Labeled, never silent; verified factors were not replaced without the flag.",
        }
    elif result.get("status") == "BLOCKED_MANUAL_CONTEXT_UNDECLARED":
        out["manual_context"] = {
            "status": "BLOCKED_UNDECLARED_OVERRIDE",
            "detail": "Row carried manual context overrides without the explicit flag: "
                      + str(result.get("reason") or ""),
        }
    else:
        out["manual_context"] = {
            "status": "VERIFIED_PUBLIC_ONLY",
            "detail": "No manual context overrides; factors are verified-public or heuristic defaults",
        }
    sport_specific = {
        "NFL": "Score approximation only; QB/trenches and Next Gen measures not wired",
        "CFB": "Score approximation only; talent/portal effects not wired",
        "NBA": "Score approximation only; pace, rotations, stars and verified rest not independently wired",
        "MLB": "Poisson run approximation; Statcast, SP/bullpen, park not automatically wired",
    }
    out["sport_specific"] = {"status": "PARTIAL_HEURISTIC" if has else MISSING,
                              "detail": sport_specific.get(sport, "Unsupported sport")}
    market = {
        "FIRST_HALF_TOTAL": "TOTAL_1H", "HALF_TOTAL": "TOTAL_1H",
        "1H_TOTAL": "TOTAL_1H", "FIRST_HALF_SPREAD": "SPREAD_1H",
        "1H_SPREAD": "SPREAD_1H", "FIRST_HALF_TEAM_TOTAL": "TEAM_TOTAL_1H",
        "1H_TEAM_TOTAL": "TEAM_TOTAL_1H",
        "FIRST_FIVE_TOTAL": "F5_TOTAL", "FIRST_FIVE_TEAM_TOTAL": "F5_TEAM_TOTAL",
    }.get(market, market)
    if sport != "MLB":
        market = {"TEAM_TOTALS": "TEAM_TOTAL",
                  "TEAM_TOTAL_OVER_UNDER": "TEAM_TOTAL"}.get(market, market)
    if market in DERIVATIVES:
        out["player_props"] = {"status": "NOT_APPLICABLE",
                               "detail": "Team or period game market, not a player prop"}
        if result.get("source") == "FREE_ESPN_SCORE_DERIVATIVE_UNVALIDATED" and result.get("status") != "NO_MODEL_OR_MARKET":
            out["team_quality"] = {"status": HEURISTIC,
                                   "detail": "Public fixture and team score heuristic; unfitted for team/half distribution"}
            out["key_numbers"] = {"status": "PUSH_AWARE_ONLY",
                                  "detail": "Observed threshold and integer push mass; no fitted key-number model"}
    elif market not in ("ML", "SPREAD", "TOTAL", "TEAM_TOTALS"):
        src = result.get("source") or ""
        if market in COVERAGE_MARKETS or market in F5_MARKETS:
            out["player_props"] = {"status": "NOT_APPLICABLE",
                                   "detail": "Game-level market"}
        elif src in {"FREE_MLB_STATSAPI_GAMELOG", "FREE_MLB_STATSAPI_BATTER_GAMELOG",
                   "FREE_MLB_STATSAPI_LINESCORE", "FREE_NFLVERSE_ANYTIME_TD",
                   "FREE_ESPN_NFL_GAMELOG", "FREE_ESPN_CFB_GAMELOG"} and result.get("status") != "NO_MODEL_OR_MARKET":
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


def _prepricing_blocked_row(line, stage, input_index):
    """Fail-closed row for a game whose critical factor could not be verified."""
    return {
        "schema": "SPORTSEDGE_FREE_RESEARCH_V1",
        "status": stage["block_reason"],
        "sport": line.get("sport"),
        "game": stage["game_label"],
        "market": str(line.get("market") or "").upper(),
        "reason": stage["block_detail"],
        "research_only": True,
        "prepricing_audit": {
            "blocked": True,
            "block_reason": stage["block_reason"],
            "block_detail": stage["block_detail"],
            "factors": stage["factors"],
        },
        "input_index": input_index,
    }


def run_full(payload, *, now=None, as_of=None, historical=False, getter=None,
             auto_context=True, min_ev=0.02, lane="A", allow_manual_context=False,
             td_cache_dir=None, td_opener=None):
    """Separate real game, pitcher, and batter models, preserving original row order.

    Issues are UNTRUSTED odds intake: NEVER use submitted features,
    probabilities, starter/participation verification flags or simulation paths.
    Trusted data comes only from free public MLB endpoints.

    lane="A" (default) prices game rows market-blind; lane="B" explicitly
    requests the anchored view. allow_manual_context=False (default) fails
    closed on any manual context override in the intake rows.

    Canonical-path additions: NFL ANYTIME_TD is priced by the nflverse
    opportunity-decomposition engine (td_cache_dir/td_opener are its cache
    and fetch seams; with auto_context off and no explicit opener, cache
    misses fail closed instead of fetching). NFL team totals, period and
    alternate markets route to the derivative pricers, which price only
    from a joint score distribution embedded in a priced game result.
    MLB NRFI/YRFI are the first-inning binary at line 0.5. MLB F5 markets
    route to the F5 quote-binding stage (sportsedge.mlb_f5_quote_binding):
    quotes bind (source, book event ID, verified gamePk fixture, explicit
    FIRST_5 period, selection/line/price, 180s freshness, 120s pairing),
    the settlement basis is checked from the settlement code, features
    assemble from strictly-prior StatsAPI linescores, and rows then block
    at the F5 deployment gate (stage F5_STATE_CANDIDATE, eligible=false)
    with the specific F5_* reason named. Every other matrix market
    without a priced route resolves through sportsedge.canonical_coverage
    to a named taxonomy blocker.
    """
    rows = payload if isinstance(payload, list) else payload.get("lines")
    if not isinstance(rows, list):
        raise ValueError("LINES_MUST_BE_LIST")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("MODEL_NOW_TIMEZONE_REQUIRED")
    default_sport = payload.get("sport") if isinstance(payload, dict) else None
    game_indices, games, prop_indices, props = [], [], [], []
    coverage_indices, coverage_input = [], []
    f5_indices, f5_input = [], []
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError("LINE_MUST_BE_OBJECT")
        line = dict(raw)
        line["sport"] = str(line.get("sport") or default_sport or "").upper()
        market = str(line.get("market") or "").upper().strip()
        market = {"MONEYLINE":"ML","H2H":"ML","RUN_LINE":"SPREAD",
                  "GAME_TOTAL":"TOTAL","TOTALS":"TOTAL",
                  "TEAM_TOTAL":"TEAM_TOTALS"}.get(market,market)
        market = {
            "FIRST_HALF_TOTAL": "TOTAL_1H", "HALF_TOTAL": "TOTAL_1H",
            "1H_TOTAL": "TOTAL_1H", "FIRST_HALF_SPREAD": "SPREAD_1H",
            "1H_SPREAD": "SPREAD_1H", "FIRST_HALF_TEAM_TOTAL": "TEAM_TOTAL_1H",
            "1H_TEAM_TOTAL": "TEAM_TOTAL_1H",
        }.get(market, market)
        if line["sport"] != "MLB":
            # Full-game team totals route to the team/half derivative lane
            # for football. MLB TEAM_TOTALS keep the game-lane contract
            # (paired no-vig team-score heuristic + prepricing fixture gate).
            # The first-five derivative aliases are likewise non-MLB only:
            # MLB FIRST_FIVE_* rows belong to the dedicated F5 lane below
            # (normalize_f5_market claims them as F5_TOTALS/F5_TEAM_TOTALS),
            # and renaming them here would preempt that lane. For other
            # sports the derivative lane fails F5 markets closed.
            market = {"FIRST_FIVE_TOTAL": "F5_TOTAL",
                      "FIRST_FIVE_TEAM_TOTAL": "F5_TEAM_TOTAL",
                      "TEAM_TOTALS": "TEAM_TOTAL",
                      "TEAM_TOTAL_OVER_UNDER": "TEAM_TOTAL"}.get(market, market)
        if line["sport"] in {"NFL", "CFB"}:
            market = {
                "PASS_YARDS":"PLAYER_PASSING_YARDS",
                "PASSING_YARDS":"PLAYER_PASSING_YARDS",
                "PASS_TDS":"PLAYER_PASS_TDS",
                "PASSING_TDS":"PLAYER_PASSING_TDS",
                "PASS_ATTEMPTS":"PLAYER_PASS_ATTEMPTS",
                "COMPLETIONS":"PLAYER_COMPLETIONS",
                "INTERCEPTIONS":"PLAYER_INTERCEPTIONS",
                "RUSH_YARDS":"PLAYER_RUSHING_YARDS",
                "RUSHING_YARDS":"PLAYER_RUSHING_YARDS",
                "RUSH_ATTEMPTS":"PLAYER_RUSH_ATTEMPTS",
                "RECEIVING_YARDS":"PLAYER_RECEIVING_YARDS",
                "REC_YARDS":"PLAYER_RECEIVING_YARDS",
                "RECEPTIONS":"PLAYER_RECEPTIONS",
                "ANYTIME_TOUCHDOWN":"ANYTIME_TD",
                "ANYTIME_TD_SCORER":"ANYTIME_TD",
                "FIRST_TOUCHDOWN":"FIRST_TD",
                "FIRST_TD_SCORER":"FIRST_TD",
            }.get(market,market)
            line["market"] = market
        if line["sport"] == "MLB" and market in F5_INTAKE_ALIASES:
            market = F5_INTAKE_ALIASES[market]
            line["market"] = market
        if market in {"ML", "SPREAD", "TOTAL"} or (
            line["sport"] == "MLB" and market == "TEAM_TOTALS"
        ):
            game_indices.append(i)
            games.append(line)
            continue
        coverage_market = normalize_coverage_market(market)
        if coverage_market is not None:
            line["market"] = coverage_market
            coverage_indices.append(i)
            coverage_input.append(line)
            continue
        f5_market = (normalize_f5_market(market)
                     if line["sport"] == "MLB" else None)
        if f5_market is not None:
            # Composition resolution (stack chain x PR #2057): the market
            # name is canonicalized here, but F5 rows are NOT diverted to
            # the legacy phone F5 lane. They fall through to prop routing,
            # where the canonical F5 quote-binding lane owns them (quote
            # binding + settlement basis + deployment gate).
            line["market"] = f5_market
        prop_indices.append(i)
        props.append(line)

    if games:
        # Option 3: Prepricing adjustments stored separately from user context.
        # Strip any user-supplied prepricing_adjustments (never trusted).
        for line in games:
            line.pop("prepricing_adjustments", None)
        # Pre-pricing factor-ingestion stage: verified pulls BEFORE pricing.
        stages = stage_games(
            games, now=clock,
            getter=getter if auto_context else (lambda url: None),
            enforce_blocks=auto_context,
            as_of=as_of, historical=historical)
        # Build separate prepricing_adjustments objects (not merged into context)
        prepricing_by_index = {}
        game_results = [None] * len(games)
        clear_lines = []
        clear_game_pos = []
        for gpos, (line, st) in enumerate(zip(games, stages)):
            if st["blocked"]:
                game_results[gpos] = _prepricing_blocked_row(
                    line, st, game_indices[gpos])
                continue
            # System-verified adjustments: separate object with provenance
            # User-supplied context remains subject to allow_manual_context
            prepricing_by_index[gpos] = {
                "source": "SPORTSEDGE_PREPRICING_V1",
                "timestamp_utc": clock.astimezone(timezone.utc).isoformat(),
                "verification_status": "VERIFIED",
                "adjustments": dict(st["adjustments"]) if isinstance(st.get("adjustments"), dict) else {},
                "factors": list(st["factors"]) if isinstance(st.get("factors"), list) else [],
            }
            clear_lines.append(line)
            clear_game_pos.append(gpos)
        # Pass prepricing adjustments explicitly to the engine
        # The engine applies them separately from user context (no double-count)
        card = engine.run({"lines": clear_lines}, now=clock, as_of=as_of, historical=historical,
                          getter=getter, auto_context=auto_context, min_ev=min_ev,
                          lane=lane, allow_manual_context=allow_manual_context,
                          prepricing_adjustments=[prepricing_by_index.get(gpos) for gpos in clear_game_pos])
        priced = card.get("evaluated_rows") or []
        if len(priced) != len(clear_lines):
            raise ValueError("GAME_EVALUATED_ROWS_INCOMPLETE")
        for pos, gpos in enumerate(clear_game_pos):
            priced[pos]["input_index"] = game_indices[gpos]
            priced[pos]["prepricing_adjustments"] = prepricing_by_index[gpos]
            game_results[gpos] = priced[pos]
        priced_games = game_results
        # Option 3: Prepricing audit for transparency (separate from user context audit)
        def _audit_entry(gpos):
            pp = prepricing_by_index.get(gpos)
            if pp is not None:
                return {
                    "input_index": game_indices[gpos],
                    "blocked": False,
                    "adjustments": pp.get("adjustments", {}),
                    "verification_status": pp.get("verification_status", "NOT_APPLICABLE"),
                    "factors": pp.get("factors", []),
                }
            # Blocked: copy reason/detail/factors from the blocked stage row
            blocked_row = game_results[gpos] if gpos < len(game_results) else {}
            pa = blocked_row.get("prepricing_audit", {}) if isinstance(blocked_row, dict) else {}
            return {
                "input_index": game_indices[gpos],
                "blocked": True,
                "block_reason": pa.get("block_reason", "UNKNOWN"),
                "block_detail": pa.get("block_detail", ""),
                "factors": pa.get("factors", []),
                "adjustments": {},
                "verification_status": "NOT_APPLICABLE",
            }
        card["prepricing_factor_audit"] = {
            "schema": "SPORTSEDGE_PREPRICING_FACTOR_AUDIT_V1",
            "market_odds_as_features": "REJECTED_METHOD_NEVER_PRICED",
            "by_input_index": [_audit_entry(gpos) for gpos in range(len(games))],
        }
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
    f5_pos, f5_input = [], []
    first_pos, first_input = [], []
    first_originals = {}  # local -> original market, for NRFI/YRFI translation
    nfl_pos, nfl_input = [], []
    cfb_pos, cfb_input = [], []
    teamhalf_pos, teamhalf_input = [], []
    deriv_pos, deriv_input = [], []
    deriv_originals = {}  # local -> intake market, for ruling-translated rows
    td_pos, td_input = [], []
    others = {}
    for local, line in enumerate(props):
        market = str(line.get("market") or "").upper()
        if line["sport"] == "NFL" and market in _NFL_RULING_DERIVATIVE_TRANSLATION:
            # Owner ruling (Oct 13, 2026; see the constant): NFL team
            # totals and first-half markets go to the derivative stage,
            # never the team/half pricer.
            translated = dict(line)
            translated["market"] = _NFL_RULING_DERIVATIVE_TRANSLATION[market]
            deriv_originals[local] = market
            deriv_pos.append(local)
            deriv_input.append(translated)
        elif market in DERIVATIVES:
            teamhalf_pos.append(local)
            teamhalf_input.append(line)
        elif line["sport"] == "MLB" and market.startswith("PITCHER_"):
            pitcher_pos.append(local)
            pitcher_input.append(line)
        elif line["sport"] == "MLB" and (
            market.startswith("BATTER_") or
            market in {"SINGLES", "DOUBLES", "HITS_RUNS_RBIS", "H_R_RBI"}
        ):
            batter_pos.append(local)
            batter_input.append(line)
        elif line["sport"] == "MLB" and market in {"NRFI", "YRFI"}:
            # NRFI/YRFI ARE the first-inning binary at line 0.5
            # (NRFI = UNDER 0.5 first-inning runs, YRFI = OVER). Translate
            # into the first-inning engine's market; the engine enforces
            # the 0.5 line. A conflicting explicit side fails closed.
            side = str(line.get("side") or line.get("selection") or "").upper()
            derived_side = "UNDER" if market == "NRFI" else "OVER"
            if side in {"OVER", "UNDER"} and side != derived_side:
                others[local] = blocked(
                    line, "NRFI_YRFI_SIDE_CONFLICTS_WITH_MARKET")
                continue
            translated = dict(line)
            translated["market"] = "FIRST_INNING_RUNS"
            translated["side"] = derived_side
            if translated.get("line") in (None, ""):
                translated["line"] = 0.5
            first_pos.append(local)
            first_input.append(translated)
            first_originals[local] = market
        elif line["sport"] == "MLB" and market in F5_CANONICAL_MARKETS:
            f5_pos.append(local)
            f5_input.append(line)
        elif line["sport"] == "MLB" and market in FIRST_INNING_PHONE_MARKETS:
            first_pos.append(local)
            first_input.append(line)
        elif line["sport"] == "NFL" and market in NFL_DERIVATIVE_MARKETS:
            deriv_pos.append(local)
            deriv_input.append(line)
        elif line["sport"] == "NFL" and (
                market in NFL_ANYTIME_TD_MARKETS
                or market in NFL_FIRST_TD_MARKETS):
            td_pos.append(local)
            td_input.append(line)
        elif line["sport"] == "NFL" and market.startswith("PLAYER_"):
            nfl_pos.append(local)
            nfl_input.append(line)
        elif line["sport"] == "CFB" and market.startswith("PLAYER_"):
            cfb_pos.append(local)
            cfb_input.append(line)
        else:
            covered = coverage_blocked_row(line["sport"], market, line)
            others[local] = covered if covered is not None else blocked(
                line, "NO_VERIFIED_MODEL_FOR_THIS_MARKET")
    pitcher_results, pitcher_receipts = phone_pitcher_rows(
        pitcher_input, now=clock, getter=getter if auto_context else (lambda url: None))
    batter_results, batter_receipts = phone_batter_rows(
        batter_input, now=clock, getter=getter if auto_context else (lambda url: None))
    first_results, first_receipts = phone_first_inning_rows(
        first_input, now=clock, getter=getter if auto_context else (lambda url: None))
    # F5 stage: quote binding + settlement-basis gate + strictly-prior
    # feature assembly, then the F5 deployment gate. With auto_context
    # off, fetching is disabled and binding fails closed on the fixture
    # gate. The stage module is dependency-light at import time; its
    # StatsAPI/engine dependencies load lazily inside the stage.
    f5_results, f5_receipts = [], []
    if f5_input:
        try:
            f5_results, f5_receipts = phone_f5_binding_rows(
                f5_input, now=clock,
                getter=getter if auto_context else None,
                fetch_enabled=auto_context)
        except Exception as exc:
            f5_results = [{
                "status": "NO_MODEL_OR_MARKET",
                "reason": "NO_ENGINE: F5_BINDING_RUNTIME_UNAVAILABLE — "
                          f"{type(exc).__name__}: {exc}",
                "blocker": "NO_ENGINE",
                "blocker_detail": str(exc),
                "f5_reason": "F5_BINDING_RUNTIME_UNAVAILABLE",
                "coverage_market": line.get("market"),
                "sport": "MLB", "market": line.get("market"),
                "research_only": True, "official_authority": False,
                "model_p_authority": False, "staking_authority": False,
            } for line in f5_input]
    nfl_results, nfl_receipts = phone_nfl_player_rows(
        nfl_input, now=clock, getter=getter if auto_context else (lambda url: None))
    cfb_results, cfb_receipts = phone_cfb_player_rows(
        cfb_input, now=clock, getter=getter if auto_context else (lambda url: None))
    teamhalf_results, teamhalf_receipts = price_team_half_rows(
        teamhalf_input, now=clock, getter=getter if auto_context else (lambda url: None))
    if len(teamhalf_results) != len(teamhalf_input):
        raise ValueError("TEAM_HALF_RESULT_COUNT_MISMATCH")
    # Canonical derivative stage: NFL team totals / period / alternate rows
    # price only from a joint score distribution embedded in a priced game
    # result. The analytic game engine emits none today, so these rows
    # resolve through the pricers' own fail-closed guards (NO_ENGINE).
    # The stage modules are imported lazily and only when such rows exist:
    # this runner must stay importable AND runnable in the numpy/pandas-
    # free phone environment; if the runtime lacks those packages, the
    # rows fail closed with a named reason instead of crashing the card.
    deriv_results, deriv_receipts = [], []
    deriv_distribution_provenance = {}
    if deriv_input:
        try:
            from sportsedge.nfl_phone_derivative_pricing import (
                extract_distribution, fixture_key as derivative_fixture_key,
                phone_nfl_derivative_rows)
        except ImportError:
            deriv_results = [{
                "status": "NO_MODEL_OR_MARKET",
                "reason": "DERIVATIVE_ENGINE_RUNTIME_UNAVAILABLE",
                "blocker": "NO_ENGINE",
                "blocker_detail": "The derivative pricer package could not "
                                  "be imported in this runtime.",
                "sport": "NFL", "market": line.get("market"),
                "research_only": True, "official_authority": False,
                "model_p_authority": False, "staking_authority": False,
            } for line in deriv_input]
        else:
            distributions = {}
            for game_line, game_result in zip(games, priced_games):
                dist = extract_distribution(game_result)
                if dist:
                    key = derivative_fixture_key(
                        game_line.get("away"), game_line.get("home"))
                    distributions[key] = dist
                    # A derivative row inherits the provenance of the
                    # distribution that priced it: an anchored source can
                    # never launder itself into an independent derivative.
                    source_prov = determine_provenance(game_result)
                    if source_prov is not None:
                        deriv_distribution_provenance[key] = source_prov
            deriv_results, deriv_receipts = phone_nfl_derivative_rows(
                deriv_input, distributions=distributions, now=clock)
    # ANYTIME_TD stage: nflverse history through the engine's own opener
    # seam. With auto_context off and no explicit opener, a cache miss
    # fails closed instead of fetching (no-fetch means no-fetch). Same
    # lazy-import discipline as the derivative stage (pandas-backed).
    td_results, td_receipts = [], []
    if td_input:
        try:
            from sportsedge.nfl_phone_anytime_td_pricing import (
                phone_anytime_td_rows)
        except ImportError:
            td_results = [{
                "status": "NO_MODEL_OR_MARKET",
                "reason": "TD_ENGINE_RUNTIME_UNAVAILABLE",
                "blocker": "NO_DATA",
                "blocker_detail": "The anytime-TD engine package could not "
                                  "be imported in this runtime.",
                "sport": "NFL", "market": line.get("market"),
                "player_name": line.get("player_name") or line.get("label"),
                "research_only": True, "official_authority": False,
                "model_p_authority": False, "staking_authority": False,
            } for line in td_input]
        else:
            def _td_unavailable_opener(url, *args, **kwargs):
                raise OSError("TD_HISTORY_FETCH_DISABLED_IN_NO_FETCH_MODE")
            td_results, td_receipts = phone_anytime_td_rows(
                td_input, now=clock, cache_dir=td_cache_dir,
                opener=td_opener if td_opener is not None else (
                    None if auto_context else _td_unavailable_opener))
    if len(deriv_results) != len(deriv_input):
        raise ValueError("DERIVATIVE_RESULT_COUNT_MISMATCH")
    if len(td_results) != len(td_input):
        raise ValueError("ANYTIME_TD_RESULT_COUNT_MISMATCH")
    if len(nfl_results) != len(nfl_input) or len(cfb_results) != len(cfb_input):
        raise ValueError("FOOTBALL_RESULT_COUNT_MISMATCH")
    if len(f5_results) != len(f5_input):
        raise ValueError("F5_RESULT_COUNT_MISMATCH")
    if len(pitcher_results) != len(pitcher_input):
        raise ValueError("PITCHER_RESULT_COUNT_MISMATCH")
    coverage_results, coverage_receipts = phone_coverage_rows(
        coverage_input, now=clock,
        getter=getter if auto_context else (lambda url: None),
        auto_context=auto_context, min_ev=min_ev)
    if len(coverage_results) != len(coverage_input):
        raise ValueError("COVERAGE_RESULT_COUNT_MISMATCH")
    if len(batter_results) != len(batter_input):
        raise ValueError("BATTER_RESULT_COUNT_MISMATCH")
    if len(first_results) != len(first_input):
        raise ValueError("FIRST_INNING_RESULT_COUNT_MISMATCH")
    modeled_props = [None]*len(props)
    for local, result in zip(pitcher_pos, pitcher_results):
        modeled_props[local] = result
    for local, result in zip(batter_pos, batter_results):
        modeled_props[local] = result
    for local, result in zip(first_pos, first_results):
        original = first_originals.get(local)
        if original is not None:
            # Restore the intake market label (NRFI/YRFI); the probability
            # came from the underlying FIRST_INNING_RUNS binary at 0.5.
            result = dict(result)
            result["market"] = original
            result["underlying_market"] = "FIRST_INNING_RUNS"
            result["priced_via"] = "FIRST_INNING_RUNS_BINARY_AT_0_5"
        modeled_props[local] = result
    for local, result in zip(f5_pos, f5_results):
        modeled_props[local] = result
    for local, result in zip(deriv_pos, deriv_results):
        original = deriv_originals.get(local)
        if original is not None and result.get("market") != original:
            # Restore the intake market label (cf. the NRFI/YRFI
            # restoration above); the derivative stage's canonical
            # market name stays on the row for audit.
            result = dict(result)
            result["derivative_market"] = result.get("market")
            result["market"] = original
        modeled_props[local] = result
    for local, result in zip(td_pos, td_results):
        modeled_props[local] = result
    for local, result in zip(nfl_pos, nfl_results):
        modeled_props[local] = result
    for local, result in zip(cfb_pos, cfb_results):
        modeled_props[local] = result
    for local, result in zip(teamhalf_pos, teamhalf_results):
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
    for i, result in zip(coverage_indices, coverage_results):
        result["input_index"] = i
        evaluated[i] = result
    for i, result in zip(f5_indices, f5_results):
        result["input_index"] = i
        evaluated[i] = result
    if any(r is None for r in evaluated):
        raise ValueError("EVALUATED_ROWS_REQUIRED_TO_AVOID_FALSE_FACTOR_COVERAGE")
    # Provenance gate (Isaac's architecture-conflict ruling, Oct 12 2026):
    # every priced row on this canonical card carries an explicit
    # INDEPENDENT / MARKET_ANCHORED provenance, identifiable from the card
    # output alone. Anchored rows are capped at WATCH; a priced row whose
    # provenance cannot be determined fails closed
    # (PROVENANCE_UNDETERMINED) -- it never defaults to independent. This
    # runs BEFORE the candidate/watchlist surfaces below are built, so a
    # demoted row can never slip into a play list.
    apply_play_gate(evaluated,
                    distribution_provenance=deriv_distribution_provenance)
    card.setdefault("play_gate", {
        "rule": "INDEPENDENT_PROBABILITY_REQUIRED_FOR_PLAY",
        "anchored_max_surface": "WATCH",
        "anchored_ev_in_edges_lists": "SUPPRESSED",
        "undetermined_provenance": "FAIL_CLOSED",
    })
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
    card["source_receipts"] = (list(card.get("source_receipts") or [])
                              + pitcher_receipts + batter_receipts
                              + first_receipts
                              + nfl_receipts + cfb_receipts
                              + coverage_receipts + f5_receipts + teamhalf_receipts
                              + deriv_receipts + td_receipts)
    card["prop_model_status"] = {
        "pitcher_engine":"MLB_PITCHER_JOINT_EMPIRICAL_BAYES",
        "batter_engine":"MLB_BATTER_EMPIRICAL_GAMELOG",
        "first_inning_engine":"MLB_FIRST_INNING_TEAM_RATES_POISSON_JEFFREYS",
        "mlb_f5_engine":"SHARED_F5_ENGINE_VIA_MLB_F5_QUOTE_BINDING_V1_DEPLOYMENT_GATED_F5_STATE_CANDIDATE",
        "coverage_engine":"FREE_COVERAGE_EXTENSION_MLB_3WAY_QUARTERS_MARGIN_UNVALIDATED",
        "f5_engine":"MLB_F5_EMPIRICAL_LINESCORE_UNVALIDATED",
        "nfl_player_engine":"ESPN_NAMED_HISTORICAL_GAMELOG_WATCH_ONLY",
        "cfb_player_engine":"ESPN_NAMED_HISTORICAL_GAMELOG_WATCH_ONLY",
        "team_half_engine":"FREE_ESPN_SCORE_DERIVATIVE_UNVALIDATED_PERIOD_SPLIT",
        "team_half_period_fitted":False,
        "nfl_anytime_td_engine":"NFLVERSE_OPPORTUNITY_DECOMPOSITION_UNVALIDATED",
        "nfl_derivative_engine":"WIRED_PRICERS_DISTRIBUTION_REQUIRED",
        "first_inning_nrfi_yrfi":"FIRST_INNING_RUNS_BINARY_ALIAS_AT_0_5",
        "free_public_history":True,
        "model_vs_close_validated":False,
        "phone_odds_freshness_required":True,
        "no_generic_player_prior":True,
        "unsupported_player_markets_blocked":len(card["prop_unpriced"]),
        "statcast":"NOT_WIRED",
        "next_gen":"NOT_WIRED",
        "nfl_cfb_player":"ESPN_NAMED_GAMES_ONLY_PARTICIPATION_NOT_VERIFIED",
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
                      "pricing_provenance":result.get("pricing_provenance"),
                      "factors":factors})
    card["factor_coverage"] = {
        "schema":"SPORTSEDGE_FACTOR_COVERAGE_V1",
        "coverage_is_not_validation":True,
        "by_input_index":audit,
        "status_counts":dict(sorted(totals.items())),
        "advanced_metrics":{
            "statcast":UNWIRED,"next_gen":UNWIRED,"coaching":UNWIRED,
            "travel":UNWIRED,"player_props":
            "MLB_PITCHER_BATTER_AND_ESPN_NAMED_FOOTBALL_HISTORY_UNVALIDATED",
            "team_half":"UNFITTED_RESEARCH_DERIVATIVE_NO_WAGER_AUTHORITY",
        },
    }
    # The 89-market coverage pass: every matrix market resolves through
    # this one canonical path to a priced route or a named taxonomy
    # blocker. Coverage is not validation; statuses are carried, not earned.
    card["canonical_coverage"] = coverage_summary()
    # Surface every catalog market on the same free phone research card.
    # This is presentation ONLY: absent quotes and unsupported model families
    # remain explicit blockers. No probabilities or quotes are synthesized.
    if any(str((row.get("sport") or default_sport or "")).upper() == "MLB"
           for row in rows):
        from sportsedge.mlb_phone_full_board import phone_market_board
        labeled_inputs = [
            {**raw, "sport": str(raw.get("sport") or default_sport or "").upper()}
            for raw in rows
        ]
        card["mlb_full_board"] = phone_market_board(labeled_inputs, evaluated)
        card["summary"]["mlb_market_coverage"] = dict(card["mlb_full_board"]["input_coverage"])
    card["runner"]="RUN_IT_FULL_MLB_AND_NAMED_FOOTBALL_PLAYER_HISTORIES_V1"
    return card


def main(argv=None):
    p = argparse.ArgumentParser(description="Free research card plus complete truthful factor-coverage audit")
    p.add_argument("--lines", required=True, type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--min-ev", type=float, default=0.02)
    p.add_argument("--lane", choices=["A", "B"], default="A",
                   help="Primary pricing lane for game rows: A=independent (default), B=anchored")
    p.add_argument("--allow-manual-context", action="store_true",
                   help="Allow intake rows to override verified context factors (labeled in audit)")
    p.add_argument("--as-of", help="Point-in-time clock (ISO-8601); defaults to now")
    p.add_argument("--historical", action="store_true",
                   help="Repricing history: refuse current-state sources that cannot be snapshotted as-of")
    args = p.parse_args(argv)
    if not 0 <= args.min_ev <= 0.15:
        p.error("min-ev must be between 0 and 0.15")
    card = run_full(json.loads(args.lines.read_text(encoding="utf-8")),
                    auto_context=not args.no_fetch, min_ev=args.min_ev,
                    lane=args.lane, allow_manual_context=args.allow_manual_context,
                    as_of=args.as_of, historical=args.historical)
    rendered = json.dumps(card, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
