"""Correlation-aware NFL same-game-parlay probability engine.

The contract is intentionally simple: every parlay leg is evaluated on the SAME
simulated game path.  Joint probability is empirical path frequency, never the
product of marginal leg probabilities.

This module has no OFFICIAL, Truth-Gate, staking, or promotion authority.  It is
an input to the user-directed IMPULSE presentation / promo evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence


SGP_JOINT_SCHEMA = "NFL_SGP_JOINT_V1"
LEG_RESULTS = ("WIN", "LOSS", "PUSH", "UNRESOLVED")


class NFLJointProbabilityError(ValueError):
    """Raised when a joint-probability request violates the path contract."""


@dataclass(frozen=True)
class LegEvaluation:
    result: str
    observed: float | str | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.result not in LEG_RESULTS:
            raise NFLJointProbabilityError("NFL_SGP_LEG_RESULT_INVALID")


def _norm(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "_").replace("-", "_")


def _number(value: Any, error: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLJointProbabilityError(error) from exc
    if not isfinite(out):
        raise NFLJointProbabilityError(error)
    return out


def _path_game_id(path: Mapping[str, Any]) -> str:
    return str(path.get("game_id") or "").strip()


def _path_teams(path: Mapping[str, Any]) -> tuple[str, str]:
    home = str(path.get("home_team") or "").strip()
    away = str(path.get("away_team") or "").strip()
    if not home or not away or _norm(home) == _norm(away):
        raise NFLJointProbabilityError("NFL_SGP_PATH_TEAMS_INVALID")
    return home, away


def _team_score(path: Mapping[str, Any], team: str) -> float | None:
    home, away = _path_teams(path)
    target = _norm(team)
    if target in {"HOME", _norm(home)}:
        value = path.get("home_score")
    elif target in {"AWAY", _norm(away)}:
        value = path.get("away_score")
    else:
        return None
    if value is None:
        return None
    return _number(value, "NFL_SGP_PATH_SCORE_INVALID")


def _opponent_score(path: Mapping[str, Any], team: str) -> float | None:
    home, away = _path_teams(path)
    target = _norm(team)
    if target in {"HOME", _norm(home)}:
        return _team_score(path, away)
    if target in {"AWAY", _norm(away)}:
        return _team_score(path, home)
    return None


def _player_record(path: Mapping[str, Any], player: str) -> Mapping[str, Any] | None:
    players = path.get("players")
    if not isinstance(players, Mapping):
        return None
    wanted = _norm(player)
    for key, value in players.items():
        if _norm(key) == wanted and isinstance(value, Mapping):
            return value
        if isinstance(value, Mapping):
            identity = value.get("player_id") or value.get("player_name") or value.get("name")
            if _norm(identity) == wanted:
                return value
    return None


_STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "RECEPTIONS": ("receptions", "rec", "catches"),
    "RECEIVING_YARDS": ("receiving_yards", "rec_yards", "receiving_yds"),
    "RUSHING_YARDS": ("rushing_yards", "rush_yards", "rushing_yds"),
    "RUSH_ATTEMPTS": ("rush_attempts", "rushing_attempts", "carries"),
    "PASSING_YARDS": ("passing_yards", "pass_yards", "passing_yds"),
    "PASS_ATTEMPTS": ("pass_attempts", "passing_attempts", "attempts"),
    "PASS_COMPLETIONS": ("pass_completions", "passing_completions", "completions"),
    "PASS_TDS": ("pass_tds", "passing_tds", "passing_touchdowns"),
    "INTERCEPTIONS": ("interceptions", "ints", "interceptions_thrown"),
    "TOUCHDOWNS": ("touchdowns", "tds", "total_touchdowns"),
}

_MARKET_ALIASES = {
    "ML": "MONEYLINE",
    "MONEY_LINE": "MONEYLINE",
    "GAME_SPREAD": "SPREAD",
    "GAME_TOTAL": "TOTAL",
    "TOTAL_POINTS": "TOTAL",
    "TEAM_TOTAL_POINTS": "TEAM_TOTAL",
    "ANYTIME_TD": "ANYTIME_TD",
    "ANYTIME_TOUCHDOWN": "ANYTIME_TD",
    "ATTD": "ANYTIME_TD",
    "REC": "RECEPTIONS",
    "REC_YDS": "RECEIVING_YARDS",
    "RECEIVING_YDS": "RECEIVING_YARDS",
    "RUSH_YDS": "RUSHING_YARDS",
    "RUSHING_YDS": "RUSHING_YARDS",
    "CARRIES": "RUSH_ATTEMPTS",
    "RUSHING_ATTEMPTS": "RUSH_ATTEMPTS",
    "PASS_YDS": "PASSING_YARDS",
    "PASSING_YDS": "PASSING_YARDS",
    "PASSING_ATTEMPTS": "PASS_ATTEMPTS",
    "COMPLETIONS": "PASS_COMPLETIONS",
    "PASSING_COMPLETIONS": "PASS_COMPLETIONS",
    "PASSING_TDS": "PASS_TDS",
    "INT": "INTERCEPTIONS",
    "INTS": "INTERCEPTIONS",
    "RUSH_REC_YARDS": "RUSH_REC_YARDS",
    "RUSH_+_REC_YARDS": "RUSH_REC_YARDS",
}


def _market(value: Any) -> str:
    raw = _norm(value)
    return _MARKET_ALIASES.get(raw, raw)


def _stat_value(record: Mapping[str, Any], market: str) -> float | None:
    if market == "RUSH_REC_YARDS":
        rush = _stat_value(record, "RUSHING_YARDS")
        rec = _stat_value(record, "RECEIVING_YARDS")
        if rush is None or rec is None:
            return None
        return rush + rec
    aliases = _STAT_ALIASES.get(market)
    if aliases is None:
        return None
    for key in aliases:
        if key in record and record[key] is not None:
            return _number(record[key], "NFL_SGP_PLAYER_STAT_INVALID")
    return None


def _ou_result(observed: float, line: float, side: str) -> LegEvaluation:
    if side == "OVER":
        if observed > line:
            return LegEvaluation("WIN", observed)
        if observed == line:
            return LegEvaluation("PUSH", observed)
        return LegEvaluation("LOSS", observed)
    if side == "UNDER":
        if observed < line:
            return LegEvaluation("WIN", observed)
        if observed == line:
            return LegEvaluation("PUSH", observed)
        return LegEvaluation("LOSS", observed)
    return LegEvaluation("UNRESOLVED", observed, "SIDE_MUST_BE_OVER_OR_UNDER")


def evaluate_leg(path: Mapping[str, Any], leg: Mapping[str, Any]) -> LegEvaluation:
    """Evaluate one sportsbook-style leg on one complete simulation path."""
    market = _market(leg.get("market"))
    side = _norm(leg.get("side"))

    if market == "MONEYLINE":
        team = str(leg.get("team") or leg.get("side") or "").strip()
        team_score = _team_score(path, team)
        opp_score = _opponent_score(path, team)
        if team_score is None or opp_score is None:
            return LegEvaluation("UNRESOLVED", None, "TEAM_OR_SCORE_MISSING")
        if team_score > opp_score:
            return LegEvaluation("WIN", team_score - opp_score)
        if team_score == opp_score:
            return LegEvaluation("PUSH", 0.0)
        return LegEvaluation("LOSS", team_score - opp_score)

    if market == "SPREAD":
        team = str(leg.get("team") or "").strip()
        if not team or leg.get("line") is None:
            return LegEvaluation("UNRESOLVED", None, "TEAM_OR_LINE_MISSING")
        team_score = _team_score(path, team)
        opp_score = _opponent_score(path, team)
        if team_score is None or opp_score is None:
            return LegEvaluation("UNRESOLVED", None, "TEAM_OR_SCORE_MISSING")
        line = _number(leg["line"], "NFL_SGP_LINE_INVALID")
        adjusted = team_score + line - opp_score
        if adjusted > 0:
            return LegEvaluation("WIN", team_score - opp_score)
        if adjusted == 0:
            return LegEvaluation("PUSH", team_score - opp_score)
        return LegEvaluation("LOSS", team_score - opp_score)

    if market == "TOTAL":
        if leg.get("line") is None:
            return LegEvaluation("UNRESOLVED", None, "LINE_MISSING")
        home = path.get("home_score")
        away = path.get("away_score")
        if home is None or away is None:
            return LegEvaluation("UNRESOLVED", None, "SCORE_MISSING")
        observed = _number(home, "NFL_SGP_PATH_SCORE_INVALID") + _number(
            away, "NFL_SGP_PATH_SCORE_INVALID"
        )
        return _ou_result(observed, _number(leg["line"], "NFL_SGP_LINE_INVALID"), side)

    if market == "TEAM_TOTAL":
        team = str(leg.get("team") or "").strip()
        if not team or leg.get("line") is None:
            return LegEvaluation("UNRESOLVED", None, "TEAM_OR_LINE_MISSING")
        observed = _team_score(path, team)
        if observed is None:
            return LegEvaluation("UNRESOLVED", None, "TEAM_OR_SCORE_MISSING")
        return _ou_result(observed, _number(leg["line"], "NFL_SGP_LINE_INVALID"), side)

    if market == "ANYTIME_TD":
        player = str(leg.get("player") or leg.get("player_id") or leg.get("player_name") or "").strip()
        if not player:
            return LegEvaluation("UNRESOLVED", None, "PLAYER_MISSING")
        record = _player_record(path, player)
        if record is None:
            return LegEvaluation("UNRESOLVED", None, "PLAYER_PATH_MISSING")
        touchdowns = _stat_value(record, "TOUCHDOWNS")
        if touchdowns is None:
            return LegEvaluation("UNRESOLVED", None, "TOUCHDOWN_STAT_MISSING")
        yes = side in {"YES", "OVER", "1+", "1_PLUS", ""}
        no = side in {"NO", "UNDER"}
        if not yes and not no:
            return LegEvaluation("UNRESOLVED", touchdowns, "ANYTIME_TD_SIDE_INVALID")
        hit = touchdowns >= 1.0
        return LegEvaluation("WIN" if hit == yes else "LOSS", touchdowns)

    if market in set(_STAT_ALIASES) | {"RUSH_REC_YARDS"}:
        player = str(leg.get("player") or leg.get("player_id") or leg.get("player_name") or "").strip()
        if not player or leg.get("line") is None:
            return LegEvaluation("UNRESOLVED", None, "PLAYER_OR_LINE_MISSING")
        record = _player_record(path, player)
        if record is None:
            return LegEvaluation("UNRESOLVED", None, "PLAYER_PATH_MISSING")
        observed = _stat_value(record, market)
        if observed is None:
            return LegEvaluation("UNRESOLVED", None, "PLAYER_STAT_MISSING")
        return _ou_result(observed, _number(leg["line"], "NFL_SGP_LINE_INVALID"), side)

    return LegEvaluation("UNRESOLVED", None, f"MARKET_UNSUPPORTED:{market}")


def _validate_game_identity(paths: Sequence[Mapping[str, Any]], legs: Sequence[Mapping[str, Any]], game_id: str | None) -> str | None:
    requested = str(game_id or "").strip() or None
    leg_games = {str(leg.get("game_id") or "").strip() for leg in legs if str(leg.get("game_id") or "").strip()}
    if len(leg_games) > 1:
        raise NFLJointProbabilityError("NFL_SGP_MULTIPLE_LEG_GAMES")
    if requested is None and leg_games:
        requested = next(iter(leg_games))
    if requested is not None and leg_games and requested not in leg_games:
        raise NFLJointProbabilityError("NFL_SGP_GAME_ID_MISMATCH")

    path_games = {_path_game_id(path) for path in paths if _path_game_id(path)}
    if len(path_games) > 1:
        if requested is None:
            raise NFLJointProbabilityError("NFL_SGP_MULTIPLE_PATH_GAMES")
        if requested not in path_games:
            raise NFLJointProbabilityError("NFL_SGP_GAME_ID_MISMATCH")
    elif requested is not None and path_games and requested not in path_games:
        raise NFLJointProbabilityError("NFL_SGP_GAME_ID_MISMATCH")
    return requested


def joint_probability_from_paths(
    simulation_paths: Iterable[Mapping[str, Any]],
    legs: Sequence[Mapping[str, Any]],
    *,
    game_id: str | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """Estimate SGP probability by evaluating all legs on each same-game path.

    A path counts as a full parlay win only when every leg is WIN.  Any PUSH is
    tracked separately because sportsbook payout after a voided SGP leg differs
    from the original quoted SGP price; pushes are never silently promoted to a
    win.  With ``strict=True`` (default), missing/unresolved leg data fails closed.
    """
    paths = [dict(path) for path in simulation_paths]
    if not paths:
        raise NFLJointProbabilityError("NFL_SGP_SIMULATION_PATHS_REQUIRED")
    if not legs:
        raise NFLJointProbabilityError("NFL_SGP_LEGS_REQUIRED")
    leg_list = [dict(leg) for leg in legs]
    resolved_game = _validate_game_identity(paths, leg_list, game_id)
    if resolved_game is not None:
        paths = [path for path in paths if not _path_game_id(path) or _path_game_id(path) == resolved_game]
        if not paths:
            raise NFLJointProbabilityError("NFL_SGP_NO_MATCHING_GAME_PATHS")

    marginal = [dict(win=0, loss=0, push=0, unresolved=0) for _ in leg_list]
    full_wins = 0
    losses = 0
    pushes = 0
    unresolved = 0
    resolved_paths = 0

    for path in paths:
        evaluations = [evaluate_leg(path, leg) for leg in leg_list]
        for idx, evaluation in enumerate(evaluations):
            marginal[idx][evaluation.result.lower()] += 1

        results = {evaluation.result for evaluation in evaluations}
        if "UNRESOLVED" in results:
            unresolved += 1
            if strict:
                reasons = [evaluation.reason for evaluation in evaluations if evaluation.result == "UNRESOLVED"]
                raise NFLJointProbabilityError(
                    "NFL_SGP_UNRESOLVED_PATH:" + ",".join(str(reason) for reason in reasons)
                )
            continue

        resolved_paths += 1
        if results == {"WIN"}:
            full_wins += 1
        elif "LOSS" in results:
            losses += 1
        else:
            pushes += 1

    if resolved_paths <= 0:
        raise NFLJointProbabilityError("NFL_SGP_NO_RESOLVED_PATHS")

    marginal_rows: list[dict[str, Any]] = []
    total_paths = len(paths)
    for idx, counts in enumerate(marginal):
        leg_resolved = counts["win"] + counts["loss"] + counts["push"]
        marginal_rows.append(
            {
                "leg_index": idx,
                "market": _market(leg_list[idx].get("market")),
                "win_probability": None if leg_resolved == 0 else counts["win"] / leg_resolved,
                "push_probability": None if leg_resolved == 0 else counts["push"] / leg_resolved,
                "resolved_paths": leg_resolved,
                "unresolved_paths": counts["unresolved"],
            }
        )

    return {
        "schema_version": SGP_JOINT_SCHEMA,
        "game_id": resolved_game,
        "method": "SAME_SIMULATION_PATHS",
        "independence_assumption": False,
        "joint_model_probability": full_wins / resolved_paths,
        "full_win_paths": full_wins,
        "loss_paths": losses,
        "push_paths": pushes,
        "unresolved_paths": unresolved,
        "resolved_paths": resolved_paths,
        "total_paths": total_paths,
        "resolved_fraction": resolved_paths / total_paths,
        "marginals": marginal_rows,
        "push_policy": "TRACK_SEPARATELY_NOT_FULL_WIN",
        "strict_missing_data": bool(strict),
    }


def enrich_sgp_candidates_with_joint_probability(
    candidates: Sequence[Mapping[str, Any]],
    simulation_paths: Iterable[Mapping[str, Any]],
    *,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """Attach same-path joint P to candidates before promo-EV ranking."""
    paths = [dict(path) for path in simulation_paths]
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        legs = candidate.get("legs")
        if not isinstance(legs, Sequence) or isinstance(legs, (str, bytes)) or not legs:
            raise NFLJointProbabilityError("NFL_SGP_CANDIDATE_LEGS_REQUIRED")
        if not all(isinstance(leg, Mapping) for leg in legs):
            raise NFLJointProbabilityError("NFL_SGP_CANDIDATE_LEG_INVALID")
        diagnostic = joint_probability_from_paths(
            paths,
            list(legs),
            game_id=str(candidate.get("game_id") or "").strip() or None,
            strict=strict,
        )
        row["joint_model_probability"] = diagnostic["joint_model_probability"]
        row["joint_probability_method"] = diagnostic["method"]
        row["joint_probability_diagnostics"] = diagnostic
        enriched.append(row)
    return enriched
