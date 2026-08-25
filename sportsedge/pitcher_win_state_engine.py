"""Game-state candidate for MLB PITCHER_RECORD_WIN.

The retired incumbent used a rolling mean of prior pitcher wins. This candidate
never consumes historical win decisions. It binds both probable starters, strictly-
prior starter workload/run-prevention rows, and current team scoring means; then it
simulates inning state, starter exit, the five-inning starter qualification rule, and
post-exit bullpen lead preservation. A starter receives a modeled win only when his
team is ahead at his exit and that lead is never relinquished afterward.

This is candidate code only. Official-scorer settlement evidence and all behavioral
promotion gates remain separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import exp, isfinite
from typing import Any, Mapping, Sequence

from .identity_rng import candidate_rng
from .live_slate import LiveGame
from .mlb_generic_features import MLBGenericHistorySource
from .source_lineage import canonical_json_sha256

PITCHER_WIN_ENGINE_VERSION = "mlb_pitcher_win_game_state_v1_candidate"
PITCHER_WIN_READOUT_VERSION = "mlb_pitcher_win_readout_v1"
DEFAULT_SIMULATIONS = 50000
MIN_START_HISTORY = 8
HISTORY_WINDOW_STARTS = 20
STARTER_WIN_MIN_OUTS = 15


class PitcherWinStateError(ValueError):
    pass


@dataclass(frozen=True)
class PitcherWinDistribution:
    simulations: int
    away_starter_id: str
    home_starter_id: str
    away_starter_win_probability: float
    home_starter_win_probability: float
    no_starting_pitcher_win_probability: float
    distribution_sha256: str
    seed_policy: str = "identity_sha256_256bit"
    engine_version: str = PITCHER_WIN_ENGINE_VERSION


def _number(value: Any, field: str, *, lower: float = 0.0) -> float:
    if isinstance(value, bool):
        raise PitcherWinStateError(f"{field} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherWinStateError(f"{field} must be numeric") from exc
    if not isfinite(out) or out < lower:
        raise PitcherWinStateError(f"{field} out of range")
    return out


def _outs_from_ip(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        raise PitcherWinStateError("inningsPitched missing")
    whole, sep, frac = text.partition(".")
    try:
        base = int(whole) * 3
    except ValueError as exc:
        raise PitcherWinStateError("inningsPitched invalid") from exc
    if not sep:
        outs = base
    else:
        if frac not in {"0", "1", "2"}:
            raise PitcherWinStateError("inningsPitched uses invalid baseball notation")
        outs = base + int(frac)
    if not 0 <= outs <= 27:
        raise PitcherWinStateError("starter outs must be in [0,27]")
    return outs


def _starter_history(
    source: MLBGenericHistorySource,
    *,
    pitcher_id: int,
    target_date: date,
) -> list[dict[str, Any]]:
    rows = source.player_rows(player_id=int(pitcher_id), group="pitching", target_date=target_date)
    starts: list[dict[str, Any]] = []
    for row in rows:
        stat = row.get("stat")
        if not isinstance(stat, Mapping):
            continue
        if _number(stat.get("gamesStarted", 0), "gamesStarted") < 1:
            continue
        try:
            outs = _outs_from_ip(stat.get("inningsPitched"))
            earned_runs = _number(stat.get("earnedRuns", 0), "earnedRuns")
        except PitcherWinStateError:
            continue
        starts.append({
            "date": row["date"].isoformat(),
            "outs": outs,
            "earned_runs": earned_runs,
        })
    starts = starts[-HISTORY_WINDOW_STARTS:]
    if len(starts) < MIN_START_HISTORY:
        raise PitcherWinStateError(
            f"PITCHER_WIN_START_HISTORY_INSUFFICIENT:{pitcher_id}:{len(starts)}<{MIN_START_HISTORY}"
        )
    return starts


def build_pitcher_win_features(
    source: MLBGenericHistorySource,
    *,
    game: LiveGame,
    target_date: date,
) -> dict[str, Any]:
    if game.away_probable_pitcher_id is None or game.home_probable_pitcher_id is None:
        raise PitcherWinStateError("PITCHER_WIN_BOTH_PROBABLE_STARTERS_REQUIRED")
    away_id = int(game.away_probable_pitcher_id)
    home_id = int(game.home_probable_pitcher_id)
    away_history = _starter_history(source, pitcher_id=away_id, target_date=target_date)
    home_history = _starter_history(source, pitcher_id=home_id, target_date=target_date)
    away_mean, home_mean, _ = source.team_means(
        away_team_id=int(game.away_team_id),
        home_team_id=int(game.home_team_id),
        target_date=target_date,
    )
    features = {
        "away_team_id": int(game.away_team_id),
        "home_team_id": int(game.home_team_id),
        "away_starter_id": away_id,
        "home_starter_id": home_id,
        "away_team_mean_runs": float(away_mean),
        "home_team_mean_runs": float(home_mean),
        "away_starter_history": away_history,
        "home_starter_history": home_history,
    }
    identity = {
        "version": PITCHER_WIN_ENGINE_VERSION,
        "game_pk": int(game.game_pk),
        "target_date": target_date.isoformat(),
        "retrieved_at": source.retrieved_at.isoformat(),
        "features": features,
    }
    return {
        "feature_version": PITCHER_WIN_ENGINE_VERSION,
        "feature_source_hash": canonical_json_sha256(identity),
        "features": features,
    }


def starter_win_credit(*, outs_recorded: int, leading_at_exit: bool, lead_relinquished: bool) -> bool:
    """Apply the structural starter-win credit gate used by the simulator."""
    return bool(
        int(outs_recorded) >= STARTER_WIN_MIN_OUTS
        and leading_at_exit
        and not lead_relinquished
    )


def _clean_history(value: Any, label: str) -> tuple[dict[str, float], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PitcherWinStateError(f"{label} must be a sequence")
    out: list[dict[str, float]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise PitcherWinStateError(f"{label} row malformed")
        outs = int(_number(row.get("outs"), f"{label}.outs"))
        if not 0 <= outs <= 27:
            raise PitcherWinStateError(f"{label}.outs out of range")
        earned_runs = _number(row.get("earned_runs"), f"{label}.earned_runs")
        out.append({"outs": float(outs), "earned_runs": earned_runs})
    if len(out) < MIN_START_HISTORY:
        raise PitcherWinStateError(f"{label} insufficient history")
    return tuple(out[-HISTORY_WINDOW_STARTS:])


def _starter_ra9(history: Sequence[Mapping[str, float]]) -> float:
    total_outs = sum(float(row["outs"]) for row in history)
    total_er = sum(float(row["earned_runs"]) for row in history)
    if total_outs <= 0:
        raise PitcherWinStateError("starter history has zero outs")
    return max(0.0, total_er * 27.0 / total_outs)


def _poisson(rng, lam: float) -> int:
    if lam <= 0:
        return 0
    if not isfinite(lam) or lam > 20:
        raise PitcherWinStateError("half-inning run rate out of range")
    threshold = exp(-lam)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def _team_leads(side: str, away_runs: int, home_runs: int) -> bool:
    return away_runs > home_runs if side == "AWAY" else home_runs > away_runs


def _starter_fraction(outs_recorded: int, inning: int) -> float:
    prior_outs = (inning - 1) * 3
    remaining = int(outs_recorded) - prior_outs
    if remaining <= 0:
        return 0.0
    if remaining >= 3:
        return 1.0
    return remaining / 3.0


def simulate_pitcher_win_distribution(
    features: Mapping[str, Any],
    *,
    simulations: int = DEFAULT_SIMULATIONS,
    build_hash: str,
) -> PitcherWinDistribution:
    if isinstance(simulations, bool) or int(simulations) < 1000:
        raise PitcherWinStateError("simulations must be integer >= 1000")
    simulations = int(simulations)
    try:
        away_starter_id = str(int(features.get("away_starter_id")))
        home_starter_id = str(int(features.get("home_starter_id")))
    except (TypeError, ValueError) as exc:
        raise PitcherWinStateError("probable starter identity missing") from exc
    away_mean = _number(features.get("away_team_mean_runs"), "away_team_mean_runs", lower=0.000001)
    home_mean = _number(features.get("home_team_mean_runs"), "home_team_mean_runs", lower=0.000001)
    away_history = _clean_history(features.get("away_starter_history"), "away_starter_history")
    home_history = _clean_history(features.get("home_starter_history"), "home_starter_history")

    # Blend current opponent scoring with the starter's own strictly-prior ER/9.
    # After the starter exits, the simulation explicitly transitions to the
    # opponent's current team scoring baseline as a separate bullpen state.
    away_starter_allowed = 0.5 * home_mean + 0.5 * _starter_ra9(away_history)
    home_starter_allowed = 0.5 * away_mean + 0.5 * _starter_ra9(home_history)
    rng = candidate_rng(build_hash)
    starter_wins = {"AWAY": 0, "HOME": 0}

    for _ in range(simulations):
        sampled_outs = {
            "AWAY": int(away_history[rng.randrange(len(away_history))]["outs"]),
            "HOME": int(home_history[rng.randrange(len(home_history))]["outs"]),
        }
        states = {
            "AWAY": {"recorded": False, "leading_at_exit": False, "lead_relinquished": False},
            "HOME": {"recorded": False, "leading_at_exit": False, "lead_relinquished": False},
        }
        away_runs = 0
        home_runs = 0

        def record_exit(side: str) -> None:
            state = states[side]
            if state["recorded"]:
                return
            state["recorded"] = True
            state["leading_at_exit"] = _team_leads(side, away_runs, home_runs)

        def check_relinquished() -> None:
            for side in ("AWAY", "HOME"):
                state = states[side]
                if state["recorded"] and state["leading_at_exit"] and not state["lead_relinquished"]:
                    if not _team_leads(side, away_runs, home_runs):
                        state["lead_relinquished"] = True

        def play_half(*, offense: str, fielding: str, inning: int) -> None:
            nonlocal away_runs, home_runs
            outs = sampled_outs[fielding]
            prior_outs = (inning - 1) * 3
            if not states[fielding]["recorded"] and outs <= prior_outs:
                record_exit(fielding)
            starter_fraction = _starter_fraction(outs, inning)
            bullpen_fraction = 1.0 - starter_fraction
            starter_rate = home_starter_allowed if fielding == "HOME" else away_starter_allowed
            bullpen_rate = away_mean if offense == "AWAY" else home_mean

            if starter_fraction > 0:
                runs = _poisson(rng, (starter_rate / 9.0) * starter_fraction)
                if offense == "AWAY":
                    away_runs += runs
                else:
                    home_runs += runs
                check_relinquished()

            if not states[fielding]["recorded"] and prior_outs < outs <= prior_outs + 3:
                record_exit(fielding)

            if bullpen_fraction > 0:
                runs = _poisson(rng, (bullpen_rate / 9.0) * bullpen_fraction)
                if offense == "AWAY":
                    away_runs += runs
                else:
                    home_runs += runs
                check_relinquished()

        for inning in range(1, 10):
            play_half(offense="AWAY", fielding="HOME", inning=inning)
            if inning == 9 and home_runs > away_runs:
                break
            play_half(offense="HOME", fielding="AWAY", inning=inning)

        # Complete-game starters exit at game end if their sampled workload was
        # actually reached. A road starter cannot record a ninth inning when the
        # game ends before the bottom half, which correctly leaves him ineligible.
        for side in ("AWAY", "HOME"):
            if not states[side]["recorded"]:
                reached = 27 if side == "HOME" else (27 if home_runs <= away_runs else 24)
                if sampled_outs[side] <= reached:
                    record_exit(side)

        credited = []
        for side in ("AWAY", "HOME"):
            state = states[side]
            if state["recorded"] and starter_win_credit(
                outs_recorded=sampled_outs[side],
                leading_at_exit=bool(state["leading_at_exit"]),
                lead_relinquished=bool(state["lead_relinquished"]),
            ):
                credited.append(side)
        if len(credited) > 1:
            raise PitcherWinStateError("both starters cannot receive a win")
        if credited:
            starter_wins[credited[0]] += 1

    away_p = starter_wins["AWAY"] / simulations
    home_p = starter_wins["HOME"] / simulations
    residual = 1.0 - away_p - home_p
    if away_p < 0 or home_p < 0 or residual < -1e-12:
        raise PitcherWinStateError("pitcher-win probability mass invalid")
    residual = max(0.0, residual)
    digest = canonical_json_sha256({
        "version": PITCHER_WIN_ENGINE_VERSION,
        "simulations": simulations,
        "away_starter_id": away_starter_id,
        "home_starter_id": home_starter_id,
        "away_starter_win_probability": away_p,
        "home_starter_win_probability": home_p,
        "no_starting_pitcher_win_probability": residual,
    })
    return PitcherWinDistribution(
        simulations=simulations,
        away_starter_id=away_starter_id,
        home_starter_id=home_starter_id,
        away_starter_win_probability=away_p,
        home_starter_win_probability=home_p,
        no_starting_pitcher_win_probability=residual,
        distribution_sha256=digest,
    )


def build_shared_pitcher_win_engine_session():
    cache: dict[str, PitcherWinDistribution] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        if str(model_input.get("market") or "").upper() != "PITCHER_RECORD_WIN":
            raise PitcherWinStateError("shared pitcher-win engine requires PITCHER_RECORD_WIN")
        game_id = str(model_input.get("game_id") or "").strip()
        entity_id = str(model_input.get("entity_id") or "").strip()
        side = str(model_input.get("side") or "").upper()
        features = model_input.get("features")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not game_id or not entity_id or not isinstance(features, Mapping) or not feature_source_hash:
            raise PitcherWinStateError("PITCHER_WIN_MODEL_IDENTITY_INCOMPLETE")
        if side not in {"YES", "NO"}:
            raise PitcherWinStateError("PITCHER_RECORD_WIN side must be YES or NO")
        simulations = int(model_input.get("simulations", DEFAULT_SIMULATIONS))
        stochastic_identity = {
            "engine": PITCHER_WIN_ENGINE_VERSION,
            "game_id": game_id,
            "feature_source_hash": feature_source_hash,
            "features": dict(features),
        }
        build_hash = canonical_json_sha256(stochastic_identity)
        model_input_hash = canonical_json_sha256({**stochastic_identity, "simulations": simulations})
        distribution = cache.get(model_input_hash)
        if distribution is None:
            distribution = simulate_pitcher_win_distribution(
                features,
                simulations=simulations,
                build_hash=build_hash,
            )
            cache[model_input_hash] = distribution
        if entity_id == distribution.away_starter_id:
            p_yes = distribution.away_starter_win_probability
        elif entity_id == distribution.home_starter_id:
            p_yes = distribution.home_starter_win_probability
        else:
            raise PitcherWinStateError("PITCHER_RECORD_WIN_ENTITY_NOT_PROBABLE_STARTER")
        model_p = p_yes if side == "YES" else 1.0 - p_yes
        readout_sha = canonical_json_sha256({
            "version": PITCHER_WIN_READOUT_VERSION,
            "distribution_sha256": distribution.distribution_sha256,
            "entity_id": entity_id,
            "side": side,
            "model_p": model_p,
        })
        return {
            "game_id": model_input.get("game_id"),
            "market": "PITCHER_RECORD_WIN",
            "entity_id": model_input.get("entity_id"),
            "line": model_input.get("line"),
            "side": model_input.get("side"),
            "model_p": float(model_p),
            "push_p": 0.0,
            "model_input_hash": model_input_hash,
            "distribution_sha256": distribution.distribution_sha256,
            "readout_sha256": readout_sha,
            "readout_version": PITCHER_WIN_READOUT_VERSION,
            "engine_version": PITCHER_WIN_ENGINE_VERSION,
            "seed_policy": distribution.seed_policy,
            "mc_paths": distribution.simulations,
        }

    return engine
