from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from ..identity_rng import candidate_rng, validate_build_hash
from ..source_lineage import canonical_json_sha256
from .mlb_pitcher_contract import normalize_starter_path

DFS_MLB_STARTER_PATH_VERSION = "dfs_mlb_starter_paths_v1_candidate"
MIN_PATHS = 1000


class MlbStarterPathError(ValueError):
    pass


@dataclass(frozen=True)
class _ScoreState:
    away_runs: int
    home_runs: int
    probability: float


@dataclass(frozen=True)
class _SupportState:
    away_history_index: int
    home_history_index: int
    score: _ScoreState
    weight: float


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise MlbStarterPathError(f"{field} must be integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise MlbStarterPathError(f"{field} must be integer") from exc
    if not isfinite(numeric) or numeric < 0 or numeric != int(numeric):
        raise MlbStarterPathError(f"{field} must be nonnegative integer")
    return int(numeric)


def _binary(value: Any, field: str) -> int:
    out = _integer(value, field)
    if out not in (0, 1):
        raise MlbStarterPathError(f"{field} must be 0 or 1")
    return out


def _history(features: Mapping[str, Any], side: str) -> tuple[dict[str, float], ...]:
    raw = features.get("starter_history")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 5:
        raise MlbStarterPathError(f"DFS_MLB_{side}_STARTER_HISTORY_INSUFFICIENT")
    rows: list[dict[str, float]] = []
    required = (
        "outs",
        "strikeouts",
        "earned_runs",
        "runs_allowed",
        "hits_allowed",
        "walks_allowed",
        "hbp_allowed",
        "starter_exit_batters_faced",
        "starter_exit_pitch_count",
        "complete_game_probability",
        "cg_shutout_probability",
        "no_hitter_probability",
    )
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise MlbStarterPathError(f"DFS_MLB_{side}_STARTER_ROW_INVALID:{index}")
        row: dict[str, float] = {}
        for key in required:
            if key not in item:
                raise MlbStarterPathError(
                    f"DFS_MLB_{side}_STARTER_FIELD_MISSING:{index}:{key}"
                )
            try:
                value = float(item[key])
            except (TypeError, ValueError) as exc:
                raise MlbStarterPathError(
                    f"DFS_MLB_{side}_STARTER_FIELD_INVALID:{index}:{key}"
                ) from exc
            if not isfinite(value) or value < 0:
                raise MlbStarterPathError(
                    f"DFS_MLB_{side}_STARTER_FIELD_INVALID:{index}:{key}"
                )
            row[key] = value
        for key in ("complete_game_probability", "cg_shutout_probability", "no_hitter_probability"):
            if row[key] not in (0.0, 1.0):
                raise MlbStarterPathError(
                    f"DFS_MLB_{side}_STARTER_BINARY_INVALID:{index}:{key}"
                )
        if row["earned_runs"] > row["runs_allowed"]:
            raise MlbStarterPathError(f"DFS_MLB_{side}_ER_EXCEEDS_RUNS:{index}")
        # Reuse the downstream contract here with neutral lead state so producer and
        # scorer cannot silently disagree about BF/pitch/event support.
        normalize_starter_path(
            {
                **row,
                "starter_scoped_events": 1.0,
                "lead_at_exit": 0.0,
                "lead_preserved_to_final": 0.0,
            }
        )
        rows.append(row)
    return tuple(rows)


def _credit_rows(features: Mapping[str, Any], side: str) -> tuple[dict[str, Any], ...]:
    raw = features.get("credit_history")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) < 10:
        raise MlbStarterPathError(f"DFS_MLB_{side}_CREDIT_HISTORY_INSUFFICIENT")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise MlbStarterPathError(f"DFS_MLB_{side}_CREDIT_ROW_INVALID:{index}")
        team_won = bool(item.get("team_won"))
        required = item.get("win_credit_required_outs")
        if required is not None:
            required = _integer(required, f"{side}.credit[{index}].required_outs")
            if required < 15:
                raise MlbStarterPathError(
                    f"DFS_MLB_{side}_CREDIT_OUTS_BELOW_QUALIFICATION:{index}"
                )
        rows.append(
            {
                "team_won": team_won,
                "win_credit_required_outs": required,
            }
        )
    return tuple(rows)


