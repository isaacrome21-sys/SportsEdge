#!/usr/bin/env python3
"""Strict-prior audit of a full-game MLB over-dispersion candidate.

This script deliberately separates mean-model validation from distribution-shape
validation. It uses the current production full-game run means (the #1234 50/50
team-offense + opponent-run-prevention blend) and compares:

1. the current V7 production score distribution; and
2. a mean-preserving shared Gamma-Poisson candidate whose total-run variance is
   Var(T) = E[T] + E[T]^2 / r.

The dispersion parameter ``r`` is fit once on an earlier tuning slice using only
final scores and strict-prior production means, then frozen for the later
validation slice. No sportsbook prices are used. This is distribution research,
not edge/CLV/ROI or Truth-Gate promotion evidence.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from math import exp, isfinite, sqrt
from pathlib import Path
import random
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.mlb_all_market_features import (
    MLBAllMarketHistorySource,
    PRODUCTION_RUN_MEAN_VERSION,
)
from sportsedge.source_lineage import canonical_json_sha256
from sportsedge.v7_distribution import (
    DEFAULT_EXTRA_HALF_INNING_MEAN,
    DEFAULT_FIRST_INNING_DISPERSION_R,
    DEFAULT_FIRST_INNING_SHARE,
    V7_DISTRIBUTION_VERSION,
    simulate_game_distribution,
)

CANDIDATE_VERSION = "mlb_full_game_shared_gamma_poisson_dispersion_v1"
REFERENCE_LINES = (6.5, 7.5, 8.5, 9.5)


def _get_json(url: str):
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _schedule(start: date, end: date) -> list[dict]:
    q = urlencode({
        "sportId": 1,
        "gameType": "R",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "hydrate": "linescore,team",
    })
    payload = _get_json(f"https://statsapi.mlb.com/api/v1/schedule?{q}")
    out = []
    for day in payload.get("dates") or []:
        for game in day.get("games") or []:
            status = (game.get("status") or {}).get("abstractGameState")
            if str(status).lower() != "final":
                continue
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            if away.get("score") is None or home.get("score") is None:
                continue
            out.append({
                "game_pk": int(game["gamePk"]),
                "official_date": str(game.get("officialDate")),
                "away_team_id": int(away_team["id"]),
                "home_team_id": int(home_team["id"]),
                "away_team": str(away_team.get("name") or away_team["id"]),
                "home_team": str(home_team.get("name") or home_team["id"]),
                "away_score": int(away["score"]),
                "home_score": int(home["score"]),
            })
    out.sort(key=lambda g: (g["official_date"], g["game_pk"]))
    return out


def _pmf_rows(pmf: dict[str, float]):
    for key, p in pmf.items():
        away, home = key.split(",", 1)
        yield int(away), int(home), float(p)


def _line_prob(pmf: dict[str, float], line: float) -> tuple[float, float, float]:
    over = under = push = 0.0
    for away, home, p in _pmf_rows(pmf):
        total = away + home
        if total > line:
            over += p
        elif total < line:
            under += p
        else:
            push += p
    return over, under, push


def _calibration_bins(rows: list[tuple[float, int]], width: float = 0.10) -> list[dict]:
    bins = []
    lo = 0.0
    while lo < 1.0 - 1e-12:
        hi = min(1.0, lo + width)
        bucket = [(p, y) for p, y in rows if (lo <= p < hi) or (hi == 1.0 and lo <= p <= hi)]
        if bucket:
            bins.append({
                "lo": round(lo, 2),
                "hi": round(hi, 2),
                "n": len(bucket),
                "mean_p": sum(p for p, _ in bucket) / len(bucket),
                "observed_rate": sum(y for _, y in bucket) / len(bucket),
            })
        lo = hi
    return bins


def _binary_summary(rows: list[tuple[float, int]]) -> dict:
    if not rows:
        return {"n": 0}
    n = len(rows)
    mean_p = sum(p for p, _ in rows) / n
    observed = sum(y for _, y in rows) / n
    brier = sum((p - y) ** 2 for p, y in rows) / n
    return {
        "n": n,
        "mean_predicted_probability": mean_p,
        "observed_rate": observed,
        "calibration_gap_pp": 100.0 * (mean_p - observed),
        "brier": brier,
        "bins": _calibration_bins(rows),
    }


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 30.0:
        limit = exp(-lam)
        product = 1.0
        k = 0
        while product > limit:
            k += 1
            product *= rng.random()
        return k - 1
    return max(0, int(round(rng.gauss(lam, lam ** 0.5))))


def _resolve_extras(
    rng: random.Random,
    away_runs: int,
    home_runs: int,
    *,
    away_lam: float,
    home_lam: float,
    extra_half_inning_mean: float,
) -> tuple[int, int]:
    if away_runs != home_runs:
        return away_runs, home_runs
    avg_lam = max(1e-9, (away_lam + home_lam) / 2.0)
    away_extra_mean = extra_half_inning_mean * away_lam / avg_lam
    home_extra_mean = extra_half_inning_mean * home_lam / avg_lam
    for _ in range(30):
        away_extra = _poisson(rng, away_extra_mean)
        home_extra = _poisson(rng, home_extra_mean)
        away_runs += away_extra
        if home_extra > away_extra:
            home_runs += away_extra + 1
            return away_runs, home_runs
        home_runs += home_extra
        if away_extra > home_extra:
            return away_runs, home_runs
    p_home = home_lam / max(1e-9, home_lam + away_lam)
    if rng.random() < p_home:
        home_runs += 1
    else:
        away_runs += 1
    return away_runs, home_runs


def _candidate_pmf(
    *,
    away_mean: float,
    home_mean: float,
    dispersion_r: float,
    simulations: int,
    identity: str,
) -> dict[str, float]:
    if not isfinite(dispersion_r) or dispersion_r <= 0:
        raise ValueError("dispersion_r must be finite and > 0")
    seed_hex = canonical_json_sha256({
        "candidate": CANDIDATE_VERSION,
        "identity": identity,
        "away_mean": away_mean,
        "home_mean": home_mean,
        "dispersion_r": dispersion_r,
        "simulations": simulations,
    })
    rng = random.Random(int(seed_hex, 16))
    counts: dict[tuple[int, int], int] = {}
    scale = 1.0 / dispersion_r
    for _ in range(simulations):
        # Shared pace preserves each team's unconditional mean while widening the
        # game-total distribution. Conditional on pace, team scores remain Poisson.
        pace = rng.gammavariate(dispersion_r, scale)
        away_lam = away_mean * pace
        home_lam = home_mean * pace
        away_runs = _poisson(rng, away_lam)
        home_runs = _poisson(rng, home_lam)
        if away_runs == home_runs:
            away_runs, home_runs = _resolve_extras(
                rng,
                away_runs,
                home_runs,
                away_lam=max(1e-9, away_lam),
                home_lam=max(1e-9, home_lam),
                extra_half_inning_mean=DEFAULT_EXTRA_HALF_INNING_MEAN,
            )
        counts[(away_runs, home_runs)] = counts.get((away_runs, home_runs), 0) + 1
    return {f"{a},{h}": n / simulations for (a, h), n in sorted(counts.items())}


def _fit_dispersion_r(rows: list[dict], *, min_r: float = 2.0, max_r: float = 50.0) -> dict:
    """Method-of-moments fit on centered total residuals for a Gamma-Poisson total.

    For heterogeneous game means mu_i, the candidate implies
      Var(T_i | mu_i) = mu_i + mu_i^2 / r.
    We center residuals for mean bias, sum the excess squared residual above the
    Poisson term, and solve once for r. The result is clipped before validation.
    """
    if len(rows) < 20:
        raise ValueError("need at least 20 tuning games")
    residuals = [float(r["actual_final_total"]) - float(r["model_input_total_mean"]) for r in rows]
    bias = sum(residuals) / len(residuals)
    centered_sq = [((res - bias) ** 2) for res in residuals]
    mus = [float(r["model_input_total_mean"]) for r in rows]
    numerator = sum(mu * mu for mu in mus)
    denominator = sum(sq - mu for sq, mu in zip(centered_sq, mus))
    raw_r = float("inf") if denominator <= 0 else numerator / denominator
    locked_r = max(min_r, min(max_r, raw_r if isfinite(raw_r) else max_r))
    return {
        "method": "heterogeneous_gamma_poisson_mom_centered_residuals_v1",
        "n": len(rows),
        "mean_residual_actual_minus_input_mean": bias,
        "raw_r": raw_r if isfinite(raw_r) else None,
        "locked_r": locked_r,
        "clip": {"min_r": min_r, "max_r": max_r},
    }


def _aggregate_line_summaries(rows: list[dict], key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in REFERENCE_LINES:
        pairs: list[tuple[float, int]] = []
        for row in rows:
            probs = row[key][str(line)]
            p_over = probs["p_over_ex_push"]
            if p_over is None:
                continue
            actual_total = int(row["actual_final_total"])
            if actual_total == line:
                continue
            pairs.append((float(p_over), 1 if actual_total > line else 0))
        out[str(line)] = _binary_summary(pairs)
    return out


def _score_distribution(summaries: dict[str, dict]) -> dict:
    usable = [s for s in summaries.values() if s.get("n", 0)]
    if not usable:
        return {"mean_abs_calibration_gap_pp": None, "mean_brier": None}
    return {
        "mean_abs_calibration_gap_pp": sum(abs(float(s["calibration_gap_pp"])) for s in usable) / len(usable),
        "mean_brier": sum(float(s["brier"]) for s in usable) / len(usable),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-01")
    ap.add_argument("--end", default="2026-09-27")
    ap.add_argument("--validation-start", default="2026-09-15")
    ap.add_argument("--max-games", type=int, default=250)
    ap.add_argument("--simulations", type=int, default=100000)
    ap.add_argument("--output", default="artifacts/mlb_game_engine_dispersion_audit.json")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    validation_start = date.fromisoformat(args.validation_start)
    if not start < validation_start <= end:
        raise SystemExit("validation-start must be inside (start, end]")
    if end >= date(2026, 9, 29):
        raise SystemExit("audit end must be strictly before 2026-09-29")
    if args.simulations < 100000:
        raise SystemExit("audit uses the production 100k simulation floor")

    games = _schedule(start, end)
    if args.max_games > 0 and len(games) > args.max_games:
        games = games[-args.max_games:]

    source = MLBAllMarketHistorySource(retrieved_at=datetime(2026, 9, 29, tzinfo=timezone.utc))
    rows: list[dict] = []
    failures = []

    for i, game in enumerate(games, 1):
        try:
            target_date = date.fromisoformat(game["official_date"])
            feature = source.feature_row(
                game_pk=game["game_pk"],
                market="TOTALS",
                entity_id=str(game["game_pk"]),
                target_date=target_date,
                away_team_id=game["away_team_id"],
                home_team_id=game["home_team_id"],
            )
            away_mean = float(feature["away_mean_runs"])
            home_mean = float(feature["home_mean_runs"])
            feature_hash = feature.get("source_subset_hash")
            build_hash = canonical_json_sha256({
                "engine": V7_DISTRIBUTION_VERSION,
                "game_id": str(game["game_pk"]),
                "away_mean_runs": away_mean,
                "home_mean_runs": home_mean,
                "feature_source_hash": feature_hash,
            })
            dist = simulate_game_distribution(
                away_mean_runs=away_mean,
                home_mean_runs=home_mean,
                total_line=0.0,
                simulations=args.simulations,
                build_hash=build_hash,
                first_inning_share=DEFAULT_FIRST_INNING_SHARE,
                first_inning_dispersion_r=DEFAULT_FIRST_INNING_DISPERSION_R,
                extra_half_inning_mean=DEFAULT_EXTRA_HALF_INNING_MEAN,
            )
            actual_total = game["away_score"] + game["home_score"]
            baseline_lines = {}
            for line in REFERENCE_LINES:
                p_over, p_under, p_push = _line_prob(dist.joint_score_pmf, line)
                baseline_lines[str(line)] = {
                    "p_over": p_over,
                    "p_under": p_under,
                    "p_push": p_push,
                    "p_over_ex_push": p_over / (p_over + p_under) if p_over + p_under > 0 else None,
                }
            rows.append({
                **game,
                "run_mean_version": feature.get("run_mean_version"),
                "run_mean_components": feature.get("run_mean_components"),
                "strict_prior_away_mean_runs": away_mean,
                "strict_prior_home_mean_runs": home_mean,
                "model_input_total_mean": away_mean + home_mean,
                "actual_final_total": actual_total,
                "feature_source_hash": feature_hash,
                "baseline_distribution_sha256": dist.result_sha256,
                "baseline_line_probabilities": baseline_lines,
            })
            print(f"[{i}/{len(games)}] {game['game_pk']} {game['away_team']} @ {game['home_team']} baseline ok")
        except Exception as exc:
            failures.append({"game": game, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{i}/{len(games)}] {game['game_pk']} FAILED {type(exc).__name__}: {exc}")

    if not rows:
        raise SystemExit("no games audited")
    if {row.get("run_mean_version") for row in rows} != {PRODUCTION_RUN_MEAN_VERSION}:
        raise SystemExit("audit did not bind exclusively to the current production defense-blend run means")

    tuning = [row for row in rows if date.fromisoformat(row["official_date"]) < validation_start]
    validation = [row for row in rows if date.fromisoformat(row["official_date"]) >= validation_start]
    fit = _fit_dispersion_r(tuning)
    locked_r = float(fit["locked_r"])

    for i, row in enumerate(rows, 1):
        pmf = _candidate_pmf(
            away_mean=float(row["strict_prior_away_mean_runs"]),
            home_mean=float(row["strict_prior_home_mean_runs"]),
            dispersion_r=locked_r,
            simulations=args.simulations,
            identity=str(row["game_pk"]),
        )
        candidate_lines = {}
        for line in REFERENCE_LINES:
            p_over, p_under, p_push = _line_prob(pmf, line)
            candidate_lines[str(line)] = {
                "p_over": p_over,
                "p_under": p_under,
                "p_push": p_push,
                "p_over_ex_push": p_over / (p_over + p_under) if p_over + p_under > 0 else None,
            }
        row["candidate_line_probabilities"] = candidate_lines
        row["candidate_distribution_sha256"] = canonical_json_sha256({
            "version": CANDIDATE_VERSION,
            "dispersion_r": locked_r,
            "pmf": pmf,
        })
        print(f"[{i}/{len(rows)}] {row['game_pk']} candidate ok")

    baseline_validation = _aggregate_line_summaries(validation, "baseline_line_probabilities")
    candidate_validation = _aggregate_line_summaries(validation, "candidate_line_probabilities")
    baseline_tuning = _aggregate_line_summaries(tuning, "baseline_line_probabilities")
    candidate_tuning = _aggregate_line_summaries(tuning, "candidate_line_probabilities")
    baseline_score = _score_distribution(baseline_validation)
    candidate_score = _score_distribution(candidate_validation)

    b95 = baseline_validation.get("9.5") or {}
    c95 = candidate_validation.get("9.5") or {}
    closes_95_gap = (
        b95.get("n", 0) > 0
        and c95.get("n", 0) > 0
        and abs(float(c95["calibration_gap_pp"])) < abs(float(b95["calibration_gap_pp"]))
    )
    improves_mean_gap = (
        baseline_score["mean_abs_calibration_gap_pp"] is not None
        and candidate_score["mean_abs_calibration_gap_pp"] is not None
        and float(candidate_score["mean_abs_calibration_gap_pp"]) < float(baseline_score["mean_abs_calibration_gap_pp"])
    )
    improves_brier = (
        baseline_score["mean_brier"] is not None
        and candidate_score["mean_brier"] is not None
        and float(candidate_score["mean_brier"]) <= float(baseline_score["mean_brier"])
    )

    payload = {
        "schema_version": 1,
        "audit": "MLB_GAME_ENGINE_DISPERSION_STRICT_PRIOR_V1",
        "production_mean_version": PRODUCTION_RUN_MEAN_VERSION,
        "baseline_distribution_version": V7_DISTRIBUTION_VERSION,
        "candidate_distribution_version": CANDIDATE_VERSION,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "tuning_period": {"start": start.isoformat(), "end": (validation_start.replace(day=validation_start.day) - __import__('datetime').timedelta(days=1)).isoformat()},
        "validation_period": {"start": validation_start.isoformat(), "end": end.isoformat()},
        "simulations_per_game_per_distribution": args.simulations,
        "games_requested": len(games),
        "games_audited": len(rows),
        "tuning_games": len(tuning),
        "validation_games": len(validation),
        "failures": failures,
        "dispersion_fit": fit,
        "methodology": [
            "Regular-season final games only; audit cutoff is strictly before 2026-09-29.",
            "Run means come from the current production 50/50 team-offense + opponent-run-prevention blend.",
            "The earlier slice fits one shared Gamma-Poisson dispersion r from final scores; that r is frozen before the later validation slice is scored.",
            "Candidate preserves each team's unconditional mean and changes distribution shape only.",
            "No sportsbook historical prices are used; this audit cannot establish edge, CLV, ROI, or Truth-Gate qualification.",
        ],
        "tuning": {
            "baseline": baseline_tuning,
            "candidate": candidate_tuning,
        },
        "validation": {
            "baseline": baseline_validation,
            "candidate": candidate_validation,
            "baseline_score": baseline_score,
            "candidate_score": candidate_score,
            "checks": {
                "candidate_closes_9_5_calibration_gap": closes_95_gap,
                "candidate_improves_mean_abs_calibration_gap": improves_mean_gap,
                "candidate_noninferior_mean_brier": improves_brier,
                "candidate_passes_all_three": bool(closes_95_gap and improves_mean_gap and improves_brier),
            },
        },
        "games": rows,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(json.dumps({
        "output": str(out),
        "games_audited": len(rows),
        "tuning_games": len(tuning),
        "validation_games": len(validation),
        "dispersion_fit": fit,
        "validation_baseline": baseline_validation,
        "validation_candidate": candidate_validation,
        "validation_checks": payload["validation"]["checks"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
