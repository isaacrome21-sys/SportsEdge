from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import random
from typing import Mapping, Sequence

from .mlb_pitcher_contract import normalize_starter_path

MLB_JOINT_PATH_VERSION = "MLB_DFS_JOINT_PATH_V1"
_ALLOWED_OUTCOMES = frozenset(
    {"K", "K_REACH", "OUT", "GIDP", "SAC_FLY", "1B", "2B", "3B", "HR", "BB", "HBP"}
)
_HIT_OUTCOMES = frozenset({"1B", "2B", "3B", "HR"})


class MlbJointPathError(ValueError):
    pass


def _canonical_hash(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(text.encode("utf-8")).hexdigest()


def _weighted_choice(rng: random.Random, probabilities: Mapping[str, float]) -> str:
    draw = rng.random()
    running = 0.0
    last = ""
    for key in sorted(probabilities):
        probability = float(probabilities[key])
        if probability <= 0.0:
            continue
        running += probability
        last = key
        if draw <= running + 1e-15:
            return key
    if last:
        return last
    raise MlbJointPathError("DFS_MLB_JOINT_EMPTY_PROBABILITY_SUPPORT")


def _weighted_int(rng: random.Random, probabilities: Mapping[int, float]) -> int:
    ordered = {str(int(key)): float(value) for key, value in probabilities.items()}
    return int(_weighted_choice(rng, ordered))


def _validate_probability_map(values: Mapping[object, float], *, label: str) -> None:
    if not values:
        raise MlbJointPathError(f"{label}:EMPTY")
    total = 0.0
    for key, value in values.items():
        probability = float(value)
        if probability < 0.0 or probability > 1.0:
            raise MlbJointPathError(f"{label}:PROBABILITY_INVALID:{key}:{probability}")
        total += probability
    if abs(total - 1.0) > 1e-9:
        raise MlbJointPathError(f"{label}:PROBABILITY_SUM:{total}")


@dataclass(frozen=True)
class PlateAppearanceProfile:
    outcome_probabilities: Mapping[str, float]
    pitch_count_probabilities: Mapping[int, float]
    source_id: str

    def __post_init__(self) -> None:
        unknown = set(self.outcome_probabilities) - _ALLOWED_OUTCOMES
        if unknown:
            raise MlbJointPathError("DFS_MLB_JOINT_OUTCOME_UNSUPPORTED:" + ",".join(sorted(unknown)))
        _validate_probability_map(self.outcome_probabilities, label="DFS_MLB_JOINT_OUTCOME")
        _validate_probability_map(self.pitch_count_probabilities, label="DFS_MLB_JOINT_PITCH_COUNT")
        if any(int(value) < 1 for value in self.pitch_count_probabilities):
            raise MlbJointPathError("DFS_MLB_JOINT_PITCH_COUNT_LT_ONE")
        if not str(self.source_id).strip():
            raise MlbJointPathError("DFS_MLB_JOINT_PROFILE_SOURCE_REQUIRED")

    def sample(self, rng: random.Random) -> tuple[str, int]:
        return (
            _weighted_choice(rng, self.outcome_probabilities),
            _weighted_int(rng, self.pitch_count_probabilities),
        )

    def identity(self) -> dict[str, object]:
        return {
            "outcomes": {str(k): float(v) for k, v in sorted(self.outcome_probabilities.items())},
            "pitches": {str(int(k)): float(v) for k, v in sorted(self.pitch_count_probabilities.items())},
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class HookHazardSurface:
    pitch_count_upper_bounds: tuple[int, ...]
    runs_allowed_upper_bounds: tuple[int, ...]
    remove_probabilities: tuple[tuple[float, ...], ...]
    source_id: str

    def __post_init__(self) -> None:
        if not self.pitch_count_upper_bounds or not self.runs_allowed_upper_bounds:
            raise MlbJointPathError("DFS_MLB_HOOK_BINS_EMPTY")
        if tuple(sorted(self.pitch_count_upper_bounds)) != self.pitch_count_upper_bounds:
            raise MlbJointPathError("DFS_MLB_HOOK_PITCH_BINS_UNSORTED")
        if tuple(sorted(self.runs_allowed_upper_bounds)) != self.runs_allowed_upper_bounds:
            raise MlbJointPathError("DFS_MLB_HOOK_RUN_BINS_UNSORTED")
        if self.pitch_count_upper_bounds[-1] < 200 or self.runs_allowed_upper_bounds[-1] < 20:
            raise MlbJointPathError("DFS_MLB_HOOK_BINS_INCOMPLETE_SUPPORT")
        if len(self.remove_probabilities) != len(self.pitch_count_upper_bounds):
            raise MlbJointPathError("DFS_MLB_HOOK_MATRIX_PITCH_SHAPE")
        for row in self.remove_probabilities:
            if len(row) != len(self.runs_allowed_upper_bounds):
                raise MlbJointPathError("DFS_MLB_HOOK_MATRIX_RUN_SHAPE")
            if any(float(value) < 0.0 or float(value) > 1.0 for value in row):
                raise MlbJointPathError("DFS_MLB_HOOK_PROBABILITY_INVALID")
        if not str(self.source_id).strip():
            raise MlbJointPathError("DFS_MLB_HOOK_SOURCE_REQUIRED")

    @staticmethod
    def _bucket(value: int, upper_bounds: tuple[int, ...]) -> int:
        for index, upper in enumerate(upper_bounds):
            if value <= upper:
                return index
        raise MlbJointPathError(f"DFS_MLB_HOOK_STATE_OUT_OF_SUPPORT:{value}")

    def removal_probability(self, *, pitch_count: int, runs_allowed: int) -> float:
        pitch_index = self._bucket(int(pitch_count), self.pitch_count_upper_bounds)
        runs_index = self._bucket(int(runs_allowed), self.runs_allowed_upper_bounds)
        return float(self.remove_probabilities[pitch_index][runs_index])

    def identity(self) -> dict[str, object]:
        return {
            "pitch_count_upper_bounds": self.pitch_count_upper_bounds,
            "runs_allowed_upper_bounds": self.runs_allowed_upper_bounds,
            "remove_probabilities": self.remove_probabilities,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class BaserunningProfile:
    single_second_scores: float
    single_first_to_third: float
    double_first_scores: float
    source_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("single_second_scores", self.single_second_scores),
            ("single_first_to_third", self.single_first_to_third),
            ("double_first_scores", self.double_first_scores),
        ):
            if float(value) < 0.0 or float(value) > 1.0:
                raise MlbJointPathError(f"DFS_MLB_BASERUN_PROBABILITY_INVALID:{name}")
        if not str(self.source_id).strip():
            raise MlbJointPathError("DFS_MLB_BASERUN_SOURCE_REQUIRED")

    def identity(self) -> dict[str, object]:
        return {
            "single_second_scores": float(self.single_second_scores),
            "single_first_to_third": float(self.single_first_to_third),
            "double_first_scores": float(self.double_first_scores),
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class HitterPathInput:
    player_id: str
    starter_profile: PlateAppearanceProfile
    bullpen_profile: PlateAppearanceProfile

    def __post_init__(self) -> None:
        if not str(self.player_id).strip():
            raise MlbJointPathError("DFS_MLB_HITTER_ID_REQUIRED")


@dataclass(frozen=True)
class TeamPathInput:
    team: str
    lineup: tuple[HitterPathInput, ...]
    starter_player_id: str
    hook_surface: HookHazardSurface

    def __post_init__(self) -> None:
        if len(self.lineup) != 9:
            raise MlbJointPathError(f"DFS_MLB_LINEUP_MUST_HAVE_NINE:{self.team}:{len(self.lineup)}")
        ids = [h.player_id for h in self.lineup]
        if len(set(ids)) != 9:
            raise MlbJointPathError(f"DFS_MLB_LINEUP_DUPLICATE_PLAYER:{self.team}")
        if not str(self.starter_player_id).strip():
            raise MlbJointPathError(f"DFS_MLB_STARTER_ID_REQUIRED:{self.team}")

    def identity(self) -> dict[str, object]:
        return {
            "team": self.team,
            "starter_player_id": self.starter_player_id,
            "hook_surface": self.hook_surface.identity(),
            "lineup": [
                {
                    "player_id": hitter.player_id,
                    "starter_profile": hitter.starter_profile.identity(),
                    "bullpen_profile": hitter.bullpen_profile.identity(),
                }
                for hitter in self.lineup
            ],
        }


@dataclass(frozen=True)
class MlbGamePathInput:
    game_id: str
    away: TeamPathInput
    home: TeamPathInput
    baserunning: BaserunningProfile
    updated_at: datetime
    source_id: str

    def __post_init__(self) -> None:
        if self.updated_at.tzinfo is None:
            raise MlbJointPathError("DFS_MLB_JOINT_UPDATED_AT_MUST_BE_AWARE")
        if self.away.team == self.home.team:
            raise MlbJointPathError("DFS_MLB_JOINT_TEAM_IDENTITY_COLLISION")
        all_ids = [h.player_id for h in self.away.lineup + self.home.lineup]
        all_ids.extend([self.away.starter_player_id, self.home.starter_player_id])
        if len(set(all_ids)) != 20:
            raise MlbJointPathError("DFS_MLB_JOINT_PLAYER_ID_COLLISION")
        if not str(self.game_id).strip() or not str(self.source_id).strip():
            raise MlbJointPathError("DFS_MLB_JOINT_SOURCE_IDENTITY_REQUIRED")

    def identity(self) -> dict[str, object]:
        return {
            "version": MLB_JOINT_PATH_VERSION,
            "game_id": self.game_id,
            "away": self.away.identity(),
            "home": self.home.identity(),
            "baserunning": self.baserunning.identity(),
            "updated_at": self.updated_at.astimezone(timezone.utc).isoformat(),
            "source_id": self.source_id,
        }


@dataclass
class _Runner:
    player_id: str
    responsibility: str
    earned: bool = True


@dataclass
class _HitterStats:
    singles: int = 0
    doubles: int = 0
    triples: int = 0
    home_runs: int = 0
    rbi: int = 0
    runs: int = 0
    walks: int = 0
    hbp: int = 0
    stolen_bases: int = 0

    def sample(self) -> dict[str, float]:
        return {
            "singles": float(self.singles),
            "doubles": float(self.doubles),
            "triples": float(self.triples),
            "home_runs": float(self.home_runs),
            "rbi": float(self.rbi),
            "runs": float(self.runs),
            "walks": float(self.walks),
            "hbp": float(self.hbp),
            "stolen_bases": float(self.stolen_bases),
        }


@dataclass
class _StarterState:
    team: str
    player_id: str
    active: bool = True
    pending_hook: bool = False
    outs: int = 0
    batters_faced: int = 0
    pitch_count: int = 0
    strikeouts: int = 0
    earned_runs: int = 0
    hits_allowed: int = 0
    walks_allowed: int = 0
    hbp_allowed: int = 0
    bullpen_hits_allowed: int = 0
    lead_at_exit: bool = False
    lead_preserved_to_final: bool = False
    lead_tracking_active: bool = False


@dataclass
class _GameState:
    away_score: int = 0
    home_score: int = 0
    away_hits: int = 0
    home_hits: int = 0
    next_batter: dict[str, int] = field(default_factory=lambda: {"AWAY": 0, "HOME": 0})

    def score_for(self, side: str) -> int:
        return self.away_score if side == "AWAY" else self.home_score

    def score_against(self, side: str) -> int:
        return self.home_score if side == "AWAY" else self.away_score

    def add_run(self, side: str) -> None:
        if side == "AWAY":
            self.away_score += 1
        else:
            self.home_score += 1

    def add_hit(self, side: str) -> None:
        if side == "AWAY":
            self.away_hits += 1
        else:
            self.home_hits += 1

    def team_hits(self, side: str) -> int:
        return self.away_hits if side == "AWAY" else self.home_hits


@dataclass(frozen=True)
class MlbJointPathResult:
    path_set_id: str
    path_count: int
    snapshot: dict[str, object]


def _defense_side(offense_side: str) -> str:
    return "HOME" if offense_side == "AWAY" else "AWAY"


def _team_input(game: MlbGamePathInput, side: str) -> TeamPathInput:
    return game.away if side == "AWAY" else game.home


def _starter_state(states: Mapping[str, _StarterState], defense_side: str) -> _StarterState:
    return states[defense_side]


def _is_leading(game_state: _GameState, side: str) -> bool:
    return game_state.score_for(side) > game_state.score_against(side)


def _refresh_preserved_leads(game_state: _GameState, starters: Mapping[str, _StarterState]) -> None:
    for side, starter in starters.items():
        if starter.lead_tracking_active and not _is_leading(game_state, side):
            starter.lead_preserved_to_final = False
            starter.lead_tracking_active = False


def _record_exit_lead(game_state: _GameState, side: str, starter: _StarterState) -> None:
    starter.lead_at_exit = _is_leading(game_state, side)
    starter.lead_preserved_to_final = starter.lead_at_exit
    starter.lead_tracking_active = starter.lead_at_exit


def _activate_pending_bullpen(game_state: _GameState, side: str, starter: _StarterState) -> None:
    if starter.active and starter.pending_hook:
        starter.active = False
        starter.pending_hook = False
        _record_exit_lead(game_state, side, starter)


def _score_runner(
    runner: _Runner,
    *,
    offense_side: str,
    game_state: _GameState,
    hitters: Mapping[str, _HitterStats],
    defense_starter: _StarterState,
) -> None:
    game_state.add_run(offense_side)
    hitters[runner.player_id].runs += 1
    if runner.responsibility == "STARTER" and runner.earned:
        defense_starter.earned_runs += 1


def _force_walk(
    bases: list[_Runner | None],
    batter: _Runner,
    *,
    offense_side: str,
    game_state: _GameState,
    hitters: Mapping[str, _HitterStats],
    defense_starter: _StarterState,
) -> int:
    rbi = 0
    if bases[0] is None:
        bases[0] = batter
        return rbi
    if bases[1] is None:
        bases[1] = bases[0]
        bases[0] = batter
        return rbi
    if bases[2] is None:
        bases[2] = bases[1]
        bases[1] = bases[0]
        bases[0] = batter
        return rbi
    assert bases[2] is not None
    _score_runner(
        bases[2],
        offense_side=offense_side,
        game_state=game_state,
        hitters=hitters,
        defense_starter=defense_starter,
    )
    rbi += 1
    bases[2] = bases[1]
    bases[1] = bases[0]
    bases[0] = batter
    return rbi


def _hit_single(
    bases: list[_Runner | None],
    batter: _Runner,
    *,
    rng: random.Random,
    baserunning: BaserunningProfile,
    offense_side: str,
    game_state: _GameState,
    hitters: Mapping[str, _HitterStats],
    defense_starter: _StarterState,
) -> int:
    rbi = 0
    runner1, runner2, runner3 = bases
    bases[:] = [None, None, None]
    if runner3 is not None:
        _score_runner(runner3, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=defense_starter)
        rbi += 1
    second_scores = runner2 is not None and rng.random() < baserunning.single_second_scores
    if runner2 is not None:
        if second_scores:
            _score_runner(runner2, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=defense_starter)
            rbi += 1
        else:
            bases[2] = runner2
    if runner1 is not None:
        can_take_third = bases[2] is None
        if can_take_third and rng.random() < baserunning.single_first_to_third:
            bases[2] = runner1
        else:
            bases[1] = runner1
    bases[0] = batter
    return rbi


def _hit_double(
    bases: list[_Runner | None],
    batter: _Runner,
    *,
    rng: random.Random,
    baserunning: BaserunningProfile,
    offense_side: str,
    game_state: _GameState,
    hitters: Mapping[str, _HitterStats],
    defense_starter: _StarterState,
) -> int:
    rbi = 0
    runner1, runner2, runner3 = bases
    bases[:] = [None, batter, None]
    for runner in (runner3, runner2):
        if runner is not None:
            _score_runner(runner, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=defense_starter)
            rbi += 1
    if runner1 is not None:
        if rng.random() < baserunning.double_first_scores:
            _score_runner(runner1, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=defense_starter)
            rbi += 1
        else:
            bases[2] = runner1
    return rbi


def _hit_triple_or_homer(
    bases: list[_Runner | None],
    batter: _Runner,
    *,
    home_run: bool,
    offense_side: str,
    game_state: _GameState,
    hitters: Mapping[str, _HitterStats],
    defense_starter: _StarterState,
) -> int:
    rbi = 0
    for runner in list(bases):
        if runner is not None:
            _score_runner(runner, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=defense_starter)
            rbi += 1
    bases[:] = [None, None, None]
    if home_run:
        _score_runner(batter, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=defense_starter)
        rbi += 1
    else:
        bases[2] = batter
    return rbi


def _simulate_half_inning(
    *,
    game: MlbGamePathInput,
    game_state: _GameState,
    starters: dict[str, _StarterState],
    hitters: dict[str, _HitterStats],
    offense_side: str,
    inning: int,
    rng: random.Random,
    walkoff_enabled: bool,
) -> bool:
    offense = _team_input(game, offense_side)
    defense_side = _defense_side(offense_side)
    defense = _team_input(game, defense_side)
    starter = _starter_state(starters, defense_side)
    _activate_pending_bullpen(game_state, defense_side, starter)

    outs = 0
    bases: list[_Runner | None] = [None, None, None]
    if inning >= 10:
        ghost_index = (game_state.next_batter[offense_side] - 1) % 9
        ghost_id = offense.lineup[ghost_index].player_id
        bases[1] = _Runner(ghost_id, "GHOST", earned=False)

    while outs < 3:
        batting_index = game_state.next_batter[offense_side] % 9
        hitter = offense.lineup[batting_index]
        game_state.next_batter[offense_side] = (batting_index + 1) % 9
        pitcher_role = "STARTER" if starter.active else "BULLPEN"
        profile = hitter.starter_profile if starter.active else hitter.bullpen_profile
        outcome, pitches = profile.sample(rng)
        runner = _Runner(hitter.player_id, pitcher_role, earned=True)

        if starter.active:
            starter.batters_faced += 1
            starter.pitch_count += int(pitches)

        batter_stats = hitters[hitter.player_id]
        if outcome in _HIT_OUTCOMES:
            game_state.add_hit(offense_side)
            if starter.active:
                starter.hits_allowed += 1
            else:
                starter.bullpen_hits_allowed += 1

        if outcome == "K":
            if starter.active:
                starter.strikeouts += 1
                starter.outs += 1
            outs += 1
        elif outcome == "K_REACH":
            if starter.active:
                starter.strikeouts += 1
            _force_walk(bases, runner, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
        elif outcome == "OUT":
            if starter.active:
                starter.outs += 1
            outs += 1
        elif outcome == "GIDP":
            gained = 1
            if bases[0] is not None and outs <= 1:
                bases[0] = None
                gained = 2
            gained = min(gained, 3 - outs)
            outs += gained
            if starter.active:
                starter.outs += gained
        elif outcome == "SAC_FLY":
            if starter.active:
                starter.outs += 1
            outs += 1
            if bases[2] is not None and outs <= 3:
                scoring = bases[2]
                bases[2] = None
                assert scoring is not None
                _score_runner(scoring, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
                batter_stats.rbi += 1
        elif outcome == "BB":
            if starter.active:
                starter.walks_allowed += 1
            batter_stats.walks += 1
            batter_stats.rbi += _force_walk(bases, runner, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
        elif outcome == "HBP":
            if starter.active:
                starter.hbp_allowed += 1
            batter_stats.hbp += 1
            batter_stats.rbi += _force_walk(bases, runner, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
        elif outcome == "1B":
            batter_stats.singles += 1
            batter_stats.rbi += _hit_single(bases, runner, rng=rng, baserunning=game.baserunning, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
        elif outcome == "2B":
            batter_stats.doubles += 1
            batter_stats.rbi += _hit_double(bases, runner, rng=rng, baserunning=game.baserunning, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
        elif outcome == "3B":
            batter_stats.triples += 1
            batter_stats.rbi += _hit_triple_or_homer(bases, runner, home_run=False, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
        elif outcome == "HR":
            batter_stats.home_runs += 1
            batter_stats.rbi += _hit_triple_or_homer(bases, runner, home_run=True, offense_side=offense_side, game_state=game_state, hitters=hitters, defense_starter=starter)
        else:
            raise MlbJointPathError(f"DFS_MLB_JOINT_OUTCOME_UNHANDLED:{outcome}")

        _refresh_preserved_leads(game_state, starters)
        if walkoff_enabled and offense_side == "HOME" and game_state.home_score > game_state.away_score:
            return True

        if starter.active and not starter.pending_hook:
            remove_probability = defense.hook_surface.removal_probability(
                pitch_count=starter.pitch_count,
                runs_allowed=starter.earned_runs,
            )
            if rng.random() < remove_probability:
                if outs >= 3:
                    starter.pending_hook = True
                else:
                    starter.active = False
                    _record_exit_lead(game_state, defense_side, starter)

    return False


def _starter_sample(
    *,
    starter: _StarterState,
    defense_side: str,
    game_state: _GameState,
) -> dict[str, float]:
    if starter.active:
        starter.pending_hook = False
        _record_exit_lead(game_state, defense_side, starter)
    opponent_side = _defense_side(defense_side)
    opponent_hits = game_state.team_hits(opponent_side)
    complete_game = float(starter.active and starter.outs >= 27)
    cg_shutout = float(complete_game == 1.0 and game_state.score_against(defense_side) == 0)
    no_hitter = float(complete_game == 1.0 and opponent_hits == 0)
    sample = {
        "outs": float(starter.outs),
        "strikeouts": float(starter.strikeouts),
        "earned_runs": float(starter.earned_runs),
        "hits_allowed": float(starter.hits_allowed),
        "walks_allowed": float(starter.walks_allowed),
        "hbp_allowed": float(starter.hbp_allowed),
        "starter_exit_batters_faced": float(starter.batters_faced),
        "starter_exit_pitch_count": float(starter.pitch_count),
        "starter_scoped_events": 1.0,
        "hook_endogenous_to_path": 1.0,
        "hook_decision_batter_by_batter": 1.0,
        "hook_conditioned_on_pitch_count": 1.0,
        "hook_conditioned_on_runs_allowed": 1.0,
        "bullpen_remainder_routed": 1.0,
        "bullpen_hits_allowed": float(starter.bullpen_hits_allowed),
        "opponent_team_hits": float(opponent_hits),
        "game_simulated_to_final": 1.0,
        "lead_at_exit": float(starter.lead_at_exit),
        "lead_preserved_to_final": float(starter.lead_preserved_to_final),
        "complete_game_probability": complete_game,
        "cg_shutout_probability": cg_shutout,
        "no_hitter_probability": no_hitter,
    }
    return normalize_starter_path(sample)


def _simulate_one(game: MlbGamePathInput, *, seed: int) -> dict[str, dict[str, float]]:
    rng = random.Random(seed)
    state = _GameState()
    starters = {
        "AWAY": _StarterState(team=game.away.team, player_id=game.away.starter_player_id),
        "HOME": _StarterState(team=game.home.team, player_id=game.home.starter_player_id),
    }
    hitters = {
        hitter.player_id: _HitterStats()
        for hitter in game.away.lineup + game.home.lineup
    }

    inning = 1
    plate_appearance_guard = 0
    while True:
        before_next = sum(state.next_batter.values())
        _simulate_half_inning(
            game=game,
            game_state=state,
            starters=starters,
            hitters=hitters,
            offense_side="AWAY",
            inning=inning,
            rng=rng,
            walkoff_enabled=False,
        )
        plate_appearance_guard += (sum(state.next_batter.values()) - before_next) % 18
        if inning >= 9 and state.home_score > state.away_score:
            break

        before_next = sum(state.next_batter.values())
        walkoff = _simulate_half_inning(
            game=game,
            game_state=state,
            starters=starters,
            hitters=hitters,
            offense_side="HOME",
            inning=inning,
            rng=rng,
            walkoff_enabled=inning >= 9,
        )
        plate_appearance_guard += (sum(state.next_batter.values()) - before_next) % 18
        if walkoff:
            break
        if inning >= 9 and state.home_score != state.away_score:
            break
        inning += 1
        if inning > 30:
            raise MlbJointPathError("DFS_MLB_JOINT_GAME_NOT_TERMINATED_BY_30_INNINGS")

    _refresh_preserved_leads(state, starters)
    result = {pid: stats.sample() for pid, stats in hitters.items()}
    result[game.away.starter_player_id] = _starter_sample(
        starter=starters["AWAY"], defense_side="AWAY", game_state=state
    )
    result[game.home.starter_player_id] = _starter_sample(
        starter=starters["HOME"], defense_side="HOME", game_state=state
    )
    return result


def simulate_mlb_joint_paths(
    game: MlbGamePathInput,
    *,
    path_count: int,
    seed: int,
) -> MlbJointPathResult:
    if path_count < 1:
        raise MlbJointPathError("DFS_MLB_JOINT_PATH_COUNT_INVALID")
    identity = {
        "version": MLB_JOINT_PATH_VERSION,
        "game": game.identity(),
        "path_count": int(path_count),
        "seed": int(seed),
    }
    path_set_id = _canonical_hash(identity)
    player_ids = [h.player_id for h in game.away.lineup + game.home.lineup]
    player_ids.extend([game.away.starter_player_id, game.home.starter_player_id])
    rows: dict[str, list[dict[str, float]]] = {pid: [] for pid in player_ids}

    for path_index in range(path_count):
        path_seed = int.from_bytes(
            sha256(f"{path_set_id}:{path_index}".encode("utf-8")).digest()[:8],
            "big",
        )
        path = _simulate_one(game, seed=path_seed)
        for player_id in player_ids:
            rows[player_id].append(path[player_id])

    team_by_player = {
        **{h.player_id: game.away.team for h in game.away.lineup},
        **{h.player_id: game.home.team for h in game.home.lineup},
        game.away.starter_player_id: game.away.team,
        game.home.starter_player_id: game.home.team,
    }
    snapshot = {
        "version": MLB_JOINT_PATH_VERSION,
        "source": "SPORTSEDGE_MLB_ENDOGENOUS_JOINT_PATHS",
        "source_id": game.source_id,
        "updated_at": game.updated_at.astimezone(timezone.utc).isoformat(),
        "path_set_id": path_set_id,
        "path_count": int(path_count),
        "game_id": game.game_id,
        "players": [
            {
                "player_id": player_id,
                "team": team_by_player[player_id],
                "path_set_id": path_set_id,
                "source": "SPORTSEDGE_MLB_ENDOGENOUS_JOINT_PATHS",
                "updated_at": game.updated_at.astimezone(timezone.utc).isoformat(),
                "samples": rows[player_id],
            }
            for player_id in player_ids
        ],
    }
    return MlbJointPathResult(
        path_set_id=path_set_id,
        path_count=path_count,
        snapshot=snapshot,
    )