def _score_states(joint_score_pmf: Mapping[str, Any]) -> tuple[_ScoreState, ...]:
    if not isinstance(joint_score_pmf, Mapping) or not joint_score_pmf:
        raise MlbStarterPathError("DFS_MLB_GAME_SCORE_PMF_REQUIRED")
    states: list[_ScoreState] = []
    total = 0.0
    for key, raw_probability in joint_score_pmf.items():
        try:
            away_text, home_text = str(key).split(",", 1)
            away = _integer(away_text, "away_runs")
            home = _integer(home_text, "home_runs")
            probability = float(raw_probability)
        except (TypeError, ValueError) as exc:
            raise MlbStarterPathError("DFS_MLB_GAME_SCORE_PMF_INVALID") from exc
        if not isfinite(probability) or probability < 0:
            raise MlbStarterPathError("DFS_MLB_GAME_SCORE_PMF_INVALID")
        if probability == 0:
            continue
        if away == home:
            raise MlbStarterPathError("DFS_MLB_GAME_SCORE_PMF_FINAL_TIE")
        states.append(_ScoreState(away, home, probability))
        total += probability
    if not states or abs(total - 1.0) > 1e-9:
        raise MlbStarterPathError(f"DFS_MLB_GAME_SCORE_PMF_MASS:{total}")
    return tuple(states)


def _is_complete_game(row: Mapping[str, float]) -> bool:
    return row["complete_game_probability"] == 1.0


def _compatible(
    away_row: Mapping[str, float],
    home_row: Mapping[str, float],
    score: _ScoreState,
) -> bool:
    # Away starter allows home runs; home starter allows away runs. Starter total
    # runs cannot exceed the opponent final. A complete-game starter owns every run.
    away_runs_allowed = int(away_row["runs_allowed"])
    home_runs_allowed = int(home_row["runs_allowed"])
    if away_runs_allowed > score.home_runs or home_runs_allowed > score.away_runs:
        return False
    if _is_complete_game(away_row) and away_runs_allowed != score.home_runs:
        return False
    if _is_complete_game(home_row) and home_runs_allowed != score.away_runs:
        return False
    return True


def _support(
    away_history: Sequence[Mapping[str, float]],
    home_history: Sequence[Mapping[str, float]],
    scores: Sequence[_ScoreState],
) -> tuple[_SupportState, ...]:
    base = 1.0 / (len(away_history) * len(home_history))
    states: list[_SupportState] = []
    for away_index, away_row in enumerate(away_history):
        for home_index, home_row in enumerate(home_history):
            for score in scores:
                if _compatible(away_row, home_row, score):
                    states.append(
                        _SupportState(
                            away_history_index=away_index,
                            home_history_index=home_index,
                            score=score,
                            weight=base * score.probability,
                        )
                    )
    if not states:
        raise MlbStarterPathError("DFS_MLB_STARTER_SCORE_SUPPORT_EMPTY")
    return tuple(states)


def _draw_weighted(rng, rows: Sequence[Any], weights: Sequence[float]):
    cumulative: list[float] = []
    total = 0.0
    for weight in weights:
        if not isfinite(weight) or weight < 0:
            raise MlbStarterPathError("DFS_MLB_PATH_WEIGHT_INVALID")
        total += weight
        cumulative.append(total)
    if total <= 0:
        raise MlbStarterPathError("DFS_MLB_PATH_WEIGHT_EMPTY")
    needle = rng.random() * total
    index = bisect_left(cumulative, needle)
    if index >= len(rows):
        index = len(rows) - 1
    return rows[index]


def _credit_state(
    rng,
    *,
    starter_outs: int,
    team_won: bool,
    credit_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, int, int | None]:
    if not team_won:
        return 0, 0, None
    wins = [row for row in credit_rows if bool(row["team_won"])]
    if not wins:
        raise MlbStarterPathError("DFS_MLB_WIN_CREDIT_SUPPORT_EMPTY")
    selected = wins[rng.randrange(len(wins))]
    required = selected.get("win_credit_required_outs")
    credited = bool(required is not None and starter_outs >= int(required))
    # We only assert lead-at-exit when the official historical score path proves a
    # permanent lead had already been obtained while the starter remained pitcher
    # of record. Lost-lead-at-exit states remain conservative zeros until a true
    # inning/PA-level current-game simulator is promoted.
    return int(credited), int(credited), None if required is None else int(required)


def _sample(
    row: Mapping[str, float],
    *,
    team_runs: int,
    opponent_runs: int,
    lead_at_exit: int,
    lead_preserved: int,
    credit_required_outs: int | None,
) -> dict[str, float]:
    out = {
        "outs": float(row["outs"]),
        "strikeouts": float(row["strikeouts"]),
        "earned_runs": float(row["earned_runs"]),
        "runs_allowed": float(row["runs_allowed"]),
        "hits_allowed": float(row["hits_allowed"]),
        "walks_allowed": float(row["walks_allowed"]),
        "hbp_allowed": float(row["hbp_allowed"]),
        "starter_exit_batters_faced": float(row["starter_exit_batters_faced"]),
        "starter_exit_pitch_count": float(row["starter_exit_pitch_count"]),
        "starter_scoped_events": 1.0,
        "lead_at_exit": float(lead_at_exit),
        "lead_preserved_to_final": float(lead_preserved),
        "complete_game_probability": float(row["complete_game_probability"]),
        "cg_shutout_probability": float(row["cg_shutout_probability"]),
        "no_hitter_probability": float(row["no_hitter_probability"]),
        "team_final_runs": float(team_runs),
        "opponent_final_runs": float(opponent_runs),
        "bullpen_runs_allowed": float(opponent_runs - int(row["runs_allowed"])),
    }
    if credit_required_outs is not None:
        out["win_credit_required_outs"] = float(credit_required_outs)
    return normalize_starter_path(out)


