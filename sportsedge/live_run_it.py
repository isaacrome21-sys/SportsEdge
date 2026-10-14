"""LIVE RUN IT: phone-shaped live/in-game research intake.

Flow: Isaac sends live lines, gets a research card back -- the same intake
shape as artifacts/run_it_full.py. RESEARCH-ONLY: no auto-betting, no bet
execution, no bet-placement code paths anywhere in this module (or repo).

Per line:
  1. Normalize sport/market/side (same aliases as the pregame runner).
  2. GAME markets (ML/SPREAD/TOTAL) only. Everything else is blocked with
     an explicit reason code (player props NOT_WIRED, first-inning markets
     deferred to Phase 1, etc.).
  3. Resolve the live event (game_pk / event_id, or team pair) and fetch
     the current live state via sportsedge.live_poll (free sources only).
  4. HARD STALENESS FAIL-CLOSED: state older than
     LIVE_STATE_STALENESS_THRESHOLD_SECONDS (60s) -> STALE_LIVE_DATA.
     Only LIVE status is priced; FINAL/PREGAME/SUSPENDED are blocked.
  5. Reconstruct the verified pregame score means as of kickoff (the
     pregame context clock is pinned to 5 minutes before kickoff so no
     post-kickoff information can leak into the means).
  6. Reprice from the current state (sportsedge.live_reprice, market-blind).
  7. Compare against the supplied live line -> EV. Statuses are
     LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED / LIVE_BELOW_THRESHOLD --
     never anything called "verified": nothing is verified until it
     passes the backtest harness.

Market-blind: the supplied live line/price is used ONLY for EV
comparison, never as a model input (LIVE_POLICY_V1 forbidden features).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from artifacts.free_models import (
    CONTEXT_KEYS,
    PublicContext,
    bounded,
    context_for,
    numeric,
    odds_decimal,
    score_means,
)

from .live_poll import LivePoller, LiveFetchError, LiveRateLimited
from .live_participation import (
    ParticipationError,
    build_football_participation_report,
    check_football_participation,
    mlb_pitcher_participation,
)
from .live_reprice import (
    NOT_WIRED_LIVE_FIELDS,
    LiveReprice,
    LiveRepriceError,
    reprice_football,
    reprice_mlb,
)
from .live_state import (
    LIVE_STATE_STALENESS_THRESHOLD_SECONDS,
    FootballGameState,
    LiveStateError,
    MLBGameState,
)
from sportsedge.registry_gate import gate_and_stamp as _registry_gate_and_stamp


CARD_SCHEMA = "SPORTSEDGE_LIVE_RESEARCH_CARD_V1"
RUNNER_NAME = "RUN_IT_LIVE_INPLAY_RESEARCH_V1"

GAME_MARKETS = {"ML", "SPREAD", "TOTAL"}
MARKET_ALIASES = {
    "MONEYLINE": "ML", "H2H": "ML",
    "RUN_LINE": "SPREAD", "GAME_TOTAL": "TOTAL", "TOTALS": "TOTAL",
}

FIRST_INNING_MARKETS = {
    "NRFI", "YRFI", "FIRST_INNING_RUNS", "FIRST_INNING_HITS",
    "FIRST_INNING_HR", "FIRST_INNING_TEAM_RUNS", "FIRST_INNING_PITCHES",
    "FIRST_1_INNINGS",
}

PLAYER_MARKET_PREFIXES = ("PLAYER_", "PITCHER_", "BATTER_")

PLAYER_NOT_WIRED_REASONS = {
    "PLAYER_": ("LIVE_PLAYER_PROP_NOT_WIRED: in-game player-prop repricing "
                "requires a verified within-game stat-projection path; only "
                "GAME markets (ML/SPREAD/TOTAL) are priced live. Queued."),
    "PITCHER_": ("LIVE_PITCHER_PROP_NOT_WIRED: in-game pitcher-prop repricing "
                 "requires verified pitch-count/bullpen state modeling; not "
                 "built. Queued."),
    "BATTER_": ("LIVE_BATTER_PROP_NOT_WIRED: in-game batter-prop repricing "
                "requires verified remaining-plate-appearance modeling; not "
                "built. Queued."),
}


def _normalize_line(raw: Mapping[str, Any], default_sport: str | None) -> dict[str, Any]:
    line = dict(raw)
    line["sport"] = str(line.get("sport") or default_sport or "").upper()
    market = str(line.get("market") or "").upper().strip()
    line["market"] = MARKET_ALIASES.get(market, market)
    side_raw = str(line.get("side") or line.get("selection") or "").strip().upper()
    line["side_raw"] = side_raw
    return line


def _resolve_side(line: dict[str, Any], home: str, away: str) -> str | None:
    side_raw = line["side_raw"]
    market = line["market"]
    if market == "TOTAL":
        return side_raw if side_raw in ("OVER", "UNDER") else None
    if side_raw in ("HOME", "AWAY"):
        return side_raw
    key = PublicContext.key
    if key(side_raw) == key(home):
        return "HOME"
    if key(side_raw) == key(away):
        return "AWAY"
    return None


def _blocked_row(index: int, line: dict[str, Any], status: str,
                 reason: str) -> dict[str, Any]:
    return {
        "input_index": index,
        "status": status,
        "reason": reason,
        "sport": line.get("sport"),
        "market": line.get("market"),
        "side": line.get("side_raw"),
        "line": line.get("line"),
        "odds_american": line.get("odds", line.get("price")),
        "research_only": True,
    }


def _classify_unsupported(line: dict[str, Any]) -> tuple[str, str]:
    market = str(line.get("market") or "")
    if market in FIRST_INNING_MARKETS or "FIRST_INNING" in market or market in ("NRFI_YRFI",):
        return ("LIVE_FIRST_INNING_DEFERRED",
                "LIVE_FIRST_INNING_DEFERRED: live first-inning markets wait "
                "on Phase 1 core first-inning work "
                "(feat/mlb-first-inning-20261011); not duplicated here.")
    for prefix, reason in PLAYER_NOT_WIRED_REASONS.items():
        if market.startswith(prefix):
            return ("NOT_WIRED_LIVE_PLAYER_PROP", reason)
    return ("NO_VERIFIED_MODEL_FOR_THIS_MARKET",
            "NO_VERIFIED_MODEL_FOR_THIS_MARKET: live pricing covers GAME "
            "markets (ML/SPREAD/TOTAL) only")


def _pregame_means(sport: str, away: str, home: str, kickoff: datetime,
                   row: Mapping[str, Any], getter: Callable | None,
                   receipts: list[dict[str, Any]]) -> tuple[float, float, list[str]]:
    """Reconstruct verified pregame means with the context clock pinned to
    just before kickoff, so no post-kickoff information can leak in."""
    pre_now = kickoff - timedelta(minutes=5)
    provider = PublicContext(now=pre_now, getter=getter)
    context = {k: 0.0 for k in CONTEXT_KEYS[sport]}
    notes: list[str] = []
    try:
        inferred, verified_start, notes = context_for(
            sport, away, home, kickoff, provider, row)
    except Exception as exc:  # fail closed, never guess
        raise LiveRepriceError(
            "LIVE_PREGAME_CONTEXT_UNVERIFIED:" + type(exc).__name__) from exc
    if verified_start is None:
        raise LiveRepriceError(
            "LIVE_PREGAME_CONTEXT_UNVERIFIED:" + ",".join(notes))
    context.update(inferred)
    # Manual overrides, same contract as the pregame runner.
    overrides = row.get("context") or {}
    for key in context:
        val = overrides.get(key, row.get(key))
        if val is not None:
            n = numeric(val, key)
            if abs(n) > 15:
                raise LiveRepriceError("CONTEXT_ADJUSTMENT_UNBOUNDED:" + key)
            context[key] = n
    receipts.extend(provider.receipts)
    return (*score_means(sport, context), ["PREGAME_CONTEXT_PINNED_TO_KICKOFF_MINUS_5MIN"] + notes)


def _ev_row(*, index: int, line: dict[str, Any], state_summary: str,
            state_observed_at: str, state_age_s: float,
            home_mean: float, away_mean: float, reprice: LiveReprice,
            receipts: list[dict[str, Any]], min_ev: float,
            pregame_notes: list[str],
            participation: dict[str, Any]) -> dict[str, Any]:
    price = numeric(line.get("odds", line.get("price")), "odds")
    dec = odds_decimal(line.get("odds", line.get("price")))
    win, push = reprice.model_p, reprice.push_p
    loss = bounded(1 - win - push, 0, 1)
    ev = win * (dec - 1) - loss
    breakeven = (1 - push) / dec
    selection = (line.get("side_raw") or "")
    status = ("LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED"
              if ev >= min_ev else "LIVE_BELOW_THRESHOLD")
    return {
        "input_index": index,
        "status": status,
        "sport": line["sport"],
        "market": reprice.market,
        "side": reprice.side,
        "selection": selection,
        "line": reprice.line,
        "odds_american": int(price),
        "live_state": state_summary,
        "live_state_observed_at_utc": state_observed_at,
        "live_state_age_seconds": round(state_age_s, 1),
        "live_state_freshness": ("FRESH"
                                 if state_age_s <= LIVE_STATE_STALENESS_THRESHOLD_SECONDS
                                 else "STALE"),
        "estimate_p": round(win, 6),
        "push_p": round(push, 6),
        "loss_p": round(loss, 6),
        "book_break_even_p": round(breakeven, 6),
        "edge_over_break_even_pp": round(100 * (win - breakeven), 3),
        "ev_per_dollar": round(ev, 6),
        "home_mean_pregame": round(home_mean, 3),
        "away_mean_pregame": round(away_mean, 3),
        "remaining_fraction": round(reprice.remaining_fraction, 4),
        "pregame_context_notes": pregame_notes,
        "not_wired_live_fields": [
            {"field": f, "reason": r} for f, r in reprice.not_wired],
        "model_assumptions": list(reprice.assumptions),
        "participation": participation,
        "model_validation": "NOT_PROVEN_VS_CLOSE",
        "market_blind": True,
        "research_only": True,
        "model_p_authority": False,
        "official_authority": False,
        "staking_authority": False,
        "bet_execution": False,
        "source_receipts": receipts,
    }


def _live_factor_audit(result: dict[str, Any]) -> dict[str, Any]:
    status = result.get("status") or ""
    priced = status in ("LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED",
                        "LIVE_BELOW_THRESHOLD")
    if not priced:
        return {
            "live_state": {"status": "NOT_PRICED",
                           "detail": result.get("reason") or status},
            "pregame_means": {"status": "NOT_PRICED", "detail": "n/a"},
            "market_blind": {"status": "NOT_APPLICABLE", "detail": "n/a"},
            "state_field_pricing": {"status": "NOT_APPLICABLE", "detail": "n/a"},
            "participation": {"status": "NOT_PRICED",
                              "detail": result.get("reason") or status},
            "validation": {"status": "NOT_APPLICABLE", "detail": "n/a"},
        }
    participation = result.get("participation") or {}
    check = participation.get("check")
    participation_factor = {
        "DIAGNOSTIC_ONLY": {
            "status": "VERIFIED_DISPLAY_ONLY",
            "detail": ("MLB probable-vs-current pitcher verified from the "
                       "live feed; changes are routine, reliever impact "
                       "NOT_WIRED")},
        "PARTICIPATION_OK": {
            "status": "VERIFIED_NO_MIDGAME_QB_CHANGE",
            "detail": str((participation.get("detail") or {})
                          .get("reason") or "")},
        "ASSUMED_NOT_VERIFIED": {
            "status": "ASSUMED_NOT_VERIFIED",
            "detail": str((participation.get("detail") or {})
                          .get("assumption") or "")},
    }.get(check, {"status": "UNKNOWN",
                  "detail": "participation check outcome unrecognized"})
    return {
        "live_state": {
            "status": "VERIFIED_FRESH",
            "detail": ("State fetched from free provider at "
                       + str(result.get("live_state_observed_at_utc"))
                       + f"; age {result.get('live_state_age_seconds')}s <= "
                       f"{LIVE_STATE_STALENESS_THRESHOLD_SECONDS}s threshold"),
        },
        "pregame_means": {
            "status": "VERIFIED_RECONSTRUCTED",
            "detail": ("Pregame means reconstructed from free public context "
                       "with the context clock pinned to kickoff-5min "
                       "(no post-kickoff leakage)"),
        },
        "market_blind": {
            "status": "VERIFIED",
            "detail": ("Live line/price never enters the model "
                       "(LIVE_POLICY_V1 forbidden features); used only for "
                       "downstream EV comparison"),
        },
        "state_field_pricing": {
            "status": "PARTIAL_SCORE_AND_TIME_ONLY",
            "detail": ("Pricing uses current score + remaining time/outs "
                       "only; " + str(len(result.get("not_wired_live_fields")
                                           or [])) + " state fields parsed "
                       "but NOT_WIRED (see not_wired_live_fields)"),
        },
        "participation": participation_factor,
        "validation": {
            "status": "NOT_VALIDATED_IN_HARNESS",
            "detail": ("MLB live ML: harness replay verdict in card "
                       "validation_status; NFL/CFB live repricing is "
                       "UNVALIDATED (no archived in-game state from free "
                       "sources)"),
        },
    }


def run_live_full(payload: Mapping[str, Any] | list,
                  *, now: datetime | None = None,
                  getter: Callable | None = None,
                  min_ev: float = 0.02) -> dict[str, Any]:
    """Price live GAME-market lines from current free-provider game state."""
    rows = payload if isinstance(payload, list) else payload.get("lines")
    if not isinstance(rows, list):
        raise ValueError("LINES_MUST_BE_LIST")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("MODEL_NOW_TIMEZONE_REQUIRED")
    default_sport = payload.get("sport") if isinstance(payload, dict) else None

    poller = LivePoller(getter=getter, now=lambda: clock)
    # Event-level caches so one card = one state fetch + one means build.
    state_cache: dict[str, Any] = {}
    means_cache: dict[str, Any] = {}
    participation_cache: dict[str, Any] = {}
    # A 429 is a hard stop for the provider: once hit, no further provider
    # calls are made for this card; remaining rows block immediately.
    provider_halted = False

    evaluated: list[dict[str, Any]] = []
    card_receipts: list[dict[str, Any]] = []

    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError("LINE_MUST_BE_OBJECT")
        line = _normalize_line(raw, default_sport)
        sport, market = line["sport"], line["market"]
        if provider_halted:
            evaluated.append(_blocked_row(
                i, line, "LIVE_PROVIDER_RATE_LIMITED",
                "LIVE_PROVIDER_RATE_LIMITED:provider halted after 429"))
            continue

    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError("LINE_MUST_BE_OBJECT")
        line = _normalize_line(raw, default_sport)
        sport, market = line["sport"], line["market"]
        if sport not in ("MLB", "NFL", "CFB"):
            evaluated.append(_blocked_row(
                i, line, "NO_VERIFIED_MODEL_FOR_THIS_MARKET",
                f"UNSUPPORTED_SPORT:{sport}"))
            continue
        if market not in GAME_MARKETS:
            status, reason = _classify_unsupported(line)
            evaluated.append(_blocked_row(i, line, status, reason))
            continue
        if market != "ML" and line.get("line") is None:
            evaluated.append(_blocked_row(
                i, line, "NO_VERIFIED_MODEL_FOR_THIS_MARKET",
                "LINE_REQUIRED"))
            continue
        try:
            result = _price_live_line(
                i, line, poller, clock, state_cache, means_cache,
                participation_cache, min_ev)
        except LiveRateLimited as exc:
            provider_halted = True
            result = _blocked_row(i, line, "LIVE_PROVIDER_RATE_LIMITED",
                                  f"LIVE_PROVIDER_RATE_LIMITED:{exc}")
        except (LiveStateError, LiveRepriceError, LiveFetchError,
                ParticipationError) as exc:
            reason = str(exc)
            status = reason.split(":")[0]
            if status == "STALE_LIVE_DATA" or "STALE" in reason:
                status = "STALE_LIVE_DATA"
            result = _blocked_row(i, line, status, reason)
        except (ValueError, TypeError) as exc:
            result = _blocked_row(i, line, "LIVE_PRICING_ERROR",
                                  f"LIVE_PRICING_ERROR:{type(exc).__name__}")
        evaluated.append(result)

    counts = dict(sorted(Counter(r.get("status") or "MISSING_STATUS"
                                 for r in evaluated).items()))
    card = {
        "schema": CARD_SCHEMA,
        "as_of_utc": clock.astimezone(timezone.utc).isoformat(),
        "min_ev": min_ev,
        "evaluated_rows": evaluated,
        "live_candidates": sorted(
            [r for r in evaluated
             if r.get("status") == "LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED"],
            key=lambda r: -r["ev_per_dollar"]),
        "live_watchlist": sorted(
            [r for r in evaluated if r.get("status") == "LIVE_BELOW_THRESHOLD"],
            key=lambda r: -r.get("ev_per_dollar", -1)),
        "live_unpriced": [r for r in evaluated
                          if r.get("status") not in (
                              "LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED",
                              "LIVE_BELOW_THRESHOLD")],
        "summary": {"rows": len(rows), "edges": 0, "status_counts": counts},
        "factor_coverage": {
            "schema": "SPORTSEDGE_LIVE_FACTOR_COVERAGE_V1",
            "coverage_is_not_validation": True,
            "by_input_index": [
                {"input_index": r["input_index"],
                 "status": r.get("status"),
                 "sport": r.get("sport"),
                 "market": r.get("market"),
                 "factors": _live_factor_audit(r)}
                for r in evaluated
            ],
        },
        "validation_status": {
            # Filled by scripts/validate_live_mlb_replay.py; the card
            # carries the latest known verdicts, never a claim of proof.
            "mlb_live_ml": "HARNESS_REPLAY_SEE_VALIDATION_REPORT",
            "nfl_cfb_live": ("UNVALIDATED_NO_ARCHIVED_IN_GAME_STATE: ESPN "
                             "does not retain completed-game live situation; "
                             "blocked pending a free historical "
                             "play-by-play source"),
        },
        "not_wired_live_fields": [
            {"field": f, "reason": r} for f, r in NOT_WIRED_LIVE_FIELDS],
        "research_only": True,
        "authority": {"research_only": True, "official": False,
                      "model_p": False, "staking": False,
                      "bet_execution": False},
        "runner": RUNNER_NAME,
        "staleness_policy": {
            "live_state_staleness_threshold_seconds":
                LIVE_STATE_STALENESS_THRESHOLD_SECONDS,
            "poll_cadence_seconds": 30,
            "note": ("State older than the threshold is STALE_LIVE_DATA: "
                     "no price, never guessed or extrapolated."),
        },
    }
    # t118: shared runtime registry gate (blocked/unregistered -> no price).
    return _registry_gate_and_stamp(card, None, "sportsedge/live_run_it.py")


def _event_key(line: dict[str, Any]) -> str:
    sport = line["sport"]
    if sport == "MLB" and line.get("game_pk"):
        return f"MLB:pk:{line['game_pk']}"
    if line.get("event_id"):
        return f"{sport}:eid:{line['event_id']}"
    game = str(line.get("game") or "")
    if " @ " in game:
        away, home = (s.strip() for s in game.split(" @ ", 1))
    else:
        away, home = str(line.get("away") or ""), str(line.get("home") or "")
    date = str(line.get("date") or "")
    return f"{sport}:teams:{away}@{home}:{date}"


def _price_live_line(index: int, line: dict[str, Any], poller: LivePoller,
                     clock: datetime, state_cache: dict, means_cache: dict,
                     participation_cache: dict,
                     min_ev: float) -> dict[str, Any]:
    sport = line["sport"]
    key = _event_key(line)
    receipts: list[dict[str, Any]] = []

    # -- 1. live state -------------------------------------------------
    if key not in state_cache:
        if sport == "MLB":
            game_pk = line.get("game_pk")
            if game_pk is not None:
                state, receipt = poller.fetch_mlb_state(int(game_pk))
            else:
                game = str(line.get("game") or "")
                if " @ " in game:
                    away_nm, home_nm = (s.strip()
                                        for s in game.split(" @ ", 1))
                else:
                    away_nm = str(line.get("away") or "")
                    home_nm = str(line.get("home") or "")
                date = str(line.get("date") or clock.date().isoformat())
                pk, discovery = poller.discover_mlb_game(
                    home=home_nm, away=away_nm, date=date)
                receipts.append(discovery)
                state, receipt = poller.fetch_mlb_state(pk)
        else:
            state, receipt = poller.fetch_football_state(
                sport, event_id=line.get("event_id"),
                home=line.get("home"), away=line.get("away"))
        receipts.append(receipt)
        state_cache[key] = (state, receipts)
    state, receipts = state_cache[key]
    receipts = list(receipts)

    age_s = state.age_seconds(clock)
    stale_reason = state.staleness_reason(clock)
    if stale_reason is not None:
        raise LiveStateError(stale_reason)
    if not state.is_live():
        raise LiveRepriceError(f"GAME_NOT_LIVE:{state.status}")

    # -- 1b. in-game participation verification (fail-closed) ------------
    # A mid-game exit by a key participant invalidates the pregame means.
    # See sportsedge.live_participation for the full rule.
    kickoff = state.kickoff
    if kickoff is None:
        raise LiveRepriceError("LIVE_PREGAME_CONTEXT_UNVERIFIED:KICKOFF_UNKNOWN")
    participation: dict[str, Any]
    if key not in participation_cache:
        if sport == "MLB":
            pitching_side = "home" if state.half == "top" else "away"
            probable = (state.probable_pitcher_home if pitching_side == "home"
                        else state.probable_pitcher_away)
            diag = mlb_pitcher_participation(
                probable, state.pitcher_id, state.pitcher_name,
                pitching_side, state.inning)
            participation = {
                "policy": ("MLB_PITCHER_DIAGNOSTIC: current pitcher verified "
                           "every pitch; changes are routine, reliever "
                           "impact NOT_WIRED"),
                "check": "DIAGNOSTIC_ONLY",
                "detail": diag,
            }
        elif sport == "NFL":
            try:
                summary, summary_receipt = poller.fetch_espn_summary(
                    sport, state.event_id)
                receipts.append(summary_receipt)
            except (LiveFetchError,) as exc:
                # The verification source itself failed: that is
                # LIVE_PARTICIPATION_UNVERIFIED, not a generic fetch error.
                # (LiveRateLimited is NOT caught here: a 429 is a hard stop
                # for the provider and must propagate.)
                summary, summary_receipt = None, {
                    "url": "ESPN_SUMMARY:" + str(state.event_id),
                    "status": "FETCH_FAILED",
                    "reason": type(exc).__name__,
                }
                receipts.append(summary_receipt)
            report = build_football_participation_report(
                sport, state.event_id, summary, home_team=state.home_team,
                away_team=state.away_team, now=clock)
            outcome, detail = check_football_participation(report, kickoff)
            participation = {
                "policy": ("NFL_REQUIRED: ESPN summary injury feed must "
                           "verify no mid-game QB Out"),
                "check": outcome,
                "detail": detail,
            }
            if outcome != "PARTICIPATION_OK":
                participation_cache[key] = participation
                raise LiveRepriceError(detail["reason"])
        else:  # CFB
            participation = {
                "policy": ("CFB_NOT_WIRED: ESPN CFB summary carries no "
                           "injuries section on the free endpoint; no "
                           "verifiable in-game participation source exists"),
                "check": "ASSUMED_NOT_VERIFIED",
                "detail": {
                    "assumption": ("PARTICIPATION_ASSUMED_UNCHANGED_SINCE_KICKOFF: "
                                   "no free source verifies CFB in-game "
                                   "personnel; a mid-game QB/injury change "
                                   "the feeds don't report would make this "
                                   "price stale"),
                },
            }
        participation_cache[key] = participation
    participation = participation_cache[key]
    if isinstance(participation.get("check"), str) and participation["check"] in (
            "LIVE_PARTICIPATION_CHANGE_UNPRICED", "LIVE_PARTICIPATION_UNVERIFIED"):
        raise LiveRepriceError(participation["detail"]["reason"])

    # -- 2. pregame means (context clock pinned to kickoff-5min) -------
    if key not in means_cache:
        mean_receipts: list[dict[str, Any]] = []
        home_mean, away_mean, notes = _pregame_means(
            sport, state.away_team, state.home_team, kickoff, line,
            poller._get_json, mean_receipts)
        means_cache[key] = (home_mean, away_mean, notes, mean_receipts)
    home_mean, away_mean, pregame_notes, mean_receipts = means_cache[key]
    receipts.extend(mean_receipts)

    # -- 3. reprice ----------------------------------------------------
    side = _resolve_side(line, state.home_team, state.away_team)
    if side is None:
        raise LiveRepriceError(
            f"SIDE_UNRESOLVED:{line.get('side_raw')}")
    line_value = None
    if line["market"] != "ML":
        line_value = numeric(line.get("line"), "line")
    if line.get("odds", line.get("price")) is None:
        raise LiveRepriceError("LIVE_LINE_REQUIRED:no_live_odds_supplied")
    if sport == "MLB":
        reprice = reprice_mlb(state, home_mean, away_mean,
                              line["market"], side, line_value)
    else:
        reprice = reprice_football(state, home_mean, away_mean,
                                   line["market"], side, line_value)

    return _ev_row(
        index=index, line=line, state_summary=reprice.state_summary,
        state_observed_at=state.observed_at.isoformat(),
        state_age_s=age_s, home_mean=home_mean, away_mean=away_mean,
        reprice=reprice, receipts=receipts, min_ev=min_ev,
        pregame_notes=pregame_notes, participation=participation)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Live/in-game research card from free provider state. "
                    "Research only: no betting, no bet execution.")
    p.add_argument("--lines", required=True, type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--min-ev", type=float, default=0.02)
    args = p.parse_args(argv)
    if not 0 <= args.min_ev <= 0.15:
        p.error("min-ev must be between 0 and 0.15")
    card = run_live_full(json.loads(args.lines.read_text(encoding="utf-8")),
                         min_ev=args.min_ev)
    rendered = json.dumps(card, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
