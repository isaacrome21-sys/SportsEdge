"""Game-state-linked candidate for MLB PITCHER_RECORD_WIN.

The legacy path used the starter's rolling historical win rate as today's event
probability. That bakes prior opponent/team context into the prediction and ignores
today's modeled game state. This candidate separates the two pieces:

* one price-independent V7 final-score distribution gives today's team win
  probability;
* strictly-prior starter game logs estimate the probability that the starter is the
  pitcher of record in a start (win or loss);
* P(pitcher records win) = P(team wins today) * P(starter is pitcher of record).

The game distribution is shared across both probable starters and does not include
pitcher identity, sportsbook line, side, or odds. Pitcher identity and YES/NO are
read-out semantics. The candidate remains unpromoted until PIT/holdout/calibration/
forward/parity evidence is earned.
"""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any, Callable, Mapping

from .game_distribution_readout import read_game_probability
from .live_slate import LiveGame
from .mlb_generic_features import MLBGenericHistorySource, _number, _outs_from_ip
from .shared_game_engine import score_distribution_sha256
from .source_lineage import canonical_json_sha256
from .v7_distribution import (
    DEFAULT_EXTRA_HALF_INNING_MEAN,
    DEFAULT_FIRST_INNING_DISPERSION_R,
    DEFAULT_FIRST_INNING_SHARE,
    V7_DISTRIBUTION_VERSION,
    GameDistribution,
    simulate_game_distribution,
)

PITCHER_RECORD_WIN_ENGINE_VERSION = "mlb_pitcher_record_win_team_state_v1_candidate"
PITCHER_RECORD_WIN_READOUT_VERSION = "mlb_pitcher_record_win_readout_v1"
MIN_STARTS = 5
HISTORY_WINDOW_STARTS = 20
DEFAULT_SIMULATIONS = 50000


class PitcherRecordWinError(ValueError):
    pass


