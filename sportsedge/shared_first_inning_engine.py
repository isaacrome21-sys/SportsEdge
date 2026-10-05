"""Strict-prior empirical NRFI/YRFI engine.

The old production path inferred inning-one scoring from full-game run means via a
single fixed share. This engine prices the first inning from actual strictly-prior
inning-one outcomes for the two teams. Each offense and opponent-allow component
gets a Jeffreys Beta(1/2, 1/2) posterior mean before the two components are blended,
which prevents short samples from emitting 0%/100% scoring probabilities.

Sportsbook prices are never model inputs.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Mapping, Sequence

from .source_lineage import canonical_json_sha256

FIRST_INNING_EMPIRICAL_VERSION = "mlb_first_inning_empirical_jeffreys_v1"
FIRST_INNING_MARKETS = frozenset({"NRFI", "YRFI"})
MIN_HISTORY_GAMES = 10


class FirstInningEmpiricalError(ValueError):
    pass


def _count_pool(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise FirstInningEmpiricalError(f"{field} must be a sequence")
    if len(value) < MIN_HISTORY_GAMES:
        raise FirstInningEmpiricalError(
            f"{field} requires at least {MIN_HISTORY_GAMES} strictly-prior games"
        )
    out: list[int] = []
    for index, raw in enumerate(value):
        if isinstance(raw, bool):
            raise FirstInningEmpiricalError(f"{field}[{index}] must be integer >= 0")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise FirstInningEmpiricalError(
                f"{field}[{index}] must be integer >= 0"
            ) from exc
        if not isfinite(numeric) or numeric < 0 or numeric != int(numeric):
            raise FirstInningEmpiricalError(f"{field}[{index}] must be integer >= 0")
        out.append(int(numeric))
    return tuple(out)


def _jeffreys_score_probability(values: Sequence[int]) -> float:
    n = len(values)
    if n <= 0:
        raise FirstInningEmpiricalError("first-inning history cannot be empty")
    scored = sum(1 for value in values if int(value) > 0)
    return (float(scored) + 0.5) / (float(n) + 1.0)


def _matchup_score_probability(offense: Sequence[int], opponent_allowed: Sequence[int]) -> float:
    # Equal source weighting prevents the longer history from silently dominating
    # when one club has fewer admissible strictly-prior games.
    return 0.5 * (
        _jeffreys_score_probability(offense)
        + _jeffreys_score_probability(opponent_allowed)
    )


def build_shared_first_inning_engine_session():
    cache: dict[str, tuple[float, float]] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        market = str(model_input.get("market", "")).upper()
        if market not in FIRST_INNING_MARKETS:
            raise FirstInningEmpiricalError(f"unsupported first-inning market: {market}")
        game_id = str(model_input.get("game_id") or "").strip()
        if not game_id:
            raise FirstInningEmpiricalError("game_id required")
        features = model_input.get("features")
        if not isinstance(features, Mapping):
            raise FirstInningEmpiricalError("first-inning features required")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not feature_source_hash:
            raise FirstInningEmpiricalError("feature_source_hash required")

        away_for = _count_pool(
            features.get("away_first_inning_runs_for"),
            "away_first_inning_runs_for",
        )
        away_against = _count_pool(
            features.get("away_first_inning_runs_against"),
            "away_first_inning_runs_against",
        )
        home_for = _count_pool(
            features.get("home_first_inning_runs_for"),
            "home_first_inning_runs_for",
        )
        home_against = _count_pool(
            features.get("home_first_inning_runs_against"),
            "home_first_inning_runs_against",
        )

        identity = {
            "engine": FIRST_INNING_EMPIRICAL_VERSION,
            "game_id": game_id,
            "feature_source_hash": feature_source_hash,
            "away_first_inning_runs_for": away_for,
            "away_first_inning_runs_against": away_against,
            "home_first_inning_runs_for": home_for,
            "home_first_inning_runs_against": home_against,
        }
        model_input_hash = canonical_json_sha256(identity)
        cached = cache.get(model_input_hash)
        if cached is None:
            away_score_p = _matchup_score_probability(away_for, home_against)
            home_score_p = _matchup_score_probability(home_for, away_against)
            nrfi = (1.0 - away_score_p) * (1.0 - home_score_p)
            nrfi = min(1.0, max(0.0, nrfi))
            cached = (nrfi, 1.0 - nrfi)
            cache[model_input_hash] = cached
        nrfi, yrfi = cached

        side = str(model_input.get("side") or "").upper()
        if market == "NRFI":
            if side in {"YES", "NRFI"}:
                p = nrfi
            elif side == "NO":
                p = yrfi
            else:
                raise FirstInningEmpiricalError("NRFI side must be YES/NO")
        else:
            if side in {"YES", "YRFI"}:
                p = yrfi
            elif side == "NO":
                p = nrfi
            else:
                raise FirstInningEmpiricalError("YRFI side must be YES/NO")

        return {
            "game_id": model_input.get("game_id"),
            "market": market,
            "entity_id": model_input.get("entity_id"),
            "line": model_input.get("line"),
            "side": model_input.get("side"),
            "model_p": float(p),
            "push_p": 0.0,
            "model_input_hash": model_input_hash,
            "engine_version": FIRST_INNING_EMPIRICAL_VERSION,
            "seed_policy": "analytic_strict_prior_first_inning_jeffreys",
            "mc_paths": 0,
        }

    return engine
