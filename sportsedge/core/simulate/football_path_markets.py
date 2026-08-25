"""Same-path football market read-outs for Engine A.

Every result in this module is a deterministic aggregation of the supplied
``GamePath`` ensemble.  No market receives an independent random draw.  This is
the structural prerequisite for coherent full-game, half, quarter, alternate,
and situational pricing.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping, Sequence

from sportsedge.core.simulate.football_path import GamePath, validate_game_path


def _three_way(values: Sequence[float], *, win: str, loss: str) -> dict[str, float]:
    n = float(len(values))
    return {
        win: sum(x > 0 for x in values) / n,
        loss: sum(x < 0 for x in values) / n,
        "push": sum(x == 0 for x in values) / n,
    }


def _moneyline(home: Sequence[int], away: Sequence[int]) -> dict[str, float]:
    n = float(len(home))
    margins = [h - a for h, a in zip(home, away)]
    return {
        "home_win": sum(x > 0 for x in margins) / n,
        "away_win": sum(x < 0 for x in margins) / n,
        "tie": sum(x == 0 for x in margins) / n,
    }


def _spread(home: Sequence[int], away: Sequence[int], line: float) -> dict[str, float]:
    return _three_way(
        [h - a + float(line) for h, a in zip(home, away)],
        win="home_cover",
        loss="away_cover",
    )


def _total(home: Sequence[int], away: Sequence[int], line: float) -> dict[str, float]:
    return _three_way(
        [h + a - float(line) for h, a in zip(home, away)],
        win="over",
        loss="under",
    )


def _score_pair(path: GamePath, period: str) -> tuple[int, int]:
    if period == "full":
        return path.home_score, path.away_score
    if period == "first_half":
        return path.q1_home + path.q2_home, path.q1_away + path.q2_away
    if period == "second_half":
        return path.q3_home + path.q4_home + path.ot_home, path.q3_away + path.q4_away + path.ot_away
    if period.startswith("q") and len(period) == 2 and period[1].isdigit():
        q = int(period[1])
        if q not in {1, 2, 3, 4}:
            raise ValueError(f"QUARTER_UNSUPPORTED:{q}")
        return int(getattr(path, f"q{q}_home")), int(getattr(path, f"q{q}_away"))
    raise ValueError(f"PERIOD_UNSUPPORTED:{period}")


def _pmf(values: Iterable[int]) -> dict[int, float]:
    rows = list(int(x) for x in values)
    n = float(len(rows))
    counts = Counter(rows)
    return {key: counts[key] / n for key in sorted(counts)}


def _first_score(path: GamePath) -> str:
    for event in path.plays:
        if event.points > 0 and event.scoring_team:
            if event.scoring_team == path.home_team:
                return "home"
            if event.scoring_team == path.away_team:
                return "away"
    return "no_score"


def _race(path: GamePath, target: int) -> str:
    for event in path.plays:
        if event.score_after_home >= target and event.score_before_home < target:
            return "home"
        if event.score_after_away >= target and event.score_before_away < target:
            return "away"
    return "neither"


def _largest_leads(path: GamePath) -> tuple[int, int]:
    home_lead = 0
    away_lead = 0
    for event in path.plays:
        margin = event.score_after_home - event.score_after_away
        home_lead = max(home_lead, margin)
        away_lead = max(away_lead, -margin)
    return home_lead, away_lead


def _winning_margin_band(path: GamePath) -> str:
    margin = path.home_score - path.away_score
    if margin == 0:
        return "tie"
    side = "home" if margin > 0 else "away"
    amount = abs(margin)
    if amount <= 3:
        band = "1_3"
    elif amount <= 7:
        band = "4_7"
    elif amount <= 13:
        band = "8_13"
    else:
        band = "14_plus"
    return f"{side}_{band}"


def derive_path_readouts(
    paths: Iterable[GamePath],
    *,
    spread_line: float | None = None,
    total_line: float | None = None,
    home_team_total_line: float | None = None,
    away_team_total_line: float | None = None,
    first_half_spread_line: float | None = None,
    first_half_total_line: float | None = None,
    second_half_spread_line: float | None = None,
    second_half_total_line: float | None = None,
    quarter_spread_lines: Mapping[int, float] | None = None,
    quarter_total_lines: Mapping[int, float] | None = None,
    alternate_spreads: Iterable[float] = (),
    alternate_totals: Iterable[float] = (),
    race_points: Iterable[int] = (),
    both_teams_score_points: Iterable[int] = (10, 20, 30),
) -> dict[str, object]:
    rows = list(paths)
    if not rows:
        raise ValueError("ENGINE_A_PATHS_REQUIRED")
    for path in rows:
        validate_game_path(path)
    game_ids = {path.game_id for path in rows}
    teams = {(path.home_team, path.away_team) for path in rows}
    if len(game_ids) != 1 or len(teams) != 1:
        raise ValueError("ENGINE_A_PATH_ENSEMBLE_IDENTITY_MISMATCH")
    n = float(len(rows))

    full = [_score_pair(path, "full") for path in rows]
    home = [x[0] for x in full]
    away = [x[1] for x in full]
    first_half = [_score_pair(path, "first_half") for path in rows]
    fh_home = [x[0] for x in first_half]
    fh_away = [x[1] for x in first_half]
    second_half = [_score_pair(path, "second_half") for path in rows]
    sh_home = [x[0] for x in second_half]
    sh_away = [x[1] for x in second_half]

    out: dict[str, object] = {
        "moneyline": _moneyline(home, away),
        "first_half_moneyline": _moneyline(fh_home, fh_away),
        "second_half_moneyline": _moneyline(sh_home, sh_away),
    }
    if spread_line is not None:
        out["spread"] = _spread(home, away, float(spread_line))
    if total_line is not None:
        out["total"] = _total(home, away, float(total_line))
    if home_team_total_line is not None:
        out["team_total_home"] = _three_way(
            [x - float(home_team_total_line) for x in home], win="over", loss="under"
        )
    if away_team_total_line is not None:
        out["team_total_away"] = _three_way(
            [x - float(away_team_total_line) for x in away], win="over", loss="under"
        )
    if first_half_spread_line is not None:
        out["first_half_spread"] = _spread(fh_home, fh_away, float(first_half_spread_line))
    if first_half_total_line is not None:
        out["first_half_total"] = _total(fh_home, fh_away, float(first_half_total_line))
    if second_half_spread_line is not None:
        out["second_half_spread"] = _spread(sh_home, sh_away, float(second_half_spread_line))
    if second_half_total_line is not None:
        out["second_half_total"] = _total(sh_home, sh_away, float(second_half_total_line))

    q_spreads = dict(quarter_spread_lines or {})
    q_totals = dict(quarter_total_lines or {})
    for q in range(1, 5):
        pairs = [_score_pair(path, f"q{q}") for path in rows]
        q_home = [x[0] for x in pairs]
        q_away = [x[1] for x in pairs]
        out[f"q{q}_moneyline"] = _moneyline(q_home, q_away)
        if q in q_spreads:
            out[f"q{q}_spread"] = _spread(q_home, q_away, float(q_spreads[q]))
        if q in q_totals:
            out[f"q{q}_total"] = _total(q_home, q_away, float(q_totals[q]))

    out["alternate_spread"] = {
        float(line): _spread(home, away, float(line)) for line in alternate_spreads
    }
    out["alternate_total"] = {
        float(line): _total(home, away, float(line)) for line in alternate_totals
    }

    first_scores = Counter(_first_score(path) for path in rows)
    out["first_score"] = {key: first_scores.get(key, 0) / n for key in ("home", "away", "no_score")}

    td_counts = [sum(event.drive_terminal == "TOUCHDOWN" for event in path.plays) for path in rows]
    out["total_touchdowns"] = {"pmf": _pmf(td_counts), "mean": sum(td_counts) / n}

    safety_yes = [any(event.drive_terminal == "SAFETY" for event in path.plays) for path in rows]
    out["safety"] = {"yes": sum(safety_yes) / n, "no": 1.0 - sum(safety_yes) / n}

    home_turnovers = []
    away_turnovers = []
    home_sacks = []
    away_sacks = []
    longest_fg = []
    largest_home = []
    largest_away = []
    margin_bands = Counter()
    for path in rows:
        home_turnovers.append(sum(
            event.turnover_type in {"INTERCEPTION", "FUMBLE"} and event.possession == path.home_team
            for event in path.plays
        ))
        away_turnovers.append(sum(
            event.turnover_type in {"INTERCEPTION", "FUMBLE"} and event.possession == path.away_team
            for event in path.plays
        ))
        # A sack credited to the defense opposite the possession team.
        home_sacks.append(sum(event.play_type == "SACK" and event.possession == path.away_team for event in path.plays))
        away_sacks.append(sum(event.play_type == "SACK" and event.possession == path.home_team for event in path.plays))
        made_distances = [
            100 - event.yardline + 17
            for event in path.plays
            if event.play_type == "FIELD_GOAL" and event.drive_terminal == "FIELD_GOAL_MADE"
        ]
        longest_fg.append(max(made_distances, default=0))
        h_lead, a_lead = _largest_leads(path)
        largest_home.append(h_lead)
        largest_away.append(a_lead)
        margin_bands[_winning_margin_band(path)] += 1

    out["team_turnovers"] = {
        "home_mean": sum(home_turnovers) / n,
        "away_mean": sum(away_turnovers) / n,
        "home_pmf": _pmf(home_turnovers),
        "away_pmf": _pmf(away_turnovers),
    }
    out["team_sacks"] = {
        "home_mean": sum(home_sacks) / n,
        "away_mean": sum(away_sacks) / n,
        "home_pmf": _pmf(home_sacks),
        "away_pmf": _pmf(away_sacks),
    }
    out["longest_fg_made"] = {"pmf": _pmf(longest_fg), "mean": sum(longest_fg) / n}
    out["largest_lead"] = {
        "home_pmf": _pmf(largest_home),
        "away_pmf": _pmf(largest_away),
        "home_mean": sum(largest_home) / n,
        "away_mean": sum(largest_away) / n,
    }
    out["winning_margin_band"] = {key: margin_bands[key] / n for key in sorted(margin_bands)}

    for target in race_points:
        target = int(target)
        if target <= 0:
            raise ValueError("RACE_POINTS_MUST_BE_POSITIVE")
        counts = Counter(_race(path, target) for path in rows)
        out[f"race_to_{target}"] = {
            key: counts.get(key, 0) / n for key in ("home", "away", "neither")
        }

    for target in both_teams_score_points:
        target = int(target)
        if target <= 0:
            raise ValueError("BOTH_TEAMS_SCORE_POINTS_MUST_BE_POSITIVE")
        yes = sum(path.home_score >= target and path.away_score >= target for path in rows) / n
        out[f"both_teams_to_score_{target}"] = {"yes": yes, "no": 1.0 - yes}

    return out