def _probability(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise PitcherRecordWinError(f"{field} must be probability")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherRecordWinError(f"{field} must be probability") from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise PitcherRecordWinError(f"{field} must be in [0,1]")
    return out


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


def build_pitcher_record_win_features(
    source: MLBGenericHistorySource,
    *,
    game: LiveGame,
    pitcher_id: int,
    target_date: date,
) -> dict[str, Any]:
    """Build strictly-prior starter decision propensity plus today's team state."""
    side = _team_side(game, int(pitcher_id))
    rows = source.player_rows(
        player_id=int(pitcher_id), group="pitching", target_date=target_date
    )
    starts = [
        row for row in rows
        if _number(row["stat"].get("gamesStarted", 0), "gamesStarted") >= 1
    ][-HISTORY_WINDOW_STARTS:]
    if len(starts) < MIN_STARTS:
        raise PitcherRecordWinError(
            f"PITCHER_RECORD_WIN_HISTORY_INSUFFICIENT:{len(starts)}<{MIN_STARTS}"
        )

    history: list[dict[str, Any]] = []
    decisions = 0
    qualified = 0
    for row in starts:
        stat = row["stat"]
        wins = int(_number(stat.get("wins", 0), "wins"))
        losses = int(_number(stat.get("losses", 0), "losses"))
        if wins not in {0, 1} or losses not in {0, 1} or wins + losses > 1:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_DECISION_ACCOUNTING_INVALID")
        outs = int(_outs_from_ip(stat.get("inningsPitched")))
        if not 0 <= outs <= 27:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_OUTS_OUT_OF_RANGE")
        decision = wins + losses
        decisions += decision
        qualified += int(outs >= 15)
        history.append({
            "date": row["date"].isoformat(),
            "wins": wins,
            "losses": losses,
            "decision": decision,
            "outs": outs,
        })

    decision_rate = decisions / len(history)
    qualification_rate = qualified / len(history)
    away_mean, home_mean, _ = source.team_means(
        away_team_id=int(game.away_team_id),
        home_team_id=int(game.home_team_id),
        target_date=target_date,
    )
    game_identity = {
        "version": V7_DISTRIBUTION_VERSION,
        "game_pk": int(game.game_pk),
        "target_date": target_date.isoformat(),
        "away_team_id": int(game.away_team_id),
        "home_team_id": int(game.home_team_id),
        "away_mean_runs": float(away_mean),
        "home_mean_runs": float(home_mean),
        "retrieved_at": source.retrieved_at.isoformat(),
    }
    pitcher_identity = {
        "version": PITCHER_RECORD_WIN_ENGINE_VERSION,
        "pitcher_id": int(pitcher_id),
        "team_side": side,
        "target_date": target_date.isoformat(),
        "history": history,
        "retrieved_at": source.retrieved_at.isoformat(),
    }
    return {
        "feature_version": PITCHER_RECORD_WIN_ENGINE_VERSION,
        "feature_source_hash": canonical_json_sha256({
            "game": game_identity, "pitcher": pitcher_identity
        }),
        "game_source_hash": canonical_json_sha256(game_identity),
        "pitcher_source_hash": canonical_json_sha256(pitcher_identity),
        "team_side": side,
        "away_mean_runs": float(away_mean),
        "home_mean_runs": float(home_mean),
        "decision_rate": float(decision_rate),
        "qualification_rate": float(qualification_rate),
        "history": history,
    }


def build_shared_pitcher_record_win_engine_session(
    *,
    simulator: Callable[..., GameDistribution] = simulate_game_distribution,
):
    """Return a per-card engine with a game-state distribution shared by starters."""
    game_cache: dict[str, tuple[GameDistribution, str]] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        if str(model_input.get("market") or "").upper() != "PITCHER_RECORD_WIN":
            raise PitcherRecordWinError("pitcher-record-win engine requires PITCHER_RECORD_WIN")
        game_id = str(model_input.get("game_id") or "").strip()
        entity_id = str(model_input.get("entity_id") or "").strip()
        side = str(model_input.get("side") or "").upper()
        team_side = str(model_input.get("team_side") or "").upper()
        features = model_input.get("features")
        if not game_id or not entity_id or not isinstance(features, Mapping):
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_MODEL_IDENTITY_INCOMPLETE")
        if side not in {"YES", "NO"}:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN side must be YES or NO")
        if team_side not in {"HOME", "AWAY"}:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN team_side must be HOME or AWAY")

        away_mean = _positive(model_input.get("away_mean_runs"), "away_mean_runs")
        home_mean = _positive(model_input.get("home_mean_runs"), "home_mean_runs")
        decision_rate = _probability(features.get("decision_rate"), "decision_rate")
        pitcher_source_hash = str(features.get("pitcher_source_hash") or "").strip()
        game_source_hash = str(features.get("game_source_hash") or "").strip()
        if len(pitcher_source_hash) != 64 or len(game_source_hash) != 64:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_SOURCE_HASH_MISSING")
        simulations = int(model_input.get("simulations", DEFAULT_SIMULATIONS))
        if simulations < 1000:
            raise PitcherRecordWinError("simulations must be >= 1000")

        stochastic_identity = {
            "engine": V7_DISTRIBUTION_VERSION,
            "game_id": game_id,
            "away_mean_runs": away_mean,
            "home_mean_runs": home_mean,
            "game_source_hash": game_source_hash,
        }
        game_build_hash = canonical_json_sha256(stochastic_identity)
        game_model_hash = canonical_json_sha256({
            **stochastic_identity, "simulations": simulations
        })
        cached = game_cache.get(game_model_hash)
        if cached is None:
            distribution = simulator(
                away_mean_runs=away_mean,
                home_mean_runs=home_mean,
                total_line=0.0,
                simulations=simulations,
                build_hash=game_build_hash,
                first_inning_share=DEFAULT_FIRST_INNING_SHARE,
                first_inning_dispersion_r=DEFAULT_FIRST_INNING_DISPERSION_R,
                extra_half_inning_mean=DEFAULT_EXTRA_HALF_INNING_MEAN,
            )
            distribution_sha = score_distribution_sha256(distribution)
            game_cache[game_model_hash] = (distribution, distribution_sha)
        else:
            distribution, distribution_sha = cached

        readout = read_game_probability(
            {
                "joint_score_pmf": distribution.joint_score_pmf,
                "result_sha256": distribution_sha,
            },
            market="MONEYLINE",
            side=team_side,
        )
        team_win_probability = float(readout.probability)
        p_yes = team_win_probability * decision_rate
        model_p = p_yes if side == "YES" else 1.0 - p_yes
        model_input_hash = canonical_json_sha256({
            "engine": PITCHER_RECORD_WIN_ENGINE_VERSION,
            "game_model_hash": game_model_hash,
            "pitcher_id": entity_id,
            "team_side": team_side,
            "pitcher_source_hash": pitcher_source_hash,
            "decision_rate": decision_rate,
        })
        readout_sha = canonical_json_sha256({
            "version": PITCHER_RECORD_WIN_READOUT_VERSION,
            "distribution_sha256": distribution_sha,
            "pitcher_id": entity_id,
            "team_side": team_side,
            "decision_rate": decision_rate,
            "team_win_probability": team_win_probability,
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
            "team_win_probability": team_win_probability,
            "decision_rate": decision_rate,
            "model_input_hash": model_input_hash,
            "distribution_sha256": distribution_sha,
            "readout_sha256": readout_sha,
            "readout_version": PITCHER_RECORD_WIN_READOUT_VERSION,
            "engine_version": PITCHER_RECORD_WIN_ENGINE_VERSION,
            "seed_policy": distribution.seed_policy,
            "mc_paths": distribution.simulations,
        }

    return engine
