"""Research-only NFL M2 V2G structural scoring-event candidate.

This module is intentionally market blind. It learns team scoring-event rates only
from training rows that summarize offensive possessions, then generates football-
native integer score support from touchdown and made-field-goal counts.

It does not grant production Model_P authority and is not consumed by the
production registry or bettor-facing RUN IT path.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial, isfinite, sqrt
from typing import Any, Iterable, Mapping

NFL_M2_V2G_CANDIDATE_MODEL_ID = "nfl_m2_scoring_event_v2g_candidate"
NFL_M2_V2G_DISTRIBUTION_CONTRACT = "NFL_M2_V2G_STRUCTURAL_SCORING_EVENT_V1"
NFL_M2_V2G_EVENT_CONTRACT = "NFL_M2_V2G_POSSESSION_EVENT_ROWS_V1"

_MARKET_FIELDS = {
    "spread_line", "total_line", "moneyline", "home_moneyline", "away_moneyline",
    "home_spread_odds", "away_spread_odds", "over_odds", "under_odds",
    "closing_spread", "closing_total",
}


def _float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _int(value: Any) -> int | None:
    parsed = _float(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _truthy_one(value: Any) -> bool:
    parsed = _float(value)
    return parsed is not None and parsed == 1.0


def _clamp_probability(value: float, *, floor: float = 1e-6, ceiling: float = 0.95) -> float:
    return max(floor, min(ceiling, float(value)))


@dataclass(frozen=True)
class NFLV2GTeamState:
    games: int
    drives: int
    touchdowns: int
    field_goals: int
    drives_faced: int
    touchdowns_allowed: int
    field_goals_allowed: int


@dataclass(frozen=True)
class NFLM2V2GCandidateModel:
    model_id: str
    distribution_contract: str
    event_contract: str
    train_seasons: tuple[int, ...]
    league_drives_per_team_game: float
    league_td_rate: float
    league_fg_rate: float
    team_state: Mapping[str, NFLV2GTeamState]
    prior_drives: float
    max_touchdowns: int
    max_field_goals: int


def build_nfl_v2g_game_event_rows(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse manifest-bound play-by-play into offensive possession event rows.

    A touchdown is credited only when the source explicitly reports the scoring
    team and that team equals ``posteam``. This prevents defensive/return scores
    from being mislabeled as offensive scoring drives.
    """
    schedule: dict[str, dict[str, Any]] = {}
    for raw in schedule_rows:
        row = dict(raw)
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        if str(row.get("game_type") or "REG").upper() != "REG":
            continue
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        season = _int(row.get("season"))
        if not home or not away or season is None:
            raise ValueError(f"NFL_M2_V2G_SCHEDULE_IDENTITY_INVALID:{game_id}")
        schedule[game_id] = row

    possessions: dict[tuple[str, str, str], dict[str, bool]] = {}
    games_seen: set[str] = set()
    for raw in pbp_rows:
        row = dict(raw)
        game_id = str(row.get("game_id") or "").strip()
        if game_id not in schedule:
            continue
        posteam = str(row.get("posteam") or "").strip()
        drive = str(row.get("drive") or "").strip()
        if not posteam or not drive:
            raise ValueError(f"NFL_M2_V2G_POSSESSION_IDENTITY_MISSING:{game_id}")
        home = str(schedule[game_id]["home_team"])
        away = str(schedule[game_id]["away_team"])
        if posteam not in {home, away}:
            continue
        key = (game_id, posteam, drive)
        state = possessions.setdefault(key, {"touchdown": False, "field_goal": False})
        if _truthy_one(row.get("touchdown")):
            td_team = str(row.get("td_team") or "").strip()
            if td_team and td_team == posteam:
                state["touchdown"] = True
        play_type = str(row.get("play_type") or "").strip().lower()
        field_goal_result = str(row.get("field_goal_result") or "").strip().lower()
        if play_type == "field_goal" and field_goal_result == "made":
            state["field_goal"] = True
        games_seen.add(game_id)

    by_game_team: dict[tuple[str, str], dict[str, int]] = {}
    for (game_id, team, _drive), state in possessions.items():
        agg = by_game_team.setdefault(
            (game_id, team),
            {"drives": 0, "touchdowns": 0, "field_goals": 0, "other_no_score": 0},
        )
        agg["drives"] += 1
        if state["touchdown"]:
            agg["touchdowns"] += 1
        elif state["field_goal"]:
            agg["field_goals"] += 1
        else:
            agg["other_no_score"] += 1

    output: list[dict[str, Any]] = []
    for game_id in sorted(games_seen):
        game = schedule[game_id]
        home = str(game["home_team"])
        away = str(game["away_team"])
        home_events = by_game_team.get((game_id, home))
        away_events = by_game_team.get((game_id, away))
        if not home_events or not away_events:
            raise ValueError(f"NFL_M2_V2G_TEAM_POSSESSIONS_MISSING:{game_id}")
        if home_events["drives"] <= 0 or away_events["drives"] <= 0:
            raise ValueError(f"NFL_M2_V2G_DRIVE_COUNT_INVALID:{game_id}")
        row = {
            "event_contract": NFL_M2_V2G_EVENT_CONTRACT,
            "game_id": game_id,
            "season": int(game["season"]),
            "week": game.get("week"),
            "home_team": home,
            "away_team": away,
            "home_drives": home_events["drives"],
            "home_touchdowns": home_events["touchdowns"],
            "home_field_goals": home_events["field_goals"],
            "home_other_no_score": home_events["other_no_score"],
            "away_drives": away_events["drives"],
            "away_touchdowns": away_events["touchdowns"],
            "away_field_goals": away_events["field_goals"],
            "away_other_no_score": away_events["other_no_score"],
        }
        for field in (
            "home_score", "away_score", "spread_line", "total_line",
            "home_spread_odds", "away_spread_odds", "over_odds", "under_odds",
        ):
            if field in game:
                row[field] = game[field]
        output.append(row)
    return output


