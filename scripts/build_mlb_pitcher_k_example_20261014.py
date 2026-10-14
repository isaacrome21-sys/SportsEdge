"""Worked example: MLB pitcher-K source -> model -> quote -> card (Oct 14, 2026).

One game, no fabricated inputs: NLCS Game 3, Milwaukee @ Los Angeles,
gamePk 849811, first pitch 2026-10-14 19:00 CT.

Chain (every link is the repository's own frozen machinery):
  1. Identity: StatsAPI live feed probable pitchers + teams (verified at
     capture time, pregame).
  2. Features: the frozen Attempt-1 candidate's eight PIT features, built by
     the same component builders the historical assembler composes --
     workload bundle from strictly-prior StatsAPI game logs (gameType=R,
     last 5-10 starts), opponent-K adjustment from the validated #1509 lane,
     lineup-K from the validated #1540 lane when it can be built pregame
     (otherwise the validated fallback: deviation = 1.0, labeled), and
     30-day Statcast whiff/chase from fetch_daily_statcast with the game
     date as exclusive end (a prospective pregame query; NOT a governed
     forward-validation unit -- see EXAMPLE.md for the eligibility note).
  3. Model: the frozen Attempt-1 passed fit (config/research/
     mlb_pitcher_k_attempt1_passed_fit_freeze_v1.json), integrity-checked by
     recomputing its fit SHA-256 from the stored payload before use.
     No retraining, no parameter edits (the freeze forbids both).
  4. Quotes: the verbatim DraftKings milestone ladders captured Oct 14
     (fixtures on main in tests/test_milestone_ladder_ingestion_20261014.py,
     sourced from the diagnostic pull), converted by the merged
     milestone-ladder adapter: X+ -> Over (X - 0.5), real prices, original
     shared capture, one-sided provenance. No opposite price is invented;
     no-vig is UNAVAILABLE.
  5. Card: per-rung candidate probabilities and research EV, every row
     labeled RESEARCH_CANDIDATE_UNVALIDATED. The one-sided EV route is not
     eligible until the probability is validated (forward protocol pending).

Usage: python3 scripts/build_mlb_pitcher_k_example_20261014.py --out-dir DIR
Writes example_card.json and example_inputs.json into DIR.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from math import exp
from pathlib import Path
import sys
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.mlb_pitcher_k_composite_candidate import build_composite_candidate
from sportsedge.mlb_pitcher_k_probability_candidate import (
    PitcherKRateFit,
    feature_vector,
    predict_k_rate,
    price_threshold,
    projected_batters_faced,
)
from sportsedge.mlb_pitcher_k_probability_prereg import CANDIDATE_FAMILY, FEATURES
from sportsedge.mlb_pitcher_k_workload_candidate import build_workload_bundle
from sportsedge.milestone_ladder_intake import expand_milestone_ladder_rows
from sportsedge.statcast_daily_source import fetch_daily_statcast

GAME_PK = 849811
TARGET_DATE = date(2026, 10, 14)
CAPTURE_UTC = "2026-10-14T19:44:00Z"  # the diagnostic pull's ladder capture
FREEZE_PATH = "config/research/mlb_pitcher_k_attempt1_passed_fit_freeze_v1.json"

# Verbatim DraftKings milestone ladders, Oct 14 2026 pull (fixtures on main:
# tests/test_milestone_ladder_ingestion_20261014.py, sourced from
# ~/workspace/sportsedge/diagnostic_run_20261014/REPORT.md).
LADDERS = {
    "Blake Snell": [(3, -2600), (4, -890), (5, -382), (6, -184), (7, 106),
                    (8, 199), (9, 370), (10, 680), (11, 1240)],
    "Robert Gasser": [(2, -730), (3, -229), (4, 105), (5, 239), (6, 537),
                      (7, 1140)],
}


def american_to_decimal(odds: int) -> float:
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / abs(odds))


def ev_per_dollar(p_win: float, odds: int) -> float:
    """Settlement EV per $1 for a half-line (no push possible)."""
    return p_win * (american_to_decimal(odds) - 1.0) - (1.0 - p_win)


def load_frozen_fit(repo_root: Path) -> tuple[PitcherKRateFit, float, dict]:
    """Load the frozen fit through the governed forward-validation loader,
    which verifies the fit SHA-256 identity before returning it."""
    from sportsedge.mlb_pitcher_k_forward_validation import (
        load_frozen_fit as _governed_load,
    )

    return _governed_load(repo_root / FREEZE_PATH)


def feed_identity() -> dict:
    with urlopen(f"https://statsapi.mlb.com/api/v1.1/game/{GAME_PK}/feed/live",
                 timeout=30) as resp:
        feed = json.loads(resp.read().decode("utf-8"))
    gd = feed["gameData"]
    out = {"status": gd["status"]["detailedState"],
           "official_start_utc": gd["datetime"]["dateTime"], "sides": {}}
    for side in ("away", "home"):
        team = gd["teams"][side]
        prob = gd["probablePitchers"][side]
        order = feed["liveData"]["boxscore"]["teams"][side].get("battingOrder", [])
        out["sides"][side] = {
            "team_id": int(team["id"]), "team_name": team["name"],
            "pitcher_id": int(prob["id"]), "pitcher_name": prob["fullName"],
            "batting_order_posted": len(order) == 9,
            "batting_order_len": len(order),
        }
    return out


def statcast_skill(snapshot, pitcher_id: int) -> dict:
    row = next((r for r in snapshot.pitcher_rows
                if str(r.get("entity_id")) == str(pitcher_id)), None)
    if row is None:
        raise SystemExit(f"STATCAST_PITCHER_MISSING:{pitcher_id}")
    swings, whiffs = int(row["swings"]), int(row["whiffs"])
    ooze, chases = int(row["out_of_zone_pitches"]), int(row["chases"])
    if swings <= 0 or ooze <= 0 or whiffs > swings or chases > ooze:
        raise SystemExit(f"STATCAST_COUNTS_IMPOSSIBLE:{pitcher_id}")
    if abs(row["whiff_rate"] - whiffs / swings) > 1e-6:
        raise SystemExit(f"STATCAST_WHIFF_RATE_MISMATCH:{pitcher_id}")
    if abs(row["chase_rate"] - chases / ooze) > 1e-6:
        raise SystemExit(f"STATCAST_CHASE_RATE_MISMATCH:{pitcher_id}")
    if row["pitcher_hand"] not in {"L", "R"}:
        raise SystemExit(f"STATCAST_HAND_INVALID:{pitcher_id}")
    return {
        "source": "BASEBALL_SAVANT_STATCAST_30D",
        "entity_id": str(pitcher_id),
        "whiff_rate": float(row["whiff_rate"]),
        "chase_rate": float(row["chase_rate"]),
        "swings": swings, "whiffs": whiffs,
        "out_of_zone_pitches": ooze, "chases": chases,
        "pitcher_hand": row["pitcher_hand"],
        "window_start": snapshot.start_date,
        "window_end": snapshot.end_date,
        "provenance": {
            "mode": "PROSPECTIVE_PREGAME_CAPTURE",
            "retrieved_at": snapshot.retrieved_at,
            "query_end_exclusive": snapshot.end_date,
            "same_day_rows_included": False,
            "future_rows_included": False,
            "forward_validation_unit": False,
            "forward_ineligibility_reason": (
                "Governed forward protocol requires main-capture provenance "
                "and two-sided main-line DK quotes; milestone ladders are "
                "one-sided alternate-format quotes."),
        },
    }


def build_pitcher(source: MLBGenericHistorySource, snapshot, identity: dict,
                  side: str, fit: PitcherKRateFit, concentration: float) -> dict:
    info = identity["sides"][side]
    pitcher_id, team_id = info["pitcher_id"], info["team_id"]
    opp_side = "home" if side == "away" else "away"
    opp_team_id = identity["sides"][opp_side]["team_id"]

    rows = source.player_rows(player_id=pitcher_id, group="pitching",
                              target_date=TARGET_DATE)
    starts = [r for r in rows
              if isinstance(r.get("stat"), dict)
              and float(r["stat"].get("gamesStarted", 0)) >= 1][-10:]
    if len(starts) < 5:
        return {"pitcher": info, "blocker": "WORKLOAD_INSUFFICIENT_PRIOR_STARTS",
                "prior_starts_found": len(starts)}
    workload = build_workload_bundle(starts)
    starts_audit = [{
        "date": str(r.get("date")),
        "batters_faced": int(r["stat"]["battersFaced"]),
        "strikeouts": int(r["stat"]["strikeOuts"]),
        "pitches": int(r["stat"]["numberOfPitches"]),
    } for r in starts]

    opp_k, why = source._opp_k_payload(
        player_id=pitcher_id, target_date=TARGET_DATE, team_id=team_id,
        away_team_id=identity["sides"]["away"]["team_id"],
        home_team_id=identity["sides"]["home"]["team_id"])
    if opp_k is None:
        return {"pitcher": info, "blocker": f"OPPONENT_K_UNAVAILABLE:{why}",
                "starts_used": starts_audit}

    lineup_k, lineup_why = source._lineup_k_payload(
        game_pk=GAME_PK, player_id=pitcher_id, target_date=TARGET_DATE,
        opponent_id=int(opp_k["opponent_team_id"]))
    lineup_note = ("VALIDATED_LINEUP_COMPONENT" if lineup_k is not None
                   else f"FALLBACK_DEVIATION_1.0:{lineup_why}")

    composite = build_composite_candidate(
        workload=workload, opp_k_adjustment=opp_k,
        lineup_k_adjustment=lineup_k)
    candidate = dict(composite)
    candidate["schema"] = "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"
    candidate["components"] = dict(composite["components"])
    candidate["components"]["pitcher_skill"] = statcast_skill(snapshot, pitcher_id)
    candidate["missing_components"] = []
    candidate["source_complete"] = True
    candidate["evaluation_ready"] = False
    candidate["evaluation_use"] = "PROSPECTIVE_WORKED_EXAMPLE_NOT_FORWARD_VALIDATION"

    features = feature_vector(candidate)
    rate = predict_k_rate(fit, candidate)
    n_bf = projected_batters_faced(candidate)

    ladder_row = {
        "sport": "MLB",
        "away": identity["sides"]["away"]["team_name"],
        "home": identity["sides"]["home"]["team_name"],
        "kickoff": "2026-10-14T19:00:00-05:00",
        "book": "draftkings", "quote_captured_at": CAPTURE_UTC,
        "market": "PITCHER_K", "player_name": info["pitcher_name"],
        "milestone_ladder": {
            "form": "X_PLUS",
            "rungs": [{"threshold": t, "odds": o}
                      for t, o in LADDERS[info["pitcher_name"]]],
        },
    }
    emitted = expand_milestone_ladder_rows([ladder_row])
    rungs = []
    for row in emitted:
        if row.get("milestone_ladder_refusal"):
            return {"pitcher": info,
                    "blocker": f"LADDER_REFUSED:{row['milestone_ladder_refusal']}"}
        priced = price_threshold(candidate, fit, concentration=concentration,
                                 line=float(row["line"]))
        p_over = priced["candidate_p_over"]
        rungs.append({
            "milestone_threshold": row["milestone_threshold"],
            "converted_line": row["line"], "side": "OVER",
            "dk_odds_american": row["odds"],
            "source_quote_form": row["source_quote_form"],
            "quote_captured_at": row["quote_captured_at"],
            "model_p_over": p_over,
            "model_p_under_complement": priced["candidate_p_under"],
            "push_probability": priced["candidate_p_push"],
            "ev_per_dollar": ev_per_dollar(p_over, int(row["odds"])),
            "no_vig": "UNAVAILABLE",
            "label": "RESEARCH_CANDIDATE_UNVALIDATED",
        })
    return {
        "pitcher": info,
        "opponent_team_id": opp_team_id,
        "starts_used": starts_audit,
        "features": dict(zip(FEATURES, features)),
        "feature_provenance": {
            "workload": "StatsAPI gameLog gameType=R, strictly-prior starts, last 10",
            "opponent_k": "validated lane #1509 (mlb_opp_k_context), strictly prior",
            "lineup_k": lineup_note,
            "statcast": "Baseball Savant 30d, game-date-exclusive, captured pregame",
        },
        "projected_batters_faced": n_bf,
        "predicted_k_per_batter_faced": rate,
        "predicted_mean_strikeouts": rate * n_bf,
        "rungs": rungs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1]

    fit, concentration, freeze = load_frozen_fit(repo_root)
    identity = feed_identity()
    source = MLBGenericHistorySource(opener=urlopen,
                                     retrieved_at=datetime.now(timezone.utc))
    snapshot = fetch_daily_statcast(end_date=TARGET_DATE, days=30,
                                    opener=urlopen)

    card = {
        "schema": "MLB_PITCHER_K_WORKED_EXAMPLE_CARD_V1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "game": {"game_pk": GAME_PK, "date": TARGET_DATE.isoformat(),
                 "status_at_capture": identity["status"],
                 "official_start_utc": identity["official_start_utc"]},
        "model": {
            "candidate_family": CANDIDATE_FAMILY,
            "fit_sha256": fit.fit_sha256,
            "ridge_alpha": fit.ridge_alpha, "concentration": concentration,
            "status": freeze["status"],
            "development_gate": "PASSED_ATTEMPT_1 (2025 one-shot test; see VALIDATION.md)",
            "forward_validation": "PENDING -- this example is not a forward unit",
        },
        "quote_provenance": {
            "book": "draftkings", "format": "MILESTONE_X_PLUS_LADDER",
            "quote_captured_at": CAPTURE_UTC,
            "no_vig": "UNAVAILABLE (one-sided quotes; no opposite price invented)",
        },
        "label": "RESEARCH_CANDIDATE_UNVALIDATED",
        "pitchers": {},
    }
    for side in ("away", "home"):
        name = identity["sides"][side]["pitcher_name"]
        card["pitchers"][name] = build_pitcher(
            source, snapshot, identity, side, fit, concentration)

    (out_dir / "example_card.json").write_text(json.dumps(card, indent=1))
    print(json.dumps({k: ("BLOCKED:" + v["blocker"]) if "blocker" in v else
                      f"meanK={v['predicted_mean_strikeouts']:.3f} rungs={len(v['rungs'])}"
                      for k, v in card["pitchers"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
