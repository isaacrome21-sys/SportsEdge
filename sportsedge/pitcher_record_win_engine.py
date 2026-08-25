"""Win-credit-state candidate for MLB PITCHER_RECORD_WIN.

The prior candidate removed rolling pitcher win rate but still priced today's event
as team-win probability multiplied by a historical decision propensity. This v2
candidate models the credit mechanics explicitly from strictly-prior state:

* an actual first-five joint score distribution supplies today's probability of the
  selected team leading, tying, or trailing after five innings;
* the starter's prior-start outs distribution models five-inning qualification and
  how long he remains pitcher of record;
* the selected team's prior inning-by-inning score paths identify the minimum
  starter outs required to still own the lead the team never relinquished;
* each score-path requirement is crossed exhaustively with starter workload rather
  than using historical wins, losses, or decision rate as today's probability.

The result is still a candidate. It remains ineligible until historical PIT,
holdout, calibration, sportsbook settlement, forward evidence, and production
parity gates are genuinely satisfied.
"""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any, Mapping, Sequence

from .f5_distribution import F5Distribution, build_f5_distribution
from .live_slate import LiveGame
from .mlb_f5_features import MLBF5HistorySource
from .mlb_generic_features import MLBGenericHistorySource, _number, _outs_from_ip
from .source_lineage import canonical_json_sha256

PITCHER_RECORD_WIN_ENGINE_VERSION = "mlb_pitcher_record_win_credit_state_v2_candidate"
PITCHER_RECORD_WIN_READOUT_VERSION = "mlb_pitcher_record_win_readout_v2"
MIN_STARTS = 5
HISTORY_WINDOW_STARTS = 20


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


def _team_side(game: LiveGame, pitcher_id: int) -> str:
    if game.away_probable_pitcher_id == pitcher_id:
        return "AWAY"
    if game.home_probable_pitcher_id == pitcher_id:
        return "HOME"
    raise PitcherRecordWinError("PITCHER_RECORD_WIN_NON_PROBABLE_STARTER")


def _outs_history(value: Any) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PitcherRecordWinError("starter_outs_history must be a sequence")
    if len(value) < MIN_STARTS:
        raise PitcherRecordWinError(
            f"PITCHER_RECORD_WIN_HISTORY_INSUFFICIENT:{len(value)}<{MIN_STARTS}"
        )
    out: list[int] = []
    for index, raw in enumerate(value):
        if isinstance(raw, bool):
            raise PitcherRecordWinError(f"starter_outs_history[{index}] must be integer")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise PitcherRecordWinError(
                f"starter_outs_history[{index}] must be integer"
            ) from exc
        if not isfinite(numeric) or numeric < 0 or numeric != int(numeric):
            raise PitcherRecordWinError(
                f"starter_outs_history[{index}] must be nonnegative integer"
            )
        outs = int(numeric)
        if outs > 27:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_OUTS_OUT_OF_RANGE")
        out.append(outs)
    return tuple(out)


def _credit_paths(value: Any) -> dict[str, tuple[int | None, ...]]:
    if not isinstance(value, Mapping):
        raise PitcherRecordWinError("post_f5_credit_paths must be an object")
    out: dict[str, tuple[int | None, ...]] = {}
    for state in ("LEAD", "TIE", "TRAIL"):
        raw_values = value.get(state)
        if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
            raise PitcherRecordWinError(f"post_f5_credit_paths.{state} must be a sequence")
        normalized: list[int | None] = []
        for index, raw in enumerate(raw_values):
            if raw is None:
                normalized.append(None)
                continue
            if isinstance(raw, bool):
                raise PitcherRecordWinError(
                    f"post_f5_credit_paths.{state}[{index}] must be integer or null"
                )
            try:
                numeric = float(raw)
            except (TypeError, ValueError) as exc:
                raise PitcherRecordWinError(
                    f"post_f5_credit_paths.{state}[{index}] must be integer or null"
                ) from exc
            if not isfinite(numeric) or numeric < 15 or numeric != int(numeric):
                raise PitcherRecordWinError(
                    f"post_f5_credit_paths.{state}[{index}] must be integer >= 15 or null"
                )
            normalized.append(int(numeric))
        out[state] = tuple(normalized)
    return out