def _validate_training_row(row: Mapping[str, Any]) -> tuple[str, str, int, dict[str, int]]:
    if str(row.get("event_contract") or "") != NFL_M2_V2G_EVENT_CONTRACT:
        raise ValueError("NFL_M2_V2G_EVENT_CONTRACT_INVALID")
    home = str(row.get("home_team") or "").strip()
    away = str(row.get("away_team") or "").strip()
    season = _int(row.get("season"))
    if not home or not away or home == away or season is None:
        raise ValueError("NFL_M2_V2G_TRAINING_IDENTITY_INVALID")
    counts: dict[str, int] = {}
    for side in ("home", "away"):
        drives = _int(row.get(f"{side}_drives"))
        td = _int(row.get(f"{side}_touchdowns"))
        fg = _int(row.get(f"{side}_field_goals"))
        other = _int(row.get(f"{side}_other_no_score"))
        if None in (drives, td, fg, other):
            raise ValueError("NFL_M2_V2G_EVENT_COUNT_MISSING")
        assert drives is not None and td is not None and fg is not None and other is not None
        if min(drives, td, fg, other) < 0 or td + fg + other != drives:
            raise ValueError("NFL_M2_V2G_EVENT_COUNT_INVALID")
        counts[f"{side}_drives"] = drives
        counts[f"{side}_touchdowns"] = td
        counts[f"{side}_field_goals"] = fg
    return home, away, season, counts


def fit_nfl_m2_v2g_candidate(
    rows: Iterable[Mapping[str, Any]],
    *,
    prior_drives: float = 48.0,
    max_touchdowns: int = 9,
    max_field_goals: int = 9,
) -> NFLM2V2GCandidateModel:
    data = [dict(row) for row in rows]
    if len(data) < 2:
        raise ValueError("NFL_M2_V2G_TRAINING_ROWS_INSUFFICIENT")
    if not isfinite(float(prior_drives)) or float(prior_drives) <= 0.0:
        raise ValueError("NFL_M2_V2G_PRIOR_DRIVES_INVALID")
    if max_touchdowns < 1 or max_field_goals < 1:
        raise ValueError("NFL_M2_V2G_EVENT_SUPPORT_INVALID")

    totals = {"games": 0, "drives": 0, "td": 0, "fg": 0}
    mutable: dict[str, dict[str, int]] = {}
    seasons: set[int] = set()
    for row in data:
        home, away, season, counts = _validate_training_row(row)
        seasons.add(season)
        totals["games"] += 2
        for side, team, opponent in (("home", home, away), ("away", away, home)):
            drives = counts[f"{side}_drives"]
            td = counts[f"{side}_touchdowns"]
            fg = counts[f"{side}_field_goals"]
            totals["drives"] += drives
            totals["td"] += td
            totals["fg"] += fg
            own = mutable.setdefault(team, {"games": 0, "drives": 0, "td": 0, "fg": 0, "faced": 0, "td_allowed": 0, "fg_allowed": 0})
            own["games"] += 1
            own["drives"] += drives
            own["td"] += td
            own["fg"] += fg
            opp = mutable.setdefault(opponent, {"games": 0, "drives": 0, "td": 0, "fg": 0, "faced": 0, "td_allowed": 0, "fg_allowed": 0})
            opp["faced"] += drives
            opp["td_allowed"] += td
            opp["fg_allowed"] += fg

    if totals["drives"] <= 0 or totals["games"] <= 0:
        raise ValueError("NFL_M2_V2G_LEAGUE_STATE_EMPTY")
    league_td = totals["td"] / float(totals["drives"])
    league_fg = totals["fg"] / float(totals["drives"])
    if league_td + league_fg >= 1.0:
        raise ValueError("NFL_M2_V2G_LEAGUE_EVENT_RATES_INVALID")
    league_drives = totals["drives"] / float(totals["games"])
    states = {
        team: NFLV2GTeamState(
            games=value["games"], drives=value["drives"], touchdowns=value["td"],
            field_goals=value["fg"], drives_faced=value["faced"],
            touchdowns_allowed=value["td_allowed"], field_goals_allowed=value["fg_allowed"],
        )
        for team, value in sorted(mutable.items())
    }
    return NFLM2V2GCandidateModel(
        model_id=NFL_M2_V2G_CANDIDATE_MODEL_ID,
        distribution_contract=NFL_M2_V2G_DISTRIBUTION_CONTRACT,
        event_contract=NFL_M2_V2G_EVENT_CONTRACT,
        train_seasons=tuple(sorted(seasons)),
        league_drives_per_team_game=league_drives,
        league_td_rate=league_td,
        league_fg_rate=league_fg,
        team_state=states,
        prior_drives=float(prior_drives),
        max_touchdowns=int(max_touchdowns),
        max_field_goals=int(max_field_goals),
    )