def build_game_starter_path_component(
    *,
    away_player_id: str,
    home_player_id: str,
    away_features: Mapping[str, Any],
    home_features: Mapping[str, Any],
    joint_score_pmf: Mapping[str, Any],
    simulations: int,
    build_hash: str,
) -> dict[str, Any]:
    """Generate aligned current-game DFS starter paths for both probable starters.

    The score PMF is shared across both starters, so only one team wins each path.
    Starter lines are empirical strictly-prior whole-start rows conditioned on being
    physically compatible with that final score. Win credit uses official prior team
    score-path timing, never historical pitcher wins or a final-score-only proxy.

    This is a starter component, not a complete DFS path snapshot; hitter/team path
    generation must join the same path set before `load_aligned_score_paths` can be
    used for a full DK lineup pool.
    """

    if isinstance(simulations, bool) or int(simulations) < MIN_PATHS:
        raise MlbStarterPathError(f"DFS_MLB_STARTER_PATHS_TOO_FEW:{simulations}")
    simulations = int(simulations)
    canonical_build_hash = validate_build_hash(build_hash)
    if not away_player_id or not home_player_id or away_player_id == home_player_id:
        raise MlbStarterPathError("DFS_MLB_STARTER_PLAYER_IDS_INVALID")

    away_source_hash = validate_build_hash(str(away_features.get("feature_source_hash") or ""))
    home_source_hash = validate_build_hash(str(home_features.get("feature_source_hash") or ""))
    away_history = _history(away_features, "AWAY")
    home_history = _history(home_features, "HOME")
    away_credit = _credit_rows(away_features, "AWAY")
    home_credit = _credit_rows(home_features, "HOME")
    scores = _score_states(joint_score_pmf)
    support = _support(away_history, home_history, scores)

    pmf_hash = canonical_json_sha256(
        {"joint_score_pmf": {str(key): joint_score_pmf[key] for key in sorted(joint_score_pmf)}}
    )
    identity = {
        "version": DFS_MLB_STARTER_PATH_VERSION,
        "build_hash": canonical_build_hash,
        "simulations": simulations,
        "away_player_id": str(away_player_id),
        "home_player_id": str(home_player_id),
        "away_feature_source_hash": away_source_hash,
        "home_feature_source_hash": home_source_hash,
        "game_score_pmf_sha256": pmf_hash,
    }
    path_set_id = canonical_json_sha256(identity)
    rng = candidate_rng(path_set_id)
    support_weights = [row.weight for row in support]

    away_samples: list[dict[str, float]] = []
    home_samples: list[dict[str, float]] = []
    for _ in range(simulations):
        state = _draw_weighted(rng, support, support_weights)
        away_row = away_history[state.away_history_index]
        home_row = home_history[state.home_history_index]
        away_won = state.score.away_runs > state.score.home_runs
        home_won = not away_won

        away_lead, away_preserved, away_required = _credit_state(
            rng,
            starter_outs=int(away_row["outs"]),
            team_won=away_won,
            credit_rows=away_credit,
        )
        home_lead, home_preserved, home_required = _credit_state(
            rng,
            starter_outs=int(home_row["outs"]),
            team_won=home_won,
            credit_rows=home_credit,
        )
        away_samples.append(
            _sample(
                away_row,
                team_runs=state.score.away_runs,
                opponent_runs=state.score.home_runs,
                lead_at_exit=away_lead,
                lead_preserved=away_preserved,
                credit_required_outs=away_required,
            )
        )
        home_samples.append(
            _sample(
                home_row,
                team_runs=state.score.home_runs,
                opponent_runs=state.score.away_runs,
                lead_at_exit=home_lead,
                lead_preserved=home_preserved,
                credit_required_outs=home_required,
            )
        )

    return {
        "version": DFS_MLB_STARTER_PATH_VERSION,
        "path_set_id": path_set_id,
        "source": DFS_MLB_STARTER_PATH_VERSION,
        "path_count": simulations,
        "game_score_pmf_sha256": pmf_hash,
        "players": [
            {
                "player_id": str(away_player_id),
                "team_side": "AWAY",
                "path_set_id": path_set_id,
                "feature_source_hash": away_source_hash,
                "samples": away_samples,
            },
            {
                "player_id": str(home_player_id),
                "team_side": "HOME",
                "path_set_id": path_set_id,
                "feature_source_hash": home_source_hash,
                "samples": home_samples,
            },
        ],
    }
