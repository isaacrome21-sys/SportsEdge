"""Report-only, out-of-fold G1 probability diagnostics on the frozen score grid."""
from __future__ import annotations

from math import isfinite, log
from .discrete_v2 import MEAN_CEILING, MEAN_FLOOR, load_freeze, score_grid
from .location_symmetric_g1 import team_means_from_location


def _finite(value):
    if isinstance(value, bool):
        raise ValueError("NFL_G1_DISTRIBUTION_BOOLEAN_INVALID")
    value = float(value)
    if not isfinite(value):
        raise ValueError("NFL_G1_DISTRIBUTION_NONFINITE")
    return value


def _market(cells, target, line):
    win = push = loss = 0.0
    for home, away, p in cells:
        delta = home - away + line if target == "spread" else home + away - line
        if delta > 0:
            win += p
        elif delta < 0:
            loss += p
        else:
            push += p
    return win, push, loss


def distribution_readout(rows):
    """Score already-produced held-out locations; never fit or select anything.

    Spread is home handicap; total is over. Three-outcome log loss scores
    win/push/loss directly. Moneyline Brier/calibration condition on no tie.
    The shape was developed on reused history, so these are diagnostics only.
    """
    data = list(rows)
    if not data:
        raise ValueError("NFL_G1_DISTRIBUTION_ROWS_REQUIRED")
    briers = []
    bins = [[] for _ in range(10)]
    markets = {m: {"losses": [], "push": [], "actual_push": 0, "missing_lines": 0} for m in ("spread", "total")}
    keys = {m: {"mass": [], "actual": 0} for m in (-7, -3, 3, 7)}
    ties = 0
    identities = set()
    # Validate the frozen score shape once per readout, then reuse those exact
    # immutable-in-practice bytes for every held-out game. This avoids one
    # filesystem read, JSON parse and SHA check per game without caching
    # across invocations or changing any probability calculation.
    frozen_shape = load_freeze()
    for row in data:
        identity = (row["season"], row["game_id"])
        if identity in identities:
            raise ValueError("NFL_G1_DISTRIBUTION_DUPLICATE_GAME")
        identities.add(identity)
        if max(row["train_seasons"]) >= int(row["season"]):
            raise ValueError("NFL_G1_DISTRIBUTION_TRAIN_TEST_OVERLAP")
        home, away = (_finite(row[k]) for k in ("home_score", "away_score"))
        if any(v < 0 or not v.is_integer() for v in (home, away)):
            raise ValueError("NFL_G1_DISTRIBUTION_REAL_INTEGER_SCORE_REQUIRED")
        means = team_means_from_location(row["predicted_margin"], row["predicted_total"])
        if any(not MEAN_FLOOR <= v <= MEAN_CEILING for v in means.values()):
            raise ValueError("NFL_G1_DISTRIBUTION_MEAN_OUTSIDE_FROZEN_GRID")
        grid = score_grid(means["mean_home"], means["mean_away"], freeze=frozen_shape)
        cells = [(h, a, p) for h, line in enumerate(grid) for a, p in enumerate(line)]
        if any(not isfinite(p) or p < 0 for _, _, p in cells) or abs(sum(p for _, _, p in cells) - 1) > 1e-9:
            raise ValueError("NFL_G1_DISTRIBUTION_GRID_INVALID")
        win, push, loss = _market(cells, "spread", 0.0)
        if home == away:
            ties += 1
        else:
            prob = win / (win + loss)
            actual = float(home > away)
            briers.append((prob - actual) ** 2)
            bins[min(9, int(prob * 10))].append((prob, actual))
        for margin in keys:
            keys[margin]["mass"].append(sum(p for h, a, p in cells if h - a == margin))
            keys[margin]["actual"] += int(home - away == margin)
        for market, stats in markets.items():
            raw = row.get(market + "_line")
            if raw is None or raw == "":
                stats["missing_lines"] += 1
                continue
            line = _finite(raw)
            probabilities = _market(cells, market, line)
            delta = home - away + line if market == "spread" else home + away - line
            index = 0 if delta > 0 else 2 if delta < 0 else 1
            stats["losses"].append(-log(max(1e-15, probabilities[index])))
            stats["push"].append(probabilities[1])
            stats["actual_push"] += int(index == 1)
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    calibration = [{"bin": i, "n": len(values), "mean_p": mean([p for p, _ in values]),
                    "observed_rate": mean([y for _, y in values])} for i, values in enumerate(bins)]
    return {
        "schema": "NFL_G1_DISTRIBUTION_DIAGNOSTICS_V1", "status": "REPORT_ONLY_NOT_VALIDATED_EDGE",
        "n": len(data), "moneyline": {"non_tie_n": len(briers), "excluded_ties": ties,
            "conditional_non_tie_brier": mean(briers), "calibration_bins": calibration,
            "ece_10_equal_width_bins": sum(r["n"] * abs(r["mean_p"] - r["observed_rate"]) for r in calibration if r["n"]) / len(briers) if briers else None},
        "markets": {m: {"n": len(s["losses"]), "missing_lines": s["missing_lines"],
            "win_push_loss_log_loss": mean(s["losses"]), "mean_push_probability": mean(s["push"]),
            "actual_pushes": s["actual_push"]} for m, s in markets.items()},
        "signed_key_mass": {str(k): {"predicted": mean(v["mass"]), "observed": v["actual"] / len(data)} for k, v in keys.items()},
        "team_total_probability_sanity": "NORMALIZED_NONNEGATIVE_SHARED_GRID",
        "shape_history_reused": True, "closing_lines_used_for_scoring_only": True,
        "selection_or_retuning_authority": False, "promotion_authority": False,
        "log_loss_probability_floor": 1e-15,
    }