def _smoothed_rate(events: int, drives: int, league_rate: float, prior_drives: float) -> float:
    return (float(events) + prior_drives * league_rate) / (float(drives) + prior_drives)


def _team_projection(model: NFLM2V2GCandidateModel, offense: str, defense: str) -> tuple[float, float, float]:
    off = model.team_state.get(offense)
    deff = model.team_state.get(defense)
    if off is None or deff is None:
        raise ValueError(f"NFL_M2_V2G_TEAM_STATE_MISSING:{offense}:{defense}")
    off_td = _smoothed_rate(off.touchdowns, off.drives, model.league_td_rate, model.prior_drives)
    off_fg = _smoothed_rate(off.field_goals, off.drives, model.league_fg_rate, model.prior_drives)
    def_td = _smoothed_rate(deff.touchdowns_allowed, deff.drives_faced, model.league_td_rate, model.prior_drives)
    def_fg = _smoothed_rate(deff.field_goals_allowed, deff.drives_faced, model.league_fg_rate, model.prior_drives)
    td_rate = _clamp_probability(sqrt(off_td * def_td), ceiling=0.80)
    fg_rate = _clamp_probability(sqrt(off_fg * def_fg), ceiling=0.50)
    if td_rate + fg_rate >= 0.98:
        scale = 0.98 / (td_rate + fg_rate)
        td_rate *= scale
        fg_rate *= scale
    off_drives = off.drives / float(off.games) if off.games else model.league_drives_per_team_game
    def_drives = deff.drives_faced / float(deff.games) if deff.games else model.league_drives_per_team_game
    expected_drives = max(1.0, (off_drives + def_drives + model.league_drives_per_team_game) / 3.0)
    return expected_drives, td_rate, fg_rate


def _poisson_pmf(lam: float, maximum: int) -> list[float]:
    if not isfinite(lam) or lam < 0.0:
        raise ValueError("NFL_M2_V2G_POISSON_RATE_INVALID")
    values = [exp(-lam) * (lam ** k) / factorial(k) for k in range(maximum + 1)]
    total = sum(values)
    if total <= 0.0 or not isfinite(total):
        raise ValueError("NFL_M2_V2G_POISSON_NORMALIZATION_FAILED")
    return [value / total for value in values]


def _team_score_distribution(model: NFLM2V2GCandidateModel, offense: str, defense: str) -> dict[int, float]:
    drives, td_rate, fg_rate = _team_projection(model, offense, defense)
    td_pmf = _poisson_pmf(drives * td_rate, model.max_touchdowns)
    fg_pmf = _poisson_pmf(drives * fg_rate, model.max_field_goals)
    scores: dict[int, float] = {}
    for td_count, td_prob in enumerate(td_pmf):
        for fg_count, fg_prob in enumerate(fg_pmf):
            score = 7 * td_count + 3 * fg_count
            scores[score] = scores.get(score, 0.0) + td_prob * fg_prob
    total = sum(scores.values())
    if total <= 0.0:
        raise ValueError("NFL_M2_V2G_TEAM_SCORE_DISTRIBUTION_EMPTY")
    return {score: probability / total for score, probability in sorted(scores.items())}


def derive_nfl_m2_v2g_score_distribution(
    model: NFLM2V2GCandidateModel,
    row: Mapping[str, Any],
) -> tuple[dict[str, float | int], ...]:
    if model.model_id != NFL_M2_V2G_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_M2_V2G_MODEL_IDENTITY_INVALID")
    if model.distribution_contract != NFL_M2_V2G_DISTRIBUTION_CONTRACT:
        raise ValueError("NFL_M2_V2G_DISTRIBUTION_CONTRACT_INVALID")
    home = str(row.get("home_team") or "").strip()
    away = str(row.get("away_team") or "").strip()
    if not home or not away or home == away:
        raise ValueError("NFL_M2_V2G_PREDICTION_IDENTITY_INVALID")
    _ = tuple(field for field in _MARKET_FIELDS if field in row)
    home_scores = _team_score_distribution(model, home, away)
    away_scores = _team_score_distribution(model, away, home)
    distribution = tuple(
        {
            "home_score": int(home_score), "away_score": int(away_score),
            "margin": int(home_score - away_score), "total": int(home_score + away_score),
            "weight": float(home_prob * away_prob),
        }
        for home_score, home_prob in home_scores.items()
        for away_score, away_prob in away_scores.items()
    )
    weight = sum(float(item["weight"]) for item in distribution)
    if abs(weight - 1.0) > 1e-10:
        raise ValueError("NFL_M2_V2G_WEIGHT_CONSERVATION_FAILED")
    return distribution
