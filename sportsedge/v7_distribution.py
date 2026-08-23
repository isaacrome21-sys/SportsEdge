from __future__ import annotations

from dataclasses import dataclass, asdict
from math import exp, isfinite
import random
from typing import Any

from .identity_rng import candidate_rng
from .source_lineage import canonical_json_sha256

V7_DISTRIBUTION_VERSION = "mlb_v7_distribution_v2_candidate"
DEFAULT_FIRST_INNING_SHARE = 0.118
DEFAULT_FIRST_INNING_DISPERSION_R = 0.35
DEFAULT_EXTRA_HALF_INNING_MEAN = 0.55


class V7DistributionError(ValueError):
    pass


@dataclass(frozen=True)
class GameDistribution:
    simulations: int
    seed_policy: str
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
    regulation_tie_probability: float
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
    return max(0, int(round(rng.gauss(lam, lam ** 0.5))))


def _negative_binomial(rng: random.Random, mean: float, dispersion_r: float) -> int:
    """Gamma-Poisson negative-binomial draw parameterized by mean and size r."""
    if mean <= 0:
        return 0
    rate = rng.gammavariate(dispersion_r, mean / dispersion_r)
    return _poisson(rng, rate)


def _resolve_extras(
    rng: random.Random,
    away_runs: int,
    home_runs: int,
    *,
    away_lam: float,
    home_lam: float,
    extra_half_inning_mean: float,
) -> tuple[int, int]:
    """Resolve tied regulation paths into a coherent final score.

    The candidate extras model uses the regulation latent-strength ratio to scale
    a ghost-runner-era half-inning mean. Home scoring is walk-off truncated: once
    the home club scores the winning run, no additional home runs are credited.
    This is a candidate model addition and must earn behavioral validation before
    production promotion.
    """
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
    # Extremely rare safety fallback: preserve score coherence rather than return a tie.
    p_home = home_lam / (home_lam + away_lam)
    if rng.random() < p_home:
        home_runs += 1
    else:
        away_runs += 1
    return away_runs, home_runs


def simulate_game_distribution(
    *,
    away_mean_runs: Any,
    home_mean_runs: Any,
    total_line: Any,
    simulations: int = 50000,
    seed: int | None = None,
    build_hash: str | None = None,
    shared_game_sigma: Any = 0.12,
    team_sigma: Any = 0.08,
    first_inning_share: Any = DEFAULT_FIRST_INNING_SHARE,
    first_inning_dispersion_r: Any = DEFAULT_FIRST_INNING_DISPERSION_R,
    extra_half_inning_mean: Any = DEFAULT_EXTRA_HALF_INNING_MEAN,
) -> GameDistribution:
    away_mean = _finite_positive(away_mean_runs, "away_mean_runs")
    home_mean = _finite_positive(home_mean_runs, "home_mean_runs")
    total = _finite_positive(total_line, "total_line", allow_zero=True)
    shared_sigma = _finite_positive(shared_game_sigma, "shared_game_sigma", allow_zero=True)
    idio_sigma = _finite_positive(team_sigma, "team_sigma", allow_zero=True)
    fi_share = _finite_positive(first_inning_share, "first_inning_share")
    fi_r = _finite_positive(first_inning_dispersion_r, "first_inning_dispersion_r")
    extras_mean = _finite_positive(extra_half_inning_mean, "extra_half_inning_mean")
    if fi_share > 1:
        raise V7DistributionError("first_inning_share must be <= 1")
    if isinstance(simulations, bool) or int(simulations) < 1000:
        raise V7DistributionError("simulations must be >= 1000")
    simulations = int(simulations)
    if build_hash is not None and seed is not None:
        raise V7DistributionError("provide build_hash or seed, not both")
    if build_hash is not None:
        rng = candidate_rng(build_hash)
        seed_policy = "identity_sha256_256bit"
    elif seed is not None:
        rng = random.Random(int(seed))
        seed_policy = "explicit_test_seed"
    else:
        raise V7DistributionError("identity-bound build_hash required when explicit test seed is absent")

    away_wins = home_wins = away_cover = home_cover = 0
    overs = unders = pushes = yrfi = regulation_ties = 0
    away_sum = home_sum = 0

    for _ in range(simulations):
        shared = rng.gauss(0.0, shared_sigma)
        away_noise = rng.gauss(0.0, idio_sigma)
        home_noise = rng.gauss(0.0, idio_sigma)
        away_lam = away_mean * exp(shared + away_noise - 0.5 * (shared_sigma ** 2 + idio_sigma ** 2))
        home_lam = home_mean * exp(shared + home_noise - 0.5 * (shared_sigma ** 2 + idio_sigma ** 2))
        away_runs = _poisson(rng, away_lam)
        home_runs = _poisson(rng, home_lam)

        # First inning is modeled per half-inning with overdispersion. Splitting the
        # means preserves offense asymmetry; using only the combined lambda cannot.
        away_fi = _negative_binomial(rng, away_lam * fi_share, fi_r)
        home_fi = _negative_binomial(rng, home_lam * fi_share, fi_r)
        if away_fi + home_fi > 0:
            yrfi += 1

        if away_runs == home_runs:
            regulation_ties += 1
            away_runs, home_runs = _resolve_extras(
                rng,
                away_runs,
                home_runs,
                away_lam=away_lam,
                home_lam=home_lam,
                extra_half_inning_mean=extras_mean,
            )

        away_sum += away_runs
        home_sum += home_runs
        if away_runs > home_runs:
            away_wins += 1
        else:
            home_wins += 1
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

    raw = {
        "version": V7_DISTRIBUTION_VERSION,
        "simulations": simulations,
        "seed_policy": seed_policy,
        "away_mean_runs": away_sum / simulations,
        "home_mean_runs": home_sum / simulations,
        "away_win_probability": away_wins / simulations,
        "home_win_probability": home_wins / simulations,
        "away_plus_1_5_probability": away_cover / simulations,
        "home_minus_1_5_probability": home_cover / simulations,
        "over_probability": overs / simulations,
        "under_probability": unders / simulations,
        "push_probability": pushes / simulations,
        "nrfi_probability": 1.0 - (yrfi / simulations),
        "yrfi_probability": yrfi / simulations,
        "regulation_tie_probability": regulation_ties / simulations,
    }
    digest = canonical_json_sha256(raw)
    return GameDistribution(**{k: raw[k] for k in raw if k != "version"}, result_sha256=digest)


def distribution_payload(result: GameDistribution) -> dict[str, Any]:
    payload = asdict(result)
    payload["distribution_version"] = V7_DISTRIBUTION_VERSION
    return payload
