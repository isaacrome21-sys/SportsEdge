"""Game-state candidate for MLB PITCHER_RECORD_WIN.

This hardens the first game-state candidate by removing pitcher wins/losses from
prediction inputs entirely. One price-independent simulation now binds both probable
starters, their strictly-prior workload/run-prevention histories, and today's team
scoring state. Each path samples starter exit workload, enforces the five-inning
starter qualification rule, records whether the starter's team is leading at exit,
and then explicitly models whether the bullpen later relinquishes that lead.

Pitcher identity and YES/NO remain deterministic read-out semantics. Official-scorer
settlement and every promotion gate remain separate and fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import exp, isfinite
from typing import Any, Mapping, Sequence

from .identity_rng import candidate_rng
from .live_slate import LiveGame
from .mlb_generic_features import MLBGenericHistorySource, _number, _outs_from_ip
from .source_lineage import canonical_json_sha256

PITCHER_RECORD_WIN_ENGINE_VERSION = "mlb_pitcher_record_win_exit_bullpen_v2_candidate"
PITCHER_RECORD_WIN_READOUT_VERSION = "mlb_pitcher_record_win_readout_v2"
MIN_STARTS = 8
HISTORY_WINDOW_STARTS = 20
DEFAULT_SIMULATIONS = 50000
STARTER_WIN_MIN_OUTS = 15


class PitcherRecordWinError(ValueError):
    pass


@dataclass(frozen=True)
class PitcherRecordWinDistribution:
    simulations: int
    away_starter_id: str
    home_starter_id: str
    away_starter_win_probability: float
    home_starter_win_probability: float
    no_starting_pitcher_win_probability: float
    distribution_sha256: str
    seed_policy: str = "identity_sha256_256bit"
    engine_version: str = PITCHER_RECORD_WIN_ENGINE_VERSION


def _positive(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise PitcherRecordWinError(f"{field} must be finite positive")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherRecordWinError(f"{field} must be finite positive") from exc
    if not isfinite(out) or out <= 0:
        raise PitcherRecordWinError(f"{field} must be finite positive")
    return out


def _team_side(game: LiveGame, pitcher_id: int) -> str:
    if game.away_probable_pitcher_id == pitcher_id:
        return "AWAY"
    if game.home_probable_pitcher_id == pitcher_id:
        return "HOME"
    raise PitcherRecordWinError("PITCHER_RECORD_WIN_NON_PROBABLE_STARTER")


def _starter_history(
    source: MLBGenericHistorySource,
    *,
    pitcher_id: int,
    target_date: date,
) -> list[dict[str, Any]]:
    rows = source.player_rows(
        player_id=int(pitcher_id), group="pitching", target_date=target_date
    )
    starts: list[dict[str, Any]] = []
    for row in rows:
        stat = row.get("stat")
        if not isinstance(stat, Mapping):
            continue
        if _number(stat.get("gamesStarted", 0), "gamesStarted") < 1:
            continue
        try:
            outs_float = float(_outs_from_ip(stat.get("inningsPitched")))
            earned_runs = float(_number(stat.get("earnedRuns", 0), "earnedRuns"))
        except Exception:
            continue
        outs = int(outs_float)
        if outs_float != outs or not 0 <= outs <= 27 or earned_runs < 0:
            continue
        starts.append({
            "date": row["date"].isoformat(),
            "outs": outs,
            "earned_runs": earned_runs,
        })
    starts = starts[-HISTORY_WINDOW_STARTS:]
    if len(starts) < MIN_STARTS:
        raise PitcherRecordWinError(
            f"PITCHER_RECORD_WIN_HISTORY_INSUFFICIENT:{pitcher_id}:{len(starts)}<{MIN_STARTS}"
        )
    return starts


def build_pitcher_record_win_features(
    source: MLBGenericHistorySource,
    *,
    game: LiveGame,
    pitcher_id: int,
    target_date: date,
) -> dict[str, Any]:
    """Build one common game-state feature payload for both probable starters."""
    side = _team_side(game, int(pitcher_id))
    if game.away_probable_pitcher_id is None or game.home_probable_pitcher_id is None:
        raise PitcherRecordWinError("PITCHER_RECORD_WIN_BOTH_PROBABLE_STARTERS_REQUIRED")
    away_starter_id = int(game.away_probable_pitcher_id)
    home_starter_id = int(game.home_probable_pitcher_id)
    away_history = _starter_history(
        source, pitcher_id=away_starter_id, target_date=target_date
    )
    home_history = _starter_history(
        source, pitcher_id=home_starter_id, target_date=target_date
    )
    away_mean, home_mean, _ = source.team_means(
        away_team_id=int(game.away_team_id),
        home_team_id=int(game.home_team_id),
        target_date=target_date,
    )
    features = {
        "away_team_id": int(game.away_team_id),
        "home_team_id": int(game.home_team_id),
        "away_starter_id": away_starter_id,
        "home_starter_id": home_starter_id,
        "away_team_mean_runs": float(away_mean),
        "home_team_mean_runs": float(home_mean),
        "away_starter_history": away_history,
        "home_starter_history": home_history,
    }
    common_identity = {
        "version": PITCHER_RECORD_WIN_ENGINE_VERSION,
        "game_pk": int(game.game_pk),
        "target_date": target_date.isoformat(),
        "retrieved_at": source.retrieved_at.isoformat(),
        "features": features,
    }
    common_hash = canonical_json_sha256(common_identity)
    return {
        "feature_version": PITCHER_RECORD_WIN_ENGINE_VERSION,
        "feature_source_hash": common_hash,
        "game_source_hash": common_hash,
        "pitcher_source_hash": common_hash,
        "team_side": side,
        "away_mean_runs": float(away_mean),
        "home_mean_runs": float(home_mean),
        "features": features,
        # Compatibility keys are retained but are no longer predictors.
        "decision_rate": None,
        "qualification_rate": None,
        "history": away_history if side == "AWAY" else home_history,
    }


def starter_win_credit(
    *,
    outs_recorded: int,
    leading_at_exit: bool,
    lead_relinquished: bool,
) -> bool:
    return bool(
        int(outs_recorded) >= STARTER_WIN_MIN_OUTS
        and leading_at_exit
        and not lead_relinquished
    )


def _clean_history(value: Any, label: str) -> tuple[dict[str, float], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PitcherRecordWinError(f"{label} must be a sequence")
    out: list[dict[str, float]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise PitcherRecordWinError(f"{label} row malformed")
        try:
            outs_value = float(row.get("outs"))
            earned_runs = float(row.get("earned_runs"))
        except (TypeError, ValueError) as exc:
            raise PitcherRecordWinError(f"{label} row invalid") from exc
        if (
            not isfinite(outs_value)
            or outs_value != int(outs_value)
            or not 0 <= int(outs_value) <= 27
            or not isfinite(earned_runs)
            or earned_runs < 0
        ):
            raise PitcherRecordWinError(f"{label} row out of range")
        out.append({"outs": float(int(outs_value)), "earned_runs": earned_runs})
    if len(out) < MIN_STARTS:
        raise PitcherRecordWinError(f"{label} insufficient history")
    return tuple(out[-HISTORY_WINDOW_STARTS:])


def _starter_ra9(history: Sequence[Mapping[str, float]]) -> float:
    total_outs = sum(float(row["outs"]) for row in history)
    total_er = sum(float(row["earned_runs"]) for row in history)
    if total_outs <= 0:
        raise PitcherRecordWinError("starter history has zero outs")
    return max(0.0, total_er * 27.0 / total_outs)


def _poisson(rng, lam: float) -> int:
    if lam <= 0:
        return 0
    if not isfinite(lam) or lam > 20:
        raise PitcherRecordWinError("half-inning run rate out of range")
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


def simulate_pitcher_record_win_distribution(
    features: Mapping[str, Any],
    *,
    simulations: int = DEFAULT_SIMULATIONS,
    build_hash: str,
) -> PitcherRecordWinDistribution:
    if isinstance(simulations, bool) or int(simulations) < 1000:
        raise PitcherRecordWinError("simulations must be integer >= 1000")
    simulations = int(simulations)
    try:
        away_starter_id = str(int(features.get("away_starter_id")))
        home_starter_id = str(int(features.get("home_starter_id")))
    except (TypeError, ValueError) as exc:
        raise PitcherRecordWinError("probable starter identity missing") from exc
    away_mean = _positive(features.get("away_team_mean_runs"), "away_team_mean_runs")
    home_mean = _positive(features.get("home_team_mean_runs"), "home_team_mean_runs")
    away_history = _clean_history(features.get("away_starter_history"), "away_starter_history")
    home_history = _clean_history(features.get("home_starter_history"), "home_starter_history")

    # Starter-facing rates blend today's opposing offense with strictly-prior
    # run prevention. Once the starter exits, the state transitions to the
    # opponent's current team scoring baseline as an explicit bullpen phase.
    away_starter_allowed = 0.5 * home_mean + 0.5 * _starter_ra9(away_history)
    home_starter_allowed = 0.5 * away_mean + 0.5 * _starter_ra9(home_history)
    rng = candidate_rng(build_hash)
    wins = {"AWAY": 0, "HOME": 0}

    for _ in range(simulations):
        sampled_outs = {
            "AWAY": int(away_history[rng.randrange(len(away_history))]["outs"]),
            "HOME": int(home_history[rng.randrange(len(home_history))]["outs"]),
        }
        state = {
            "AWAY": {"exit_recorded": False, "leading_at_exit": False, "lead_relinquished": False},
            "HOME": {"exit_recorded": False, "leading_at_exit": False, "lead_relinquished": False},
        }
        away_runs = 0
        home_runs = 0

        def record_exit(side: str) -> None:
            if state[side]["exit_recorded"]:
                return
            state[side]["exit_recorded"] = True
            state[side]["leading_at_exit"] = _team_leads(side, away_runs, home_runs)

        def check_relinquished() -> None:
            for side in ("AWAY", "HOME"):
                row = state[side]
                if row["exit_recorded"] and row["leading_at_exit"] and not row["lead_relinquished"]:
                    if not _team_leads(side, away_runs, home_runs):
                        row["lead_relinquished"] = True

        def add_runs(offense: str, runs: int) -> None:
            nonlocal away_runs, home_runs
            if offense == "AWAY":
                away_runs += runs
            else:
                home_runs += runs
            check_relinquished()

        def play_half(*, offense: str, fielding: str, inning: int) -> None:
            outs = sampled_outs[fielding]
            prior_outs = (inning - 1) * 3
            if not state[fielding]["exit_recorded"] and outs <= prior_outs:
                record_exit(fielding)

            starter_fraction = _starter_fraction(outs, inning)
            bullpen_fraction = 1.0 - starter_fraction
            starter_rate = home_starter_allowed if fielding == "HOME" else away_starter_allowed
            bullpen_rate = away_mean if offense == "AWAY" else home_mean

            if starter_fraction > 0:
                add_runs(
                    offense,
                    _poisson(rng, (starter_rate / 9.0) * starter_fraction),
                )

            if not state[fielding]["exit_recorded"] and prior_outs < outs <= prior_outs + 3:
                record_exit(fielding)

            if bullpen_fraction > 0:
                add_runs(
                    offense,
                    _poisson(rng, (bullpen_rate / 9.0) * bullpen_fraction),
                )

        for inning in range(1, 10):
            play_half(offense="AWAY", fielding="HOME", inning=inning)
            if inning == 9 and home_runs > away_runs:
                break
            play_half(offense="HOME", fielding="AWAY", inning=inning)

        # If a sampled complete-game workload was actually reached, bind exit to
        # the terminal regulation state. A road starter cannot record bottom-nine
        # outs when the home team already leads after the top of the ninth.
        reached_outs = {
            "HOME": 27,
            "AWAY": 27 if not (home_runs > away_runs and not state["AWAY"]["exit_recorded"]) else 24,
        }
        for side in ("AWAY", "HOME"):
            if not state[side]["exit_recorded"] and sampled_outs[side] <= reached_outs[side]:
                record_exit(side)

        credited: list[str] = []
        for side in ("AWAY", "HOME"):
            row = state[side]
            if row["exit_recorded"] and starter_win_credit(
                outs_recorded=sampled_outs[side],
                leading_at_exit=bool(row["leading_at_exit"]),
                lead_relinquished=bool(row["lead_relinquished"]),
            ):
                credited.append(side)
        if len(credited) > 1:
            raise PitcherRecordWinError("both starters cannot receive a win")
        if credited:
            wins[credited[0]] += 1

    away_p = wins["AWAY"] / simulations
    home_p = wins["HOME"] / simulations
    residual = 1.0 - away_p - home_p
    if away_p < 0 or home_p < 0 or residual < -1e-12:
        raise PitcherRecordWinError("pitcher-record-win probability mass invalid")
    residual = max(0.0, residual)
    distribution_sha = canonical_json_sha256({
        "version": PITCHER_RECORD_WIN_ENGINE_VERSION,
        "simulations": simulations,
        "away_starter_id": away_starter_id,
        "home_starter_id": home_starter_id,
        "away_starter_win_probability": away_p,
        "home_starter_win_probability": home_p,
        "no_starting_pitcher_win_probability": residual,
    })
    return PitcherRecordWinDistribution(
        simulations=simulations,
        away_starter_id=away_starter_id,
        home_starter_id=home_starter_id,
        away_starter_win_probability=away_p,
        home_starter_win_probability=home_p,
        no_starting_pitcher_win_probability=residual,
        distribution_sha256=distribution_sha,
    )


def build_shared_pitcher_record_win_engine_session(*, simulator=None):
    """Return a per-card session with one latent distribution shared by read-outs.

    ``simulator`` is retained only as a compatibility keyword for callers/tests of
    the prior v1 candidate. It is intentionally ignored: the v2 candidate must use
    the explicit starter-exit/bullpen state simulator above rather than a final-score
    shortcut.
    """
    cache: dict[str, PitcherRecordWinDistribution] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        if str(model_input.get("market") or "").upper() != "PITCHER_RECORD_WIN":
            raise PitcherRecordWinError("pitcher-record-win engine requires PITCHER_RECORD_WIN")
        game_id = str(model_input.get("game_id") or "").strip()
        entity_id = str(model_input.get("entity_id") or "").strip()
        side = str(model_input.get("side") or "").upper()
        features = model_input.get("features")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not game_id or not entity_id or not isinstance(features, Mapping):
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_MODEL_IDENTITY_INCOMPLETE")
        if side not in {"YES", "NO"}:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN side must be YES or NO")
        if len(feature_source_hash) != 64:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_SOURCE_HASH_MISSING")
        simulations = int(model_input.get("simulations", DEFAULT_SIMULATIONS))
        if simulations < 1000:
            raise PitcherRecordWinError("simulations must be >= 1000")

        stochastic_identity = {
            "engine": PITCHER_RECORD_WIN_ENGINE_VERSION,
            "game_id": game_id,
            "feature_source_hash": feature_source_hash,
            "features": dict(features),
        }
        build_hash = canonical_json_sha256(stochastic_identity)
        model_input_hash = canonical_json_sha256({
            **stochastic_identity,
            "simulations": simulations,
        })
        distribution = cache.get(model_input_hash)
        if distribution is None:
            distribution = simulate_pitcher_record_win_distribution(
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
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_NON_PROBABLE_STARTER")
        model_p = p_yes if side == "YES" else 1.0 - p_yes
        readout_sha = canonical_json_sha256({
            "version": PITCHER_RECORD_WIN_READOUT_VERSION,
            "distribution_sha256": distribution.distribution_sha256,
            "pitcher_id": entity_id,
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
            "readout_version": PITCHER_RECORD_WIN_READOUT_VERSION,
            "engine_version": PITCHER_RECORD_WIN_ENGINE_VERSION,
            "seed_policy": distribution.seed_policy,
            "mc_paths": distribution.simulations,
        }

    return engine
