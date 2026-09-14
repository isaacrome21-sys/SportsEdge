"""V2K attempt-0 football-native research core.

Deterministic mechanics only: source-normalized ordered drives, empirical-Bayes style
partial pooling, training-derived football-state distributions, and one sequential joint
score path. This module intentionally contains no historical candidate evaluation and
has no Model_P, pricing, promotion, staking, RUN IT, OFFICIAL, or untouched authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import Iterable, Mapping, Sequence

DRIVE_OUTCOMES = ("TD", "FG", "TURNOVER", "PUNT_OTHER", "SAFETY", "DEF_ST_SCORE")
STATE_BUCKETS = ("NORMAL", "LATE_TIED", "LATE_TRAILING", "LATE_LEADING", "OVERTIME")
FIELD_BUCKETS = ("SHORT_FIELD", "MID_FIELD", "LONG_FIELD")


def _field_bucket(yardline_100: float) -> str:
    y = float(yardline_100)
    if y <= 35.0:
        return "SHORT_FIELD"
    if y <= 65.0:
        return "MID_FIELD"
    return "LONG_FIELD"


def _state_bucket(period: int, clock_seconds: int, offense_score: int, defense_score: int, *, overtime: bool = False) -> str:
    if overtime:
        return "OVERTIME"
    if int(period) < 4 or int(clock_seconds) > 300:
        return "NORMAL"
    diff = int(offense_score) - int(defense_score)
    if diff == 0:
        return "LATE_TIED"
    if diff < 0:
        return "LATE_TRAILING"
    return "LATE_LEADING"


@dataclass(frozen=True)
class DriveRow:
    game_id: str
    season: int
    week: int
    kickoff_utc: str
    drive_index: int
    offense: str
    defense: str
    start_yardline_100: float
    outcome: str
    offense_score_before: int
    defense_score_before: int
    offense_score_after: int
    defense_score_after: int
    period: int
    clock_seconds_remaining_period: int
    conversion_points: int = 0
    source_manifest_sha256: str = ""
    source_code_sha: str = ""

    def validate(self) -> None:
        if not self.game_id or not self.offense or not self.defense or self.offense == self.defense:
            raise ValueError("V2K_DRIVE_IDENTITY_INVALID")
        if self.outcome not in DRIVE_OUTCOMES:
            raise ValueError("V2K_DRIVE_OUTCOME_UNMAPPED")
        if self.drive_index < 0 or self.period < 1 or self.clock_seconds_remaining_period < 0:
            raise ValueError("V2K_DRIVE_CHRONOLOGY_INVALID")
        if not 0.0 <= float(self.start_yardline_100) <= 100.0:
            raise ValueError("V2K_START_FIELD_POSITION_INVALID")
        if any(x < 0 for x in (self.offense_score_before, self.defense_score_before, self.offense_score_after, self.defense_score_after)):
            raise ValueError("V2K_SCORE_STATE_INVALID")
        if self.conversion_points not in (0, 1, 2):
            raise ValueError("V2K_CONVERSION_INVALID")
        if not self.source_manifest_sha256 or not self.source_code_sha:
            raise ValueError("V2K_SOURCE_BINDING_REQUIRED")


def normalize_drive_rows(rows: Iterable[DriveRow]) -> tuple[DriveRow, ...]:
    ordered = tuple(sorted(rows, key=lambda r: (r.game_id, r.drive_index)))
    last: dict[str, int] = {}
    for row in ordered:
        row.validate()
        expected = last.get(row.game_id, -1) + 1
        if row.drive_index != expected:
            raise ValueError("V2K_DRIVE_INDEX_GAP_OR_DUPLICATE")
        last[row.game_id] = row.drive_index
    return ordered


def _variance(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)


def _distribution(rows: Sequence[DriveRow]) -> dict[str, float]:
    if not rows:
        return {o: 0.0 for o in DRIVE_OUTCOMES}
    n = len(rows)
    return {o: sum(r.outcome == o for r in rows) / n for o in DRIVE_OUTCOMES}


def _delta(dist: Mapping[str, float], baseline: Mapping[str, float]) -> dict[str, float]:
    return {o: float(dist[o]) - float(baseline[o]) for o in DRIVE_OUTCOMES}


@dataclass(frozen=True)
class HierarchicalStrength:
    league_baseline: Mapping[str, float]
    offense_effect: Mapping[str, Mapping[str, float]]
    defense_effect: Mapping[str, Mapping[str, float]]
    shrinkage_weight: Mapping[str, float]
    state_effect: Mapping[str, Mapping[str, float]]
    field_effect: Mapping[str, Mapping[str, float]]
    conversion_probabilities: Mapping[int, float]
    start_field_positions: tuple[float, ...]
    regulation_drive_counts: tuple[int, ...]
    exceptional_score_points: tuple[int, ...]

    def probabilities(self, offense: str, defense: str, *, start_yardline_100: float, state_bucket: str) -> dict[str, float]:
        if state_bucket not in STATE_BUCKETS:
            raise ValueError("V2K_STATE_BUCKET_INVALID")
        field_bucket = _field_bucket(start_yardline_100)
        vals: dict[str, float] = {}
        for outcome in DRIVE_OUTCOMES:
            p = float(self.league_baseline[outcome])
            p += float(self.offense_effect.get(offense, {}).get(outcome, 0.0))
            p += float(self.defense_effect.get(defense, {}).get(outcome, 0.0))
            p += float(self.state_effect.get(state_bucket, {}).get(outcome, 0.0))
            p += float(self.field_effect.get(field_bucket, {}).get(outcome, 0.0))
            vals[outcome] = max(0.0, p)
        total = sum(vals.values())
        if not isfinite(total) or total <= 0:
            raise ValueError("V2K_DRIVE_PROBABILITY_INVALID")
        return {k: v / total for k, v in vals.items()}


def fit_hierarchical_strength(rows: Sequence[DriveRow]) -> HierarchicalStrength:
    rows = normalize_drive_rows(rows)
    if not rows:
        raise ValueError("V2K_TRAINING_ROWS_REQUIRED")
    league = _distribution(rows)
    by_off: dict[str, list[DriveRow]] = defaultdict(list)
    by_def: dict[str, list[DriveRow]] = defaultdict(list)
    by_state: dict[str, list[DriveRow]] = defaultdict(list)
    by_field: dict[str, list[DriveRow]] = defaultdict(list)
    by_game: dict[str, int] = Counter()
    for r in rows:
        by_off[r.offense].append(r)
        by_def[r.defense].append(r)
        by_state[_state_bucket(r.period, r.clock_seconds_remaining_period, r.offense_score_before, r.defense_score_before)].append(r)
        by_field[_field_bucket(r.start_yardline_100)].append(r)
        by_game[r.game_id] += 1

    raw_team_td = [sum(r.outcome == "TD" for r in group) / len(group) for group in by_off.values()]
    between = _variance(raw_team_td)
    within = max(league["TD"] * (1.0 - league["TD"]), 1e-9)
    shrinkage: dict[str, float] = {}
    off_effect: dict[str, dict[str, float]] = {}
    def_effect: dict[str, dict[str, float]] = {}

    for team, group in by_off.items():
        w = (len(group) * between) / (len(group) * between + within) if between > 0 else 0.0
        shrinkage[team] = w
        dist = _distribution(group)
        off_effect[team] = {o: w * (dist[o] - league[o]) for o in DRIVE_OUTCOMES}
    for team, group in by_def.items():
        w = (len(group) * between) / (len(group) * between + within) if between > 0 else 0.0
        shrinkage.setdefault(team, w)
        dist = _distribution(group)
        def_effect[team] = {o: w * (dist[o] - league[o]) for o in DRIVE_OUTCOMES}

    state_effect = {bucket: _delta(_distribution(by_state[bucket]), league) if by_state[bucket] else {o: 0.0 for o in DRIVE_OUTCOMES} for bucket in STATE_BUCKETS}
    field_effect = {bucket: _delta(_distribution(by_field[bucket]), league) if by_field[bucket] else {o: 0.0 for o in DRIVE_OUTCOMES} for bucket in FIELD_BUCKETS}

    td_rows = [r for r in rows if r.outcome == "TD"]
    if td_rows:
        conv_counts = Counter(r.conversion_points for r in td_rows)
        conversion_probabilities = {points: conv_counts.get(points, 0) / len(td_rows) for points in (0, 1, 2)}
    else:
        conversion_probabilities = {0: 1.0, 1: 0.0, 2: 0.0}

    exceptional = tuple(
        max(0, r.defense_score_after - r.defense_score_before)
        for r in rows
        if r.outcome == "DEF_ST_SCORE" and r.defense_score_after > r.defense_score_before
    )

    return HierarchicalStrength(
        league_baseline=league,
        offense_effect=off_effect,
        defense_effect=def_effect,
        shrinkage_weight=shrinkage,
        state_effect=state_effect,
        field_effect=field_effect,
        conversion_probabilities=conversion_probabilities,
        start_field_positions=tuple(float(r.start_yardline_100) for r in rows),
        regulation_drive_counts=tuple(by_game[g] for g in sorted(by_game)),
        exceptional_score_points=exceptional,
    )


@dataclass(frozen=True)
class GameState:
    home_team: str
    away_team: str
    possession: str
    home_score: int = 0
    away_score: int = 0
    period: int = 1
    seconds_remaining_period: int = 900
    drive_index: int = 0
    overtime: bool = False


@dataclass(frozen=True)
class SimulationResult:
    home_score: int
    away_score: int
    margin: int
    total: int
    team_totals: Mapping[str, int]
    path: tuple[Mapping[str, object], ...]


def _draw_named(probs: Mapping[object, float], order: Sequence[object], rng: Random):
    u = rng.random()
    c = 0.0
    for key in order:
        c += float(probs[key])
        if u <= c:
            return key
    return order[-1]


def _clock_state(next_drive_index: int, regulation_drives: int) -> tuple[int, int]:
    if next_drive_index >= regulation_drives:
        return 4, 0
    progress = next_drive_index / regulation_drives
    period = min(4, int(progress * 4) + 1)
    within = (progress * 4) - int(progress * 4)
    seconds = max(0, int(round(900 * (1.0 - within))))
    return period, seconds


def simulate_joint_game(
    model: HierarchicalStrength,
    home_team: str,
    away_team: str,
    *,
    seed: int,
    regulation_drives: int | None = None,
    max_overtime_drives: int = 8,
) -> SimulationResult:
    if home_team == away_team or max_overtime_drives <= 0:
        raise ValueError("V2K_SIMULATION_ARGUMENT_INVALID")
    rng = Random(seed)
    if regulation_drives is None:
        if not model.regulation_drive_counts:
            raise ValueError("V2K_POSSESSION_DISTRIBUTION_REQUIRED")
        regulation_drives = int(model.regulation_drive_counts[rng.randrange(len(model.regulation_drive_counts))])
    if regulation_drives <= 0:
        raise ValueError("V2K_SIMULATION_ARGUMENT_INVALID")

    state = GameState(home_team, away_team, possession=home_team)
    path: list[Mapping[str, object]] = []
    ot_drives = 0

    while state.drive_index < regulation_drives or (state.home_score == state.away_score and ot_drives < max_overtime_drives):
        in_ot = state.drive_index >= regulation_drives
        if in_ot:
            ot_drives += 1
        offense = state.possession
        defense = away_team if offense == home_team else home_team
        offense_score = state.home_score if offense == home_team else state.away_score
        defense_score = state.away_score if offense == home_team else state.home_score
        start_field = model.start_field_positions[rng.randrange(len(model.start_field_positions))]
        bucket = _state_bucket(state.period, state.seconds_remaining_period, offense_score, defense_score, overtime=in_ot)
        outcome_probs = model.probabilities(offense, defense, start_yardline_100=start_field, state_bucket=bucket)
        outcome = _draw_named(outcome_probs, DRIVE_OUTCOMES, rng)

        conv = 0
        pts_off = pts_def = 0
        if outcome == "TD":
            conv = int(_draw_named(model.conversion_probabilities, (0, 1, 2), rng))
            pts_off = 6 + conv
        elif outcome == "FG":
            pts_off = 3
        elif outcome == "SAFETY":
            pts_def = 2
        elif outcome == "DEF_ST_SCORE":
            if not model.exceptional_score_points:
                raise ValueError("V2K_EXCEPTIONAL_SCORE_EMPIRICAL_SUPPORT_REQUIRED")
            pts_def = int(model.exceptional_score_points[rng.randrange(len(model.exceptional_score_points))])

        home, away = state.home_score, state.away_score
        if offense == home_team:
            home += pts_off
            away += pts_def
        else:
            away += pts_off
            home += pts_def

        path.append({
            "drive_index": state.drive_index,
            "period": 5 if in_ot else state.period,
            "seconds_remaining_period": 0 if in_ot else state.seconds_remaining_period,
            "offense": offense,
            "defense": defense,
            "start_yardline_100": start_field,
            "state_bucket": bucket,
            "outcome": outcome,
            "conversion_points": conv,
            "home_score": home,
            "away_score": away,
            "overtime": in_ot,
        })

        next_index = state.drive_index + 1
        period, seconds = _clock_state(next_index, regulation_drives)
        state = GameState(home_team, away_team, defense, home, away, 5 if in_ot else period, 0 if in_ot else seconds, next_index, in_ot)
        if in_ot and home != away and ot_drives >= 2:
            break

    return SimulationResult(
        home_score=state.home_score,
        away_score=state.away_score,
        margin=state.home_score - state.away_score,
        total=state.home_score + state.away_score,
        team_totals={home_team: state.home_score, away_team: state.away_score},
        path=tuple(path),
    )


AUTHORITY = {
    "model_p": False,
    "pricing": False,
    "promotion": False,
    "staking": False,
    "run_it": False,
    "official": False,
    "untouched_readout": False,
    "development_validation_scoring": False,
}