def _f5_state_probabilities(distribution: F5Distribution, team_side: str) -> dict[str, float]:
    selected = str(team_side or "").upper()
    if selected not in {"AWAY", "HOME"}:
        raise PitcherRecordWinError("PITCHER_RECORD_WIN team_side must be HOME or AWAY")
    probs = {"LEAD": 0.0, "TIE": 0.0, "TRAIL": 0.0}
    total = 0.0
    for key, raw in distribution.joint_score_pmf.items():
        try:
            away_text, home_text = str(key).split(",", 1)
            away = int(away_text)
            home = int(home_text)
            p = float(raw)
        except (TypeError, ValueError) as exc:
            raise PitcherRecordWinError("invalid F5 joint score state") from exc
        if p < 0 or not isfinite(p):
            raise PitcherRecordWinError("invalid F5 joint score probability")
        selected_runs = away if selected == "AWAY" else home
        opponent_runs = home if selected == "AWAY" else away
        state = "LEAD" if selected_runs > opponent_runs else "TRAIL" if selected_runs < opponent_runs else "TIE"
        probs[state] += p
        total += p
    if abs(total - 1.0) > 1e-12:
        raise PitcherRecordWinError("F5 probability mass does not conserve")
    return probs


def _survival_probability(outs_history: tuple[int, ...], required_outs: int | None) -> float:
    if required_outs is None:
        return 0.0
    return sum(outs >= int(required_outs) for outs in outs_history) / len(outs_history)


