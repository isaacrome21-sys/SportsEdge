"""PIT-safe NFL play-level research features.

Research only. This module has no production Model_P, promotion, staking, OFFICIAL,
market-eligibility, prop-engine, or registry authority. It accepts play rows that are
already ordered by game and emits team-game features using PRIOR games only.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping

MAX_RESEARCH_SEASON = 2024
DEFAULT_WINDOW_GAMES = 6


@dataclass(frozen=True)
class TeamGameResearchFeatures:
    season: int
    game_id: str
    team: str
    feature_asof_game_id: str
    prior_games: int
    lagged_epa_per_play: float
    lagged_pass_epa_per_play: float
    lagged_rush_epa_per_play: float
    lagged_success_rate: float
    lagged_explosive_play_rate: float
    lagged_early_down_pass_rate: float
    lagged_sack_rate_allowed: float
    lagged_turnover_rate: float
    lagged_qb_cpoe: float


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if isfinite(out) else default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    try:
        return float(value) == 1.0
    except (TypeError, ValueError):
        return str(value).strip().lower() in {"true", "yes", "y"}


def _aggregate_team_game(rows: list[Mapping[str, Any]], team: str) -> dict[str, float]:
    offense = [r for r in rows if str(r.get("posteam") or "") == team]
    if not offense:
        return {}
    plays = [r for r in offense if str(r.get("play_type") or "") in {"pass", "run"}]
    if not plays:
        return {}
    pass_plays = [r for r in plays if str(r.get("play_type") or "") == "pass"]
    rush_plays = [r for r in plays if str(r.get("play_type") or "") == "run"]
    early = [r for r in plays if int(_f(r.get("down"), 0)) in {1, 2}]
    cpoe = [_f(r.get("cpoe")) for r in pass_plays if r.get("cpoe") not in (None, "")]
    turnovers = sum(1 for r in plays if _truthy(r.get("interception")) or _truthy(r.get("fumble_lost")))
    sacks = sum(1 for r in pass_plays if _truthy(r.get("sack")))
    explosive = sum(1 for r in plays if _f(r.get("yards_gained")) >= (15.0 if str(r.get("play_type")) == "pass" else 10.0))
    return {
        "plays": float(len(plays)),
        "epa_sum": sum(_f(r.get("epa")) for r in plays),
        "pass_plays": float(len(pass_plays)),
        "pass_epa_sum": sum(_f(r.get("epa")) for r in pass_plays),
        "rush_plays": float(len(rush_plays)),
        "rush_epa_sum": sum(_f(r.get("epa")) for r in rush_plays),
        "successes": float(sum(1 for r in plays if _truthy(r.get("success")))),
        "explosives": float(explosive),
        "early_plays": float(len(early)),
        "early_passes": float(sum(1 for r in early if str(r.get("play_type")) == "pass")),
        "sacks": float(sacks),
        "turnovers": float(turnovers),
        "cpoe_n": float(len(cpoe)),
        "cpoe_sum": sum(cpoe),
    }


def _ratio(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


def _roll(history: deque[dict[str, float]]) -> dict[str, float]:
    sums: dict[str, float] = defaultdict(float)
    for game in history:
        for key, value in game.items():
            sums[key] += value
    return {
        "lagged_epa_per_play": _ratio(sums["epa_sum"], sums["plays"]),
        "lagged_pass_epa_per_play": _ratio(sums["pass_epa_sum"], sums["pass_plays"]),
        "lagged_rush_epa_per_play": _ratio(sums["rush_epa_sum"], sums["rush_plays"]),
        "lagged_success_rate": _ratio(sums["successes"], sums["plays"]),
        "lagged_explosive_play_rate": _ratio(sums["explosives"], sums["plays"]),
        "lagged_early_down_pass_rate": _ratio(sums["early_passes"], sums["early_plays"]),
        "lagged_sack_rate_allowed": _ratio(sums["sacks"], sums["pass_plays"]),
        "lagged_turnover_rate": _ratio(sums["turnovers"], sums["plays"]),
        "lagged_qb_cpoe": _ratio(sums["cpoe_sum"], sums["cpoe_n"]),
    }


def build_lagged_team_game_features(
    play_rows: Iterable[Mapping[str, Any]], *, window_games: int = DEFAULT_WINDOW_GAMES
) -> list[TeamGameResearchFeatures]:
    """Build prior-game-only features from ordered play rows.

    Rows must provide season, game_id and posteam. The first appearance order of each
    game defines chronology; callers should therefore feed PIT-correct chronological
    source data. Seasons after 2024 are rejected to prevent accidental use of current
    prospective evidence in retrospective research.
    """
    if window_games < 1:
        raise ValueError("NFL_RESEARCH_WINDOW_GAMES_INVALID")
    games: dict[tuple[int, str], list[Mapping[str, Any]]] = {}
    game_order: list[tuple[int, str]] = []
    for raw in play_rows:
        row = dict(raw)
        season = int(_f(row.get("season"), -1))
        if season < 2000 or season > MAX_RESEARCH_SEASON:
            raise ValueError(f"NFL_RESEARCH_SEASON_NOT_ALLOWED:{season}")
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            raise ValueError("NFL_RESEARCH_GAME_ID_REQUIRED")
        key = (season, game_id)
        if key not in games:
            games[key] = []
            game_order.append(key)
        games[key].append(row)

    histories: dict[tuple[int, str], deque[dict[str, float]]] = defaultdict(lambda: deque(maxlen=window_games))
    out: list[TeamGameResearchFeatures] = []
    for season, game_id in game_order:
        rows = games[(season, game_id)]
        teams = sorted({str(r.get("posteam") or "").strip() for r in rows if str(r.get("posteam") or "").strip()})
        current: dict[str, dict[str, float]] = {}
        for team in teams:
            hist = histories[(season, team)]
            if hist:
                rolled = _roll(hist)
                out.append(TeamGameResearchFeatures(
                    season=season,
                    game_id=game_id,
                    team=team,
                    feature_asof_game_id=game_id,
                    prior_games=len(hist),
                    **rolled,
                ))
            agg = _aggregate_team_game(rows, team)
            if agg:
                current[team] = agg
        # Critical PIT boundary: update history only AFTER emitting target-game features.
        for team, agg in current.items():
            histories[(season, team)].append(agg)
    return out
