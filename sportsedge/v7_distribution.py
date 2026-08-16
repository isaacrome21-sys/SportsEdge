from __future__ import annotations

from dataclasses import dataclass, asdict
from math import exp, isfinite
import random
from typing import Any

from .source_lineage import canonical_json_sha256

V7_DISTRIBUTION_VERSION = "mlb_v7_distribution_v1"


class V7DistributionError(ValueError):
    pass


@dataclass(frozen=True)
class GameDistribution:
    simulations: int
    seed: int
    away_mean_runs: float
    home_mean_runs: float
    away_win_probability: float
    home_win_probability: float
    away_plus_1_5_probability: float
    home_minus_1_5_probability: float
    over_probability: float
    under_probability: float
    push_probability: float
    nrfi_probability: float
    yrfi_probability: float
    result_sha256: str


def _finite_positive(value: Any, field: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise V7DistributionError(f"{field} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise V7DistributionError(f"{field} must be numeric") from exc
    if not isfinite(out) or out < 0 or (out == 0 and not allow_zero):
        raise V7DistributionError(f"invalid {field}")
    return out


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
    # Stable approximation for unusually high lambdas; MLB team means are far below this.
    return max(0, int(round(rng.gauss(lam, lam ** 0.5))))


def simulate_game_distribution(
    *,
    away_mean_runs: Any,
    home_mean_runs: Any,
    total_line: Any,
    simulations: int = 50000,
    seed: int = 7,
    shared_game_sigma: Any = 0.12,
    team_sigma: Any = 0.08,
    first_inning_share: Any = 1.0 / 9.0,
) -> GameDistribution:
    away_mean = _finite_positive(away_mean_runs, "away_mean_runs")
    home_mean = _finite_positive(home_mean_runs, "home_mean_runs")
    total = _finite_positive(total_line, "total_line", allow_zero=True)
    shared_sigma = _finite_positive(shared_game_sigma, "shared_game_sigma", allow_zero=True)
    idio_sigma = _finite_positive(team_sigma, "team_sigma", allow_zero=True)
    fi_share = _finite_positive(first_inning_share, "first_inning_share")
    if fi_share > 1:
        raise V7DistributionError("first_inning_share must be <= 1")
    if isinstance(simulations, bool) or int(simulations) < 1000:
        raise V7DistributionError("simulations must be >= 1000")
    simulations = int(simulations)
    seed = int(seed)
    rng = random.Random(seed)

    away_wins = home_wins = away_cover = home_cover = 0
    overs = unders = pushes = yrfi = 0
    away_sum = home_sum = 0

    for _ in range(simulations):
        shared = rng.gauss(0.0, shared_sigma)
        away_noise = rng.gauss(0.0, idio_sigma)
        home_noise = rng.gauss(0.0, idio_sigma)
        away_lam = away_mean * exp(shared + away_noise - 0.5 * (shared_sigma ** 2 + idio_sigma ** 2))
        home_lam = home_mean * exp(shared + home_noise - 0.5 * (shared_sigma ** 2 + idio_sigma ** 2))
        away_runs = _poisson(rng, away_lam)
        home_runs = _poisson(rng, home_lam)
        away_sum += away_runs
        home_sum += home_runs
        if away_runs > home_runs:
            away_wins += 1
        elif home_runs > away_runs:
            home_wins += 1
        else:
            # Pregame baseball ML excludes ties; resolve extra innings symmetrically around latent strength.
            p_home = home_lam / (home_lam + away_lam)
            if rng.random() < p_home:
                home_wins += 1
            else:
                away_wins += 1
        if away_runs + 1.5 > home_runs:
            away_cover += 1
        if home_runs - 1.5 > away_runs:
            home_cover += 1
        game_total = away_runs + home_runs
        if game_total > total:
            overs += 1
        elif game_total < total:
            unders += 1
        else:
            pushes += 1

        # First-inning event is sampled from the same shared scoring environment, not a separate market model.
        fi_lambda = (away_lam + home_lam) * fi_share
        if _poisson(rng, fi_lambda) > 0:
            yrfi += 1

    home_p = home_wins / simulations
    away_p = away_wins / simulations
    over_p = overs / simulations
    under_p = unders / simulations
    push_p = pushes / simulations
    yrfi_p = yrfi / simulations
    nrfi_p = 1.0 - yrfi_p
    raw = {
        "version": V7_DISTRIBUTION_VERSION,
        "simulations": simulations,
        "seed": seed,
        "away_mean_runs": away_sum / simulations,
        "home_mean_runs": home_sum / simulations,
        "away_win_probability": away_p,
        "home_win_probability": home_p,
        "away_plus_1_5_probability": away_cover / simulations,
        "home_minus_1_5_probability": home_cover / simulations,
        "over_probability": over_p,
        "under_probability": under_p,
        "push_probability": push_p,
        "nrfi_probability": nrfi_p,
        "yrfi_probability": yrfi_p,
    }
    digest = canonical_json_sha256(raw)
    return GameDistribution(**{k: raw[k] for k in raw if k != "version"}, result_sha256=digest)


def distribution_payload(result: GameDistribution) -> dict[str, Any]:
    payload = asdict(result)
    payload["distribution_version"] = V7_DISTRIBUTION_VERSION
    return payload
