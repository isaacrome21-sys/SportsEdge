#!/usr/bin/env python3
"""Forward-only CFB priced-decision and settlement research.

Read ONLY previously archived pre-kickoff card rows. A model/price disagreement
can be a SHADOW_CANDIDATE; it is not verified +EV, betting advice, or a wager.
No previous-market backfill, market interpolation, or after-result selection.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from math import erf, isfinite, sqrt
from pathlib import Path

SCHEMA = "CFB_FORWARD_PRICED_EV_RESEARCH_V1"
MODEL_SNAPSHOT = "CFB_SDV_FORWARD_SCORE_SNAPSHOT_V1"
FLOOR, CAP, MIN_ODDS = 0.02, 0.12, -165
ILLINOIS_TEAMS = ("illinois", "northwestern", "northern illinois",
                  "eastern illinois", "western illinois",
                  "southern illinois", "illinois state", "chicago state")


def finite(v, label):
    if isinstance(v, bool):
        raise ValueError("CFB_FORWARD_EVAL_NUMERIC_INVALID:" + label)
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError("CFB_FORWARD_EVAL_NUMERIC_INVALID:" + label) from exc
    if not isfinite(x):
        raise ValueError("CFB_FORWARD_EVAL_NONFINITE:" + label)
    return x


def stamp(value, label):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError("missing UTC offset")
        return t.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CFB_FORWARD_EVAL_TIMESTAMP_INVALID:" + label) from exc


def cdf(x):
    return .5 * (1.0 + erf(x / sqrt(2.0)))


def raw_implied(odds):
    if odds <= -100:
        return -odds / (100.0 - odds)
    if odds >= 100:
        return 100.0 / (100.0 + odds)
    raise ValueError("CFB_FORWARD_EVAL_ODDS_INVALID")


def payout(odds):
    return (odds / 100.0) if odds > 0 else 100.0 / abs(odds)


def outcome_probs(mu, sigma, market, side, line):
    """Normal approximation with integer-threshold continuity and push mass.

    The original score model was continuous; this is a research challenger,
    not a production replacement or calibrated probability certification.
    """
    if sigma <= 0:
        raise ValueError("CFB_FORWARD_EVAL_SIGMA_INVALID")
    if market == "MONEYLINE":
        if side not in ("HOME", "AWAY") or line is not None:
            raise ValueError("CFB_FORWARD_EVAL_SELECTION_INVALID")
        w = cdf(mu / sigma) if side == "HOME" else cdf(-mu / sigma)
        return w, 1 - w, 0.0
    if market == "TOTAL":
        if side not in ("OVER", "UNDER"):
            raise ValueError("CFB_FORWARD_EVAL_SELECTION_INVALID")
        x = mu - line if side == "OVER" else line - mu
    elif market == "SPREAD":
        if side not in ("HOME", "AWAY"):
            raise ValueError("CFB_FORWARD_EVAL_SELECTION_INVALID")
        x = (mu if side == "HOME" else -mu) + line
    else:
        raise ValueError("CFB_FORWARD_EVAL_MARKET_INVALID")
    # A half-point contract cannot push. A whole-point contract can.
    if abs(line * 2 - round(line * 2)) > 1e-8:
        raise ValueError("CFB_FORWARD_EVAL_NONHALFPOINT_LINE")
    if abs(line - round(line)) < 1e-8:
        win = cdf((x - .5) / sigma)
        lose = cdf((-x - .5) / sigma)
        push = 1 - win - lose
    else:
        win = cdf(x / sigma)
        lose = 1 - win
        push = 0.0
    return max(0.0, win), max(0.0, lose), max(0.0, push)


def _canonical(q):
    market, side = q["market"], q["side"]
    line = q.get("line")
    if market == "MONEYLINE":
        return ("MONEYLINE", None)
    val = finite(line, "line")
    if market == "TOTAL":
        return ("TOTAL", val)
    if market == "SPREAD":
        return ("SPREAD", -val if side == "HOME" else val)
    raise ValueError("CFB_FORWARD_EVAL_MARKET_INVALID")


def _result(market, side, line, home, away):
    margin, total = home - away, home + away
    if market == "MONEYLINE":
        diff = margin if side == "HOME" else -margin
    elif market == "SPREAD":
        diff = (margin if side == "HOME" else -margin) + line
    else:
        diff = (total - line) if side == "OVER" else (line - total)
    return 1 if diff > 0 else -1 if diff < 0 else 0


def evaluate(snapshot, outcomes=None):
    if not isinstance(snapshot, dict) or snapshot.get("schema") != MODEL_SNAPSHOT:
        raise ValueError("CFB_FORWARD_EVAL_SNAPSHOT_SCHEMA_INVALID")
    if snapshot.get("bets_enabled") is not False or snapshot.get("positive_ev_proven") is not False:
        raise ValueError("CFB_FORWARD_EVAL_SNAPSHOT_AUTHORITY_INVALID")
    if snapshot.get("source_model_status") != "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED":
        raise ValueError("CFB_FORWARD_EVAL_NATIVE_MODEL_REQUIRED")
    if snapshot.get("paired_decision_quotes_retained") is not True:
        raise ValueError("CFB_FORWARD_EVAL_DECISION_QUOTES_MISSING")
    sigma = finite(snapshot.get("combined_sigma"), "sigma")
    if sigma <= 0:
        raise ValueError("CFB_FORWARD_EVAL_SIGMA_INVALID")
    games = snapshot.get("games")
    if not isinstance(games, list):
        raise ValueError("CFB_FORWARD_EVAL_GAMES_REQUIRED")
    results = {}
    for final in outcomes or []:
        gid = str(final.get("game_id") or "")
        if not gid or gid in results:
            raise ValueError("CFB_FORWARD_EVAL_SETTLEMENT_DUPLICATE")
        results[gid] = final
    selections = []
    seen = set()
    for game in games:
        gid = str(game.get("game_id") or "")
        if not gid or gid in seen:
            raise ValueError("CFB_FORWARD_EVAL_GAME_DUPLICATE")
        seen.add(gid)
        kickoff = stamp(game.get("kickoff_at"), "kickoff_at")
        scored = stamp(game.get("scored_at"), "scored_at")
        captured = stamp(game.get("source_capture_at"), "source_capture_at")
        if not captured <= scored < kickoff:
            raise ValueError("CFB_FORWARD_EVAL_NOT_PREGAME")
        total = finite(game.get("model_total"), "total")
        margin = finite(game.get("model_margin"), "margin")
        home = finite(game.get("home_mean"), "home_mean")
        away = finite(game.get("away_mean"), "away_mean")
        if abs(total - home - away) > .03 or abs(margin - home + away) > .03:
            raise ValueError("CFB_FORWARD_EVAL_MODEL_SCORE_MISMATCH")
        if game.get("decision_book_verified") is not False or game.get("decision_quote_captured_at_independently") is not None:
            raise ValueError("CFB_FORWARD_EVAL_FALSE_BOOK_ATTESTATION")
        if game.get("quote_source_card_sha256") != snapshot.get("source_card_sha256"):
            raise ValueError("CFB_FORWARD_EVAL_SOURCE_CARD_HASH_MISMATCH")
        raw_quotes = game.get("paired_decision_quotes") or []
        groups = {}
        for q in raw_quotes:
            key = _canonical(q)
            groups.setdefault(key, []).append(q)
        final = results.get(gid)
        hp = ap = None
        if final is not None:
            if final.get("status") != "FINAL":
                raise ValueError("CFB_FORWARD_EVAL_FINAL_REQUIRED")
            hp, ap = int(finite(final.get("home_points"), "home_points")), int(finite(final.get("away_points"), "away_points"))
            if (hp < 0 or ap < 0 or hp != finite(final["home_points"], "home_points") or
                    ap != finite(final["away_points"], "away_points")):
                raise ValueError("CFB_FORWARD_EVAL_FINAL_SCORE_INVALID")
            if stamp(final.get("final_at"), "final_at") <= kickoff:
                raise ValueError("CFB_FORWARD_EVAL_FINAL_BEFORE_KICKOFF")
            digest = str(final.get("outcome_source_sha256") or "")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("CFB_FORWARD_EVAL_SETTLEMENT_HASH_REQUIRED")
        for key, pair in sorted(groups.items(), key=lambda a: (a[0][0], a[0][1] or 0)):
            market = key[0]
            opp = {"MONEYLINE": {"HOME", "AWAY"},
                   "SPREAD": {"HOME", "AWAY"},
                   "TOTAL": {"OVER", "UNDER"}}[market]
            if len(pair) != 2 or {q.get("side") for q in pair} != opp:
                raise ValueError("CFB_FORWARD_EVAL_UNPAIRED_MARKET")
            implied = [raw_implied(finite(q["american_odds"], "odds")) for q in pair]
            denom = sum(implied)
            if denom <= 0:
                raise ValueError("CFB_FORWARD_EVAL_MARKET_IMPLIED_INVALID")
            for q, raw in zip(pair, implied):
                odds = finite(q["american_odds"], "odds")
                line = None if market == "MONEYLINE" else finite(q["line"], "line")
                mu = total if market == "TOTAL" else margin
                win, lose, push = outcome_probs(mu, sigma, market, q["side"], line)
                conditional_p = win / (win + lose) if win + lose > 0 else None
                fair = raw / denom
                edge = conditional_p - fair if conditional_p is not None else None
                ev = win * payout(odds) - lose
                allowed = (edge is not None and FLOOR <= edge <= CAP and ev > 0
                           and odds >= MIN_ODDS)
                score = _result(market, q["side"], line, hp, ap) if final else None
                selections.append({
                    "game_id": gid, "matchup": game.get("matchup"),
                    "market": market, "side": q["side"], "line": line, "american_odds": odds,
                    "no_vig_market_p": round(fair, 6),
                    "model_win_p_unvalidated": round(win, 6),
                    "model_loss_p_unvalidated": round(lose, 6),
                    "model_push_p_unvalidated": round(push, 6),
                    "model_conditional_win_p_unvalidated": round(conditional_p, 6),
                    "model_vs_novig_edge_pp": round(edge * 100, 3),
                    "theoretical_roi_unvalidated": round(ev, 6),
                    "shadow_rule_eligible": bool(allowed),
                    "settled": final is not None,
                    "result": ("WIN" if score == 1 else "LOSS" if score == -1
                               else "PUSH" if score == 0 else "PENDING"),
                    "units_per_one_risk_if_selected": (
                        round(payout(odds), 6) if score == 1 else -1.0 if score == -1
                        else 0.0 if score == 0 else None),
                    "decision_quote_receipt_independently_verified": False,
                    "disposition": "SHADOW_RESEARCH_ONLY_NO_WAGER",
                })
    # One decision per game in the result market family, chosen BEFORE result.
    for game_id in sorted(seen):
        for fam in (("MONEYLINE", "SPREAD"), ("TOTAL",)):
            candidates = [q for q in selections if q["game_id"] == game_id and
                          q["market"] in fam and q["shadow_rule_eligible"]]
            candidates.sort(key=lambda q: (-q["theoretical_roi_unvalidated"],
                                           q["market"], q["side"]))
            for j, q in enumerate(candidates):
                q["shadow_selected_before_settlement"] = (j == 0)
    for q in selections:
        q.setdefault("shadow_selected_before_settlement", False)
    selected = [q for q in selections if q["shadow_selected_before_settlement"]]
    settled = [q for q in selected if q["settled"]]
    units = sum(q["units_per_one_risk_if_selected"] for q in settled)
    return {
        "schema": SCHEMA,
        "source_snapshot_schema": MODEL_SNAPSHOT,
        "source_card_sha256": snapshot.get("source_card_sha256"),
        "paired_market_count": len(selections) // 2,
        "shadow_candidates": len(selected),
        "settled_shadow_candidates": len(settled),
        "settled_shadow_net_units": round(units, 5),
        "settled_shadow_roi": round(units / len(settled), 5) if settled else None,
        "decision_quotes_independently_verified": False,
        "real_positive_ev_proven": False,
        "bets_enabled": False,
        "staking_authority": False,
        "results": selections,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--outcomes", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    outcomes = json.loads(args.outcomes.read_text()) if args.outcomes else []
    report = evaluate(snapshot, outcomes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("CFB_FORWARD_PRICED_RESEARCH paired=%d candidates=%d settled=%d EV_UNPROVEN" %
          (report["paired_market_count"], report["shadow_candidates"], report["settled_shadow_candidates"]))


if __name__ == "__main__":
    main()
