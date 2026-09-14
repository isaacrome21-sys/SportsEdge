"""V2K attempt-0 football-native research core.

This module is intentionally evaluation-free. It provides deterministic mechanics for
source-normalized ordered drives, hierarchical partial pooling, and a sequential joint
score simulator. It does not run historical development/validation scoring and grants
no Model_P, pricing, promotion, staking, RUN IT, OFFICIAL, or untouched-readout authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from random import Random
from typing import Iterable, Mapping, Sequence

DRIVE_OUTCOMES = ("TD", "FG", "TURNOVER", "PUNT_OTHER", "SAFETY", "DEF_ST_SCORE")


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


@dataclass(frozen=True)
class HierarchicalStrength:
    league_baseline: Mapping[str, float]
    offense_effect: Mapping[str, Mapping[str, float]]
    defense_effect: Mapping[str, Mapping[str, float]]
    shrinkage_weight: Mapping[str, float]

    def probabilities(self, offense: str, defense: str) -> dict[str, float]:
        vals: dict[str, float] = {}
        for outcome in DRIVE_OUTCOMES:
            p = float(self.league_baseline[outcome])
            p += float(self.offense_effect.get(offense, {}).get(outcome, 0.0))
            p += float(self.defense_effect.get(defense, {}).get(outcome, 0.0))
            vals[outcome] = max(0.0, p)
        total = sum(vals.values())
        if not isfinite(total) or total <= 0:
            raise ValueError("V2K_DRIVE_PROBABILITY_INVALID")
        return {k: v / total for k, v in vals.items()}


def _variance(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean = sum(xs) / len(xs)
    return sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)


def fit_hierarchical_strength(rows: Sequence[DriveRow]) -> HierarchicalStrength:
    rows = normalize_drive_rows(rows)
    if not rows:
        raise ValueError("V2K_TRAINING_ROWS_REQUIRED")
    n = len(rows)
    league = {o: sum(r.outcome == o for r in rows) / n for o in DRIVE_OUTCOMES}
    by_off: dict[str, list[DriveRow]] = {}
    by_def: dict[str, list[DriveRow]] = {}
    for r in rows:
        by_off.setdefault(r.offense, []).append(r)
        by_def.setdefault(r.defense, []).append(r)

    raw_team_td = [sum(r.outcome == "TD" for r in group) / len(group) for group in by_off.values()]
    between = _variance(raw_team_td)
    within = max(league["TD"] * (1.0 - league["TD"]), 1e-9)

    shrinkage: dict[str, float] = {}
    off_effect: dict[str, dict[str, float]] = {}
    def_effect: dict[str, dict[str, float]] = {}

    for team, group in by_off.items():
        w = (len(group) * between) / (len(group) * between + within) if between > 0 else 0.0
        shrinkage[team] = w
        off_effect[team] = {o: w * ((sum(r.outcome == o for r in group) / len(group)) - league[o]) for o in DRIVE_OUTCOMES}
    for team, group in by_def.items():
        w = (len(group) * between) / (len(group) * between + within) if between > 0 else 0.0
        shrinkage.setdefault(team, w)
        def_effect[team] = {o: w * ((sum(r.outcome == o for r in group) / len(group)) - league[o]) for o in DRIVE_OUTCOMES}

    return HierarchicalStrength(league, off_effect, def_effect, shrinkage)


@dataclass(frozen=True)
class GameState:
    home_team: str
    away_team: str
    possession: str
    home_score: int = 0
    away_score: int = 0
    drive_index: int = 0


@dataclass(frozen=True)
class SimulationResult:
    home_score: int
    away_score: int
    margin: int
    total: int
    team_totals: Mapping[str, int]
    path: tuple[Mapping[str, object], ...]


def _draw(probs: Mapping[str, float], rng: Random) -> str:
    u = rng.random()
    c = 0.0
    for outcome in DRIVE_OUTCOMES:
        c += float(probs[outcome])
        if u <= c:
            return outcome
    return DRIVE_OUTCOMES[-1]


def simulate_joint_game(model: HierarchicalStrength, home_team: str, away_team: str, *, seed: int, max_regulation_drives: int = 24, max_overtime_drives: int = 8) -> SimulationResult:
    if home_team == away_team or max_regulation_drives <= 0 or max_overtime_drives <= 0:
        raise ValueError("V2K_SIMULATION_ARGUMENT_INVALID")
    rng = Random(seed)
    state = GameState(home_team, away_team, possession=home_team)
    path: list[Mapping[str, object]] = []
    ot_drives = 0

    while state.drive_index < max_regulation_drives or (state.home_score == state.away_score and ot_drives < max_overtime_drives):
        in_ot = state.drive_index >= max_regulation_drives
        if in_ot:
            ot_drives += 1
        offense = state.possession
        defense = away_team if offense == home_team else home_team
        outcome = _draw(model.probabilities(offense, defense), rng)
        conv = 0
        pts_off = pts_def = 0
        if outcome == "TD":
            conv = 1 if rng.random() < 0.94 else 0
            pts_off = 6 + conv
        elif outcome == "FG":
            pts_off = 3
        elif outcome == "SAFETY":
            pts_def = 2
        elif outcome == "DEF_ST_SCORE":
            pts_def = 7

        home, away = state.home_score, state.away_score
        if offense == home_team:
            home += pts_off
            away += pts_def
        else:
            away += pts_off
            home += pts_def
        path.append({"drive_index": state.drive_index, "offense": offense, "defense": defense, "outcome": outcome, "conversion_points": conv, "home_score": home, "away_score": away, "overtime": in_ot})
        state = GameState(home_team, away_team, possession=defense, home_score=home, away_score=away, drive_index=state.drive_index + 1)
        if in_ot and home != away and ot_drives >= 2:
            break

    return SimulationResult(home, away, home - away, home + away, {home_team: home, away_team: away}, tuple(path))


AUTHORITY = {"model_p": False, "pricing": False, "promotion": False, "staking": False, "run_it": False, "official": False, "untouched_readout": False, "development_validation_scoring": False}
