#!/usr/bin/env python3
"""One-shot frozen Attempt 9 check on pre-registered 2026 weeks.

Does not change coefficients, decay, or eligibility rules.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from math import sqrt
from pathlib import Path

from sportsedge.nfl_attempt9_live_forecast import (
    is_integer_line,
    load_model_p,
    load_runtime,
    raw_forecasts,
    recency_features,
)
from sportsedge.sports.nfl.attempt9_model_p import model_probability
from sportsedge.source_lineage import canonical_json_sha256

CUTOFF = date(2026, 9, 30)
WINDOW_START = date(2026, 9, 1)


def _rmse(pairs: list[tuple[float, float]]) -> float:
    if not pairs:
        return float("nan")
    return sqrt(sum((a - b) ** 2 for a, b in pairs) / len(pairs))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    blob = json.loads(Path(args.history).read_text(encoding="utf-8"))
    games = blob["games"] if isinstance(blob, dict) and "games" in blob else blob
    runtime = load_runtime()
    artifact = load_model_p()
    scored = []
    skipped = []
    for game in games:
        if int(game.get("season") or 0) != 2026:
            continue
        day = date.fromisoformat(str(game["date"])[:10])
        if day < WINDOW_START or day >= CUTOFF:
            continue
        feat = recency_features(games, home=game["home"], away=game["away"], asof=day)
        if not feat.get("ok"):
            skipped.append({"id": game.get("id"), "date": game["date"], "reason": feat["reason"]})
            continue
        forecast = raw_forecasts(runtime, feat["vector"])
        actual_margin = float(game["hs"]) - float(game["as"])
        actual_total = float(game["hs"]) + float(game["as"])
        row = {
            "id": game.get("id"),
            "date": game["date"],
            "home": game["home"],
            "away": game["away"],
            "pred_margin": forecast["margin"],
            "pred_total": forecast["total"],
            "actual_margin": actual_margin,
            "actual_total": actual_total,
            "close_home_margin": game.get("spread_line"),
            "close_total": game.get("total_line"),
            "home_prior_games": feat["home_prior_games"],
            "away_prior_games": feat["away_prior_games"],
        }
        if game.get("total_line") is not None and not is_integer_line(float(game["total_line"])):
            over = model_probability(artifact, market="total", raw_prediction=forecast["total"], line=float(game["total_line"]), selection="over")
            row["p_over_close"] = over["model_p"]
            row["over_hit"] = int(actual_total > float(game["total_line"]))
        if game.get("spread_line") is not None and not is_integer_line(float(game["spread_line"])):
            # nflverse spread_line > 0 ⇒ home favored ≈ expected home margin.
            # Attempt 9 home handicap is the opposite sign of a favorite.
            home_handicap = -float(game["spread_line"])
            cover = model_probability(artifact, market="spread", raw_prediction=forecast["margin"], line=home_handicap, selection="home")
            row["p_home_cover_close"] = cover["model_p"]
            row["home_cover"] = int(actual_margin > float(game["spread_line"]))
        scored.append(row)

    margin_pairs = [(r["pred_margin"], r["actual_margin"]) for r in scored]
    total_pairs = [(r["pred_total"], r["actual_total"]) for r in scored]
    close_m = [(float(r["close_home_margin"]), r["actual_margin"]) for r in scored if r.get("close_home_margin") is not None]
    close_t = [(float(r["close_total"]), r["actual_total"]) for r in scored if r.get("close_total") is not None]

    def _rate(rows, p_key, y_key):
        usable = [r for r in rows if p_key in r]
        if not usable:
            return None
        pred = sum(float(r[p_key]) for r in usable) / len(usable)
        obs = sum(int(r[y_key]) for r in usable) / len(usable)
        brier = sum((float(r[p_key]) - int(r[y_key])) ** 2 for r in usable) / len(usable)
        return {"n": len(usable), "mean_predicted": pred, "observed": obs, "gap_pp": abs(pred - obs) * 100.0, "brier": brier}

    payload = {
        "evaluation": "NFL_ATTEMPT9_2026_WEEKS_ONE_SHOT",
        "window": {"start": WINDOW_START.isoformat(), "end_exclusive": CUTOFF.isoformat()},
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "history_source": blob.get("source") if isinstance(blob, dict) else None,
        "history_retrieved_at_utc": blob.get("retrieved_at_utc") if isinstance(blob, dict) else None,
        "scored_games": len(scored),
        "skipped_games": len(skipped),
        "rmse": {
            "attempt9_margin": _rmse(margin_pairs),
            "attempt9_total": _rmse(total_pairs),
            "closing_home_margin": _rmse(close_m),
            "closing_total": _rmse(close_t),
        },
        "half_point_close_lines": {
            "total_over": _rate(scored, "p_over_close", "over_hit"),
            "home_cover": _rate(scored, "p_home_cover_close", "home_cover"),
        },
        "integer_lines": "NO_MODEL_EXCLUDED",
        "skipped": skipped,
        "label": "NOT Model_P / NOT Truth Gate / NOT OFFICIAL",
    }
    payload["payload_sha256"] = canonical_json_sha256({k: v for k, v in payload.items() if k != "games"})
    payload["games"] = scored
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "scored": payload["scored_games"],
        "skipped": payload["skipped_games"],
        "rmse": payload["rmse"],
        "half_point_close_lines": payload["half_point_close_lines"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
