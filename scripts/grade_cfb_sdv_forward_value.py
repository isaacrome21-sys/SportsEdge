#!/usr/bin/env python3
"""Grade captured CFB side/total LEANs against later final scores.

Research only. Selections are frozen by pregame probabilities/odds, before
looking up results. Manual DK board quotes have no independent sportsbook
timestamp and cannot substantiate executable positive EV or betting authority.
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

SNAPSHOT_SCHEMA = "CFB_SDV_FORWARD_SCORE_SNAPSHOT_V1"
SCHEMA = "CFB_SDV_FORWARD_VALUE_RESEARCH_V1"
EDGE_FLOOR = 0.02
EDGE_CAP = 0.12
STRAIGHT_MIN_ODDS = -165


def _time(value, field):
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if out.tzinfo is None or out.utcoffset() is None:
            raise ValueError("timezone missing")
        return out.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CFB_VALUE_TIME_INVALID:" + field) from exc


def _float(value, field):
    if isinstance(value, bool):
        raise ValueError("CFB_VALUE_NUMBER_INVALID:" + field)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CFB_VALUE_NUMBER_INVALID:" + field) from exc
    if not isfinite(out):
        raise ValueError("CFB_VALUE_NUMBER_INVALID:" + field)
    return out


def _digest(value, field):
    if not isinstance(value, str) or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        raise ValueError("CFB_VALUE_SHA256_INVALID:" + field)


def _profit_multiplier(odds):
    price = _float(odds, "american_odds")
    if -100 < price < 100:
        raise ValueError("CFB_VALUE_ODDS_INVALID")
    return price / 100.0 if price > 0 else 100.0 / -price


def _pair_valid(quote, quotes):
    market, side, line = quote["market"], quote["side"], quote["line"]
    opposite = {"SPREAD": {"HOME": "AWAY", "AWAY": "HOME"},
                "TOTAL": {"OVER": "UNDER", "UNDER": "OVER"}}[market][side]
    mates = [
        q for q in quotes if q.get("market") == market
        and q.get("side") == opposite
        and (q.get("line") == -line if market == "SPREAD" else q.get("line") == line)
        and q.get("devig") == "PAIRED_PROPORTIONAL"
    ]
    return len(mates) == 1


def _select_pre_result(game):
    """Decide hypothetical positions using only originally captured fields."""
    quotes = game.get("quoted_selections") or []
    if not isinstance(quotes, list):
        raise ValueError("CFB_VALUE_QUOTES_NOT_LIST")
    chosen = []
    for market in ("SPREAD", "TOTAL"):
        eligible = []
        for quote in quotes:
            if quote.get("market") != market:
                continue
            side = quote.get("side")
            if side not in ({"HOME", "AWAY"} if market == "SPREAD" else {"OVER", "UNDER"}):
                raise ValueError("CFB_VALUE_SIDE_INVALID")
            p = _float(quote.get("model_p"), "model_p")
            fair = _float(quote.get("market_p"), "market_p")
            edge = p - fair
            odds = _float(quote.get("american_odds"), "american_odds")
            payout = _profit_multiplier(odds)
            roi = p * (1.0 + payout) - 1.0
            if not 0 <= p <= 1 or not 0 <= fair <= 1:
                raise ValueError("CFB_VALUE_PROBABILITY_OUT_OF_RANGE")
            if abs(roi - _float(quote.get("expected_roi_unvalidated"), "expected_roi")) > 0.0005:
                raise ValueError("CFB_VALUE_EXPECTED_ROI_TAMPERED")
            if (quote.get("devig") != "PAIRED_PROPORTIONAL"
                    or quote.get("quote_evidence") != "UNATTESTED_MANUAL_BOARD"
                    or quote.get("original_status") != "LEAN"):
                continue
            if not _pair_valid(quote, quotes):
                raise ValueError("CFB_VALUE_PAIR_INVALID")
            if EDGE_FLOOR <= edge <= EDGE_CAP and roi > 0 and odds >= STRAIGHT_MIN_ODDS:
                eligible.append((roi, edge, str(side), quote))
        if eligible:
            # Deterministic pre-result choice; never pick the winning side in hindsight.
            winner = sorted(eligible, key=lambda x: (-x[0], -x[1], x[2]))[0][-1]
            chosen.append(winner)
    return chosen


def _settle(quote, home, away):
    market, side, line = quote["market"], quote["side"], float(quote["line"])
    if market == "SPREAD":
        diff = home - away if side == "HOME" else away - home
        test = diff + line
    else:
        total = home + away
        test = total - line if side == "OVER" else line - total
    return 1 if test > 1e-9 else -1 if test < -1e-9 else 0


def _roi_interval(values):
    """Exploratory independent-game bootstrap, not validation/promotion evidence."""
    if len(values) < 2:
        return None
    gen = random.Random(20261009)
    n = len(values)
    samples = sorted(sum(values[gen.randrange(n)] for _ in range(n)) / n
                     for _ in range(2000))
    return [round(samples[49], 5), round(samples[1949], 5)]


def evaluate(snapshots, settlements):
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("CFB_VALUE_SNAPSHOTS_REQUIRED")
    if not isinstance(settlements, list):
        raise ValueError("CFB_VALUE_SETTLEMENTS_INVALID")
    settled = {}
    for result in settlements:
        gid = str(result.get("game_id") or "")
        if not gid or gid in settled:
            raise ValueError("CFB_VALUE_SETTLEMENT_ID_INVALID")
        _digest(result.get("source_sha256"), "settlement_source")
        kickoff = _time(result.get("kickoff_at"), "settlement_kickoff")
        observed = _time(result.get("settled_at"), "settled_at")
        if observed <= kickoff:
            raise ValueError("CFB_VALUE_RESULT_NOT_AFTER_KICKOFF")
        home = _float(result.get("home_points"), "home_points")
        away = _float(result.get("away_points"), "away_points")
        if not (home.is_integer() and away.is_integer() and 0 <= home <= 100 and 0 <= away <= 100):
            raise ValueError("CFB_VALUE_POINTS_INVALID")
        settled[gid] = (kickoff, int(home), int(away))
    grouped = {"SPREAD": [], "TOTAL": []}
    pending = {"SPREAD": 0, "TOTAL": 0}
    seen_games = set()
    for snap in snapshots:
        if (snap.get("schema") != SNAPSHOT_SCHEMA or snap.get("bets_enabled") is not False
                or snap.get("positive_ev_proven") is not False
                or snap.get("staking_authority") is not False):
            raise ValueError("CFB_VALUE_RESEARCH_SNAPSHOT_REQUIRED")
        _digest(snap.get("source_card_sha256"), "card")
        for game in snap.get("games") or []:
            gid = str(game.get("game_id") or "")
            if not gid or gid in seen_games:
                raise ValueError("CFB_VALUE_GAME_DUPLICATE_OR_MISSING")
            seen_games.add(gid)
            predicted = _time(game.get("scored_at"), "scored_at")
            kickoff = _time(game.get("kickoff_at"), "kickoff_at")
            if predicted >= kickoff:
                raise ValueError("CFB_VALUE_FORECAST_NOT_PREGAME")
            chosen = _select_pre_result(game)
            outcome = settled.get(gid)
            if outcome is None:
                for q in chosen:
                    pending[q["market"]] += 1
                continue
            result_kickoff, home, away = outcome
            if result_kickoff != kickoff:
                raise ValueError("CFB_VALUE_KICKOFF_IDENTITY_MISMATCH")
            for quote in chosen:
                win = _settle(quote, home, away)
                profit = _profit_multiplier(quote["american_odds"]) if win > 0 else (
                    -1.0 if win < 0 else 0.0)
                grouped[quote["market"]].append({
                    "game_id": gid,
                    "matchup": game.get("matchup"),
                    "side": quote["side"],
                    "line": quote["line"],
                    "odds": quote["american_odds"],
                    "model_p_unvalidated": quote["model_p"],
                    "forecast_expected_roi": quote["expected_roi_unvalidated"],
                    "result": "WIN" if win > 0 else "LOSS" if win < 0 else "PUSH",
                    "unit_return": round(profit, 6),
                })
    markets = {}
    for market, records in grouped.items():
        values = [r["unit_return"] for r in records]
        n = len(records)
        markets[market] = {
            "settled_count": n,
            "pending_count": pending[market],
            "wins": sum(r["result"] == "WIN" for r in records),
            "losses": sum(r["result"] == "LOSS" for r in records),
            "pushes": sum(r["result"] == "PUSH" for r in records),
            "realized_roi_per_unit": round(sum(values) / n, 5) if n else None,
            "exploratory_bootstrap_roi_95pct": _roi_interval(values),
            "mean_unvalidated_predicted_roi": round(
                sum(r["forecast_expected_roi"] for r in records) / n, 5) if n else None,
            "records": records,
        }
    return {
        "schema": SCHEMA,
        "evidence_class": "RESEARCH_SETTLEMENT_GRADING_NOT_EXECUTABLE_PRICE_PROOF",
        "source_run_independently_attested": False,
        "sportsbook_price_receipt_verified": False,
        "settlement_source_independently_verified": False,
        "positive_ev_proven": False,
        "validated_markets": [],
        "bets_enabled": False,
        "staking_authority": False,
        "no_backfill": True,
        "markets": markets,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", action="append", type=Path, required=True)
    parser.add_argument("--settlements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snaps = [json.loads(p.read_text(encoding="utf-8")) for p in args.snapshot]
    outcomes = json.loads(args.settlements.read_text(encoding="utf-8"))
    report = evaluate(snaps, outcomes["games"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CFB_FORWARD_VALUE_RESEARCH SPREAD=%d TOTAL=%d BETS_ENABLED=0" % (
        report["markets"]["SPREAD"]["settled_count"],
        report["markets"]["TOTAL"]["settled_count"],
    ))


if __name__ == "__main__":
    main()
