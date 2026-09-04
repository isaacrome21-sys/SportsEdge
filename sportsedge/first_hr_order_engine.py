"""Ordering-aware candidate for MLB FIRST_HOME_RUN.

The prior scalar model treated hitters as exchangeable. This candidate instead
binds the confirmed 1-9 lineups, estimates strictly-prior HR-per-PA and non-HR
on-base rates for every starter, and simulates the actual away-then-home half-
inning order with three outs per half. The resulting first-HR winner distribution
is generated once per game state and read out per player.

This is a candidate only. Book-specific no-HR settlement policy and all promotion
evidence remain separate gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any, Mapping, Sequence

from .identity_rng import candidate_rng
from .live_slate import LiveGame, TeamLineup
from .mlb_generic_features import MLBGenericHistorySource
from .source_lineage import canonical_json_sha256

FIRST_HR_ENGINE_VERSION = "mlb_first_hr_lineup_order_v1_candidate"
FIRST_HR_READOUT_VERSION = "mlb_first_hr_readout_v1"
MIN_HISTORY_GAMES = 10
HISTORY_WINDOW_GAMES = 30
DEFAULT_SIMULATIONS = 250000
MAX_PA_PER_HALF_INNING = 100


class FirstHROrderError(ValueError):
    pass


@dataclass(frozen=True)
class FirstHRDistribution:
    simulations: int
    winner_probabilities: dict[str, float]
    no_home_run_probability: float
    distribution_sha256: str
    seed_policy: str = "identity_sha256_256bit"
    engine_version: str = FIRST_HR_ENGINE_VERSION


def _count(value: Any, field: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise FirstHROrderError(f"{field} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise FirstHROrderError(f"{field} must be numeric") from exc
    if not isfinite(out) or out < 0:
        raise FirstHROrderError(f"{field} must be finite and >= 0")
    return out


def _primary_lineup(lineup: TeamLineup) -> tuple[tuple[int, int], ...]:
    if not lineup.confirmed:
        raise FirstHROrderError("FIRST_HR_CONFIRMED_LINEUP_REQUIRED")
    slots: dict[int, int] = {}
    for player_id, slot in zip(lineup.player_ids, lineup.batting_slots):
        if slot in slots and slots[slot] != int(player_id):
            raise FirstHROrderError("FIRST_HR_LINEUP_SLOT_AMBIGUOUS")
        slots[int(slot)] = int(player_id)
    if set(slots) != set(range(1, 10)):
        raise FirstHROrderError("FIRST_HR_COMPLETE_1_TO_9_LINEUP_REQUIRED")
    return tuple((slot, slots[slot]) for slot in range(1, 10))


def _player_rates(
    source: MLBGenericHistorySource,
    *,
    player_id: int,
    target_date: date,
) -> tuple[float, float, list[dict[str, Any]]]:
    rows = source.player_rows(player_id=int(player_id), group="hitting", target_date=target_date)[-HISTORY_WINDOW_GAMES:]
    if len(rows) < MIN_HISTORY_GAMES:
        raise FirstHROrderError(
            f"FIRST_HR_PLAYER_HISTORY_INSUFFICIENT:{player_id}:{len(rows)}<{MIN_HISTORY_GAMES}"
        )
    pa = hr = hits = walks = hbp = 0.0
    bound_rows: list[dict[str, Any]] = []
    for row in rows:
        stat = row["stat"]
        row_pa = _count(stat.get("plateAppearances"), "plateAppearances")
        row_hr = _count(stat.get("homeRuns"), "homeRuns")
        row_hits = _count(stat.get("hits"), "hits")
        row_walks = _count(stat.get("baseOnBalls"), "baseOnBalls")
        row_hbp = _count(stat.get("hitByPitch"), "hitByPitch")
        if row_hr > row_hits or row_hits + row_walks + row_hbp > row_pa + 1e-9:
            raise FirstHROrderError(f"FIRST_HR_HISTORY_ACCOUNTING_INVALID:{player_id}")
        pa += row_pa
        hr += row_hr
        hits += row_hits
        walks += row_walks
        hbp += row_hbp
        bound_rows.append({
            "date": row["date"].isoformat(),
            "pa": row_pa,
            "hr": row_hr,
            "hits": row_hits,
            "walks": row_walks,
            "hbp": row_hbp,
        })
    if pa <= 0:
        raise FirstHROrderError(f"FIRST_HR_PLAYER_PA_MISSING:{player_id}")
    p_hr = hr / pa
    p_non_hr_on_base = (hits - hr + walks + hbp) / pa
    if not 0.0 <= p_hr <= 1.0 or not 0.0 <= p_non_hr_on_base <= 1.0:
        raise FirstHROrderError(f"FIRST_HR_RATE_OUT_OF_RANGE:{player_id}")
    if p_hr + p_non_hr_on_base > 1.0 + 1e-12:
        raise FirstHROrderError(f"FIRST_HR_PA_PROBABILITY_OVERFLOW:{player_id}")
    return p_hr, p_non_hr_on_base, bound_rows


def build_first_hr_features(
    source: MLBGenericHistorySource,
    *,
    game: LiveGame,
    target_date: date,
) -> dict[str, Any]:
    away = _primary_lineup(game.away_lineup)
    home = _primary_lineup(game.home_lineup)
    bound_history: dict[str, Any] = {}

    def build(side: str, lineup: tuple[tuple[int, int], ...]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for slot, player_id in lineup:
            p_hr, p_non_hr_on_base, rows = _player_rates(
                source,
                player_id=player_id,
                target_date=target_date,
            )
            bound_history[str(player_id)] = rows
            out.append({
                "player_id": player_id,
                "side": side,
                "slot": slot,
                "p_hr": p_hr,
                "p_non_hr_on_base": p_non_hr_on_base,
            })
        return out

    features = {"away_lineup": build("AWAY", away), "home_lineup": build("HOME", home)}
    identity = {
        "version": FIRST_HR_ENGINE_VERSION,
        "game_pk": int(game.game_pk),
        "target_date": target_date.isoformat(),
        "retrieved_at": source.retrieved_at.isoformat(),
        "features": features,
        "strictly_prior_history": bound_history,
    }
    return {
        "feature_version": FIRST_HR_ENGINE_VERSION,
        "feature_source_hash": canonical_json_sha256(identity),
        "features": features,
    }


def _lineup(value: Any, side: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 9:
        raise FirstHROrderError(f"{side} lineup must contain exactly 9 starters")
    out: list[dict[str, Any]] = []
    slots: set[int] = set()
    players: set[int] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise FirstHROrderError(f"{side} lineup row malformed")
        try:
            player_id = int(raw.get("player_id"))
            slot = int(raw.get("slot"))
            p_hr = float(raw.get("p_hr"))
            p_non = float(raw.get("p_non_hr_on_base"))
        except (TypeError, ValueError) as exc:
            raise FirstHROrderError(f"{side} lineup row invalid") from exc
        if player_id <= 0 or slot not in range(1, 10) or slot in slots or player_id in players:
            raise FirstHROrderError(f"{side} lineup identity invalid")
        if not isfinite(p_hr) or not isfinite(p_non) or p_hr < 0 or p_non < 0 or p_hr + p_non > 1:
            raise FirstHROrderError(f"{side} lineup probability invalid")
        slots.add(slot); players.add(player_id)
        out.append({"player_id": player_id, "slot": slot, "p_hr": p_hr, "p_non_hr_on_base": p_non})
    out.sort(key=lambda row: row["slot"])
    return tuple(out)


def simulate_first_hr_distribution(
    features: Mapping[str, Any],
    *,
    simulations: int = DEFAULT_SIMULATIONS,
    build_hash: str,
) -> FirstHRDistribution:
    if isinstance(simulations, bool) or int(simulations) < 1000:
        raise FirstHROrderError("simulations must be >= 1000")
    simulations = int(simulations)
    away = _lineup(features.get("away_lineup"), "AWAY")
    home = _lineup(features.get("home_lineup"), "HOME")
    rng = candidate_rng(build_hash)
    winners: dict[str, int] = {}
    no_hr = 0

    for _ in range(simulations):
        indices = {"AWAY": 0, "HOME": 0}
        winner: int | None = None
        for _inning in range(1, 10):
            for side, lineup in (("AWAY", away), ("HOME", home)):
                outs = 0
                pa_guard = 0
                while outs < 3 and pa_guard < MAX_PA_PER_HALF_INNING:
                    batter = lineup[indices[side] % 9]
                    indices[side] += 1
                    pa_guard += 1
                    u = rng.random()
                    if u < batter["p_hr"]:
                        winner = int(batter["player_id"])
                        break
                    if u >= batter["p_hr"] + batter["p_non_hr_on_base"]:
                        outs += 1
                if winner is not None:
                    break
                if pa_guard >= MAX_PA_PER_HALF_INNING and outs < 3:
                    raise FirstHROrderError("FIRST_HR_HALF_INNING_GUARD_EXCEEDED")
            if winner is not None:
                break
        if winner is None:
            no_hr += 1
        else:
            key = str(winner)
            winners[key] = winners.get(key, 0) + 1

    probabilities = {player_id: count / simulations for player_id, count in sorted(winners.items())}
    no_hr_probability = no_hr / simulations
    if abs(sum(probabilities.values()) + no_hr_probability - 1.0) > 1e-12:
        raise FirstHROrderError("FIRST_HR_DISTRIBUTION_MASS_INVALID")
    digest = canonical_json_sha256({
        "version": FIRST_HR_ENGINE_VERSION,
        "simulations": simulations,
        "winner_probabilities": probabilities,
        "no_home_run_probability": no_hr_probability,
    })
    return FirstHRDistribution(
        simulations=simulations,
        winner_probabilities=probabilities,
        no_home_run_probability=no_hr_probability,
        distribution_sha256=digest,
    )


def build_shared_first_hr_engine_session():
    cache: dict[str, FirstHRDistribution] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        if str(model_input.get("market") or "").upper() != "FIRST_HOME_RUN":
            raise FirstHROrderError("shared first-HR engine requires FIRST_HOME_RUN")
        game_id = str(model_input.get("game_id") or "").strip()
        entity_id = str(model_input.get("entity_id") or "").strip()
        side = str(model_input.get("side") or "").upper()
        features = model_input.get("features")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not game_id or not entity_id or not isinstance(features, Mapping) or not feature_source_hash:
            raise FirstHROrderError("FIRST_HR_MODEL_IDENTITY_INCOMPLETE")
        if side not in {"YES", "NO"}:
            raise FirstHROrderError("FIRST_HOME_RUN side must be YES or NO")
        simulations = int(model_input.get("simulations", DEFAULT_SIMULATIONS))
        stochastic_identity = {
            "engine": FIRST_HR_ENGINE_VERSION,
            "game_id": game_id,
            "feature_source_hash": feature_source_hash,
            "features": dict(features),
        }
        build_hash = canonical_json_sha256(stochastic_identity)
        model_input_hash = canonical_json_sha256({**stochastic_identity, "simulations": simulations})
        distribution = cache.get(model_input_hash)
        if distribution is None:
            distribution = simulate_first_hr_distribution(
                features,
                simulations=simulations,
                build_hash=build_hash,
            )
            cache[model_input_hash] = distribution
        p_yes = float(distribution.winner_probabilities.get(entity_id, 0.0))
        model_p = p_yes if side == "YES" else 1.0 - p_yes
        readout_sha = canonical_json_sha256({
            "version": FIRST_HR_READOUT_VERSION,
            "distribution_sha256": distribution.distribution_sha256,
            "entity_id": entity_id,
            "side": side,
            "model_p": model_p,
        })
        return {
            "game_id": model_input.get("game_id"),
            "market": "FIRST_HOME_RUN",
            "entity_id": model_input.get("entity_id"),
            "line": model_input.get("line"),
            "side": model_input.get("side"),
            "model_p": model_p,
            "push_p": 0.0,
            "model_input_hash": model_input_hash,
            "distribution_sha256": distribution.distribution_sha256,
            "readout_sha256": readout_sha,
            "readout_version": FIRST_HR_READOUT_VERSION,
            "engine_version": FIRST_HR_ENGINE_VERSION,
            "seed_policy": distribution.seed_policy,
            "mc_paths": distribution.simulations,
            "no_home_run_probability": distribution.no_home_run_probability,
        }

    return engine