def _state_credit_probabilities(
    *, outs_history: tuple[int, ...], paths: Mapping[str, tuple[int | None, ...]],
    state_probabilities: Mapping[str, float],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for state in ("LEAD", "TIE", "TRAIL"):
        state_p = _probability(state_probabilities.get(state), f"f5_state_probability.{state}")
        values = paths[state]
        if not values:
            if state_p > 1e-12:
                raise PitcherRecordWinError(
                    f"PITCHER_RECORD_WIN_CREDIT_PATH_STATE_MISSING:{state}"
                )
            out[state] = 0.0
            continue
        out[state] = sum(
            _survival_probability(outs_history, required) for required in values
        ) / len(values)
    return out


def build_pitcher_record_win_features(
    source: MLBGenericHistorySource,
    *,
    game: LiveGame,
    pitcher_id: int,
    target_date: date,
    f5_source: MLBF5HistorySource | None = None,
) -> dict[str, Any]:
    """Build strictly-prior starter workload and official team score-path state."""
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
    outs_history: list[int] = []
    for row in starts:
        stat = row["stat"]
        outs = int(_outs_from_ip(stat.get("inningsPitched")))
        if not 0 <= outs <= 27:
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_OUTS_OUT_OF_RANGE")
        outs_history.append(outs)
        history.append({"date": row["date"].isoformat(), "outs": outs})

    qualification_rate = sum(outs >= 15 for outs in outs_history) / len(outs_history)
    f5 = f5_source or MLBF5HistorySource(
        opener=source.opener, retrieved_at=source.retrieved_at
    )
    matchup = f5.matchup_features(
        away_team_id=int(game.away_team_id),
        home_team_id=int(game.home_team_id),
        target_date=target_date,
    )
    selected_team_id = int(game.away_team_id if side == "AWAY" else game.home_team_id)
    credit = f5.win_credit_transition_features(
        team_id=selected_team_id, target_date=target_date
    )
    pitcher_identity = {
        "version": PITCHER_RECORD_WIN_ENGINE_VERSION,
        "pitcher_id": int(pitcher_id),
        "team_side": side,
        "target_date": target_date.isoformat(),
        "history": history,
        "retrieved_at": source.retrieved_at.isoformat(),
    }
    game_identity = {
        "game_pk": int(game.game_pk),
        "target_date": target_date.isoformat(),
        "away_team_id": int(game.away_team_id),
        "home_team_id": int(game.home_team_id),
        "f5_feature_source_hash": matchup["feature_source_hash"],
        "retrieved_at": f5.retrieved_at.isoformat(),
    }
    credit_identity = {
        "team_id": selected_team_id,
        "team_side": side,
        "credit_path_source_hash": credit["feature_source_hash"],
    }
    return {
        "feature_version": PITCHER_RECORD_WIN_ENGINE_VERSION,
        "feature_source_hash": canonical_json_sha256({
            "game": game_identity,
            "pitcher": pitcher_identity,
            "credit": credit_identity,
        }),
        "game_source_hash": canonical_json_sha256(game_identity),
        "pitcher_source_hash": canonical_json_sha256(pitcher_identity),
        "credit_path_source_hash": str(credit["feature_source_hash"]),
        "team_side": side,
        "team_id": selected_team_id,
        "qualification_rate": float(qualification_rate),
        "starter_outs_history": outs_history,
        "history": history,
        "f5_features": dict(matchup["features"]),
        "f5_feature_source_hash": str(matchup["feature_source_hash"]),
        "post_f5_credit_paths": {
            state: list(values) for state, values in credit["paths"].items()
        },
        "credit_path_state_counts": dict(credit["state_counts"]),
    }


def build_shared_pitcher_record_win_engine_session():
    """Return an analytic score-path/read-out engine for pitcher win credit."""
    distribution_cache: dict[str, F5Distribution] = {}

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

        outs_history = _outs_history(features.get("starter_outs_history"))
        paths = _credit_paths(features.get("post_f5_credit_paths"))
        f5_features = features.get("f5_features")
        if not isinstance(f5_features, Mapping):
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_F5_FEATURES_MISSING")
        pitcher_source_hash = str(features.get("pitcher_source_hash") or "").strip()
        game_source_hash = str(features.get("game_source_hash") or "").strip()
        f5_source_hash = str(features.get("f5_feature_source_hash") or "").strip()
        credit_source_hash = str(features.get("credit_path_source_hash") or "").strip()
        if any(len(value) != 64 for value in (
            pitcher_source_hash, game_source_hash, f5_source_hash, credit_source_hash
        )):
            raise PitcherRecordWinError("PITCHER_RECORD_WIN_SOURCE_HASH_MISSING")

        f5_identity = canonical_json_sha256({
            "f5_feature_source_hash": f5_source_hash,
            "f5_features": dict(f5_features),
        })
        distribution = distribution_cache.get(f5_identity)
        if distribution is None:
            distribution = build_f5_distribution(f5_features)
            distribution_cache[f5_identity] = distribution

        state_probabilities = _f5_state_probabilities(distribution, team_side)
        credit_by_state = _state_credit_probabilities(
            outs_history=outs_history,
            paths=paths,
            state_probabilities=state_probabilities,
        )
        p_yes = sum(
            state_probabilities[state] * credit_by_state[state]
            for state in ("LEAD", "TIE", "TRAIL")
        )
        p_yes = _probability(p_yes, "pitcher_record_win_probability")
        model_p = p_yes if side == "YES" else 1.0 - p_yes
        qualification_rate = sum(outs >= 15 for outs in outs_history) / len(outs_history)
        latent_identity = {
            "engine": PITCHER_RECORD_WIN_ENGINE_VERSION,
            "game_id": game_id,
            "pitcher_id": entity_id,
            "team_side": team_side,
            "pitcher_source_hash": pitcher_source_hash,
            "game_source_hash": game_source_hash,
            "f5_feature_source_hash": f5_source_hash,
            "credit_path_source_hash": credit_source_hash,
            "f5_distribution_sha256": distribution.distribution_sha256,
            "starter_outs_history": list(outs_history),
            "post_f5_credit_paths": {
                state: list(paths[state]) for state in ("LEAD", "TIE", "TRAIL")
            },
        }
        model_input_hash = canonical_json_sha256(latent_identity)
        distribution_sha = canonical_json_sha256({
            **latent_identity,
            "f5_state_probabilities": state_probabilities,
            "credit_probability_by_state": credit_by_state,
            "qualification_rate": qualification_rate,
            "p_yes": p_yes,
        })
        readout_sha = canonical_json_sha256({
            "version": PITCHER_RECORD_WIN_READOUT_VERSION,
            "distribution_sha256": distribution_sha,
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
            "qualification_rate": float(qualification_rate),
            "f5_state_probabilities": dict(state_probabilities),
            "credit_probability_by_state": dict(credit_by_state),
            "model_input_hash": model_input_hash,
            "distribution_sha256": distribution_sha,
            "readout_sha256": readout_sha,
            "readout_version": PITCHER_RECORD_WIN_READOUT_VERSION,
            "engine_version": PITCHER_RECORD_WIN_ENGINE_VERSION,
            "seed_policy": "analytic_f5_score_path_x_starter_outs_cross_product",
            "mc_paths": 0,
        }

    return engine
