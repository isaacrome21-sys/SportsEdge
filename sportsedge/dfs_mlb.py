"""SportsEdge MLB DFS engine.

Clean-room implementation inspired by public DFS optimizer/simulator patterns while
keeping SportsEdge projections as the source of truth.  No external repository code
is copied here.  The engine is dependency-light so it can run in the existing repo.

Primary goals:
- DraftKings-style MLB roster legality and salary constraints.
- Projection + ownership/leverage-aware lineup construction.
- Team/game correlated Monte Carlo instead of independent player draws.
- Portfolio uniqueness and exposure controls.
- Reproducible output from a fixed seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import inf
from random import Random
from typing import Iterable, Mapping, Sequence


DK_MLB_SLOTS: tuple[str, ...] = (
    "P",
    "P",
    "C/1B",
    "2B",
    "3B",
    "SS",
    "OF",
    "OF",
    "OF",
)


@dataclass(frozen=True)
class PlayerProjection:
    player_id: str
    name: str
    team: str
    opponent: str
    positions: tuple[str, ...]
    salary: int
    projection: float
    stdev: float
    ownership: float = 0.0
    batting_order: int | None = None
    is_pitcher: bool = False
    game_id: str | None = None

    def eligible_for(self, slot: str) -> bool:
        if slot == "C/1B":
            return "C" in self.positions or "1B" in self.positions or "C/1B" in self.positions
        return slot in self.positions


@dataclass(frozen=True)
class DFSConfig:
    salary_cap: int = 50_000
    min_salary: int = 0
    slots: tuple[str, ...] = DK_MLB_SLOTS
    max_hitters_per_team: int = 5
    forbid_hitter_vs_pitcher: bool = True
    min_unique_players: int = 2
    leverage_weight: float = 0.12
    salary_efficiency_weight: float = 0.02
    randomness: float = 0.08
    max_player_exposure: float = 0.70
    max_lineups: int = 20


@dataclass(frozen=True)
class Lineup:
    players: tuple[PlayerProjection, ...]
    slots: tuple[str, ...]
    objective: float

    @property
    def salary(self) -> int:
        return sum(p.salary for p in self.players)

    @property
    def projection(self) -> float:
        return sum(p.projection for p in self.players)

    @property
    def ownership_sum(self) -> float:
        return sum(p.ownership for p in self.players)

    @property
    def player_ids(self) -> frozenset[str]:
        return frozenset(p.player_id for p in self.players)

    def hitters_by_team(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self.players:
            if not p.is_pitcher:
                counts[p.team] = counts.get(p.team, 0) + 1
        return counts


@dataclass
class SimulatedLineupResult:
    lineup: Lineup
    mean: float
    median: float
    p90: float
    p95: float
    boom_rate: float
    top_lineup_rate: float


@dataclass
class PortfolioResult:
    lineups: list[Lineup]
    simulation: list[SimulatedLineupResult] = field(default_factory=list)


def _player_objective(player: PlayerProjection, config: DFSConfig, rng: Random) -> float:
    # Ownership is expected as a 0-1 fraction.  Lower ownership improves leverage.
    leverage = max(0.0, 1.0 - player.ownership)
    salary_eff = player.projection / max(player.salary / 1000.0, 1.0)
    jitter = rng.uniform(-config.randomness, config.randomness) * max(player.stdev, 1.0)
    return (
        player.projection
        + config.leverage_weight * leverage * player.projection
        + config.salary_efficiency_weight * salary_eff
        + jitter
    )


def _lineup_conflict(selected: Sequence[PlayerProjection], candidate: PlayerProjection, config: DFSConfig) -> bool:
    if candidate.player_id in {p.player_id for p in selected}:
        return True

    if not candidate.is_pitcher:
        same_team_hitters = sum(1 for p in selected if not p.is_pitcher and p.team == candidate.team)
        if same_team_hitters >= config.max_hitters_per_team:
            return True

    if config.forbid_hitter_vs_pitcher:
        for p in selected:
            if p.is_pitcher and not candidate.is_pitcher and candidate.team == p.opponent:
                return True
            if candidate.is_pitcher and not p.is_pitcher and p.team == candidate.opponent:
                return True

    return False


def validate_lineup(lineup: Lineup, config: DFSConfig) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    if len(lineup.players) != len(config.slots):
        errors.append("ROSTER_SIZE")
    if lineup.salary > config.salary_cap:
        errors.append("SALARY_CAP")
    if lineup.salary < config.min_salary:
        errors.append("MIN_SALARY")
    if len(lineup.player_ids) != len(lineup.players):
        errors.append("DUPLICATE_PLAYER")

    for slot, player in zip(lineup.slots, lineup.players):
        if not player.eligible_for(slot):
            errors.append(f"POSITION:{slot}:{player.player_id}")

    for team, count in lineup.hitters_by_team().items():
        if count > config.max_hitters_per_team:
            errors.append(f"TEAM_LIMIT:{team}")

    if config.forbid_hitter_vs_pitcher:
        pitchers = [p for p in lineup.players if p.is_pitcher]
        hitters = [p for p in lineup.players if not p.is_pitcher]
        for pitcher in pitchers:
            if any(h.team == pitcher.opponent for h in hitters):
                errors.append(f"HITTER_VS_PITCHER:{pitcher.player_id}")

    return (not errors, tuple(errors))


def _build_single_lineup(
    players: Sequence[PlayerProjection],
    config: DFSConfig,
    rng: Random,
    exposure_counts: Mapping[str, int],
    lineup_index: int,
) -> Lineup | None:
    # Fail-closed candidate pools by slot and then use a bounded DFS search.
    slot_candidates: list[list[PlayerProjection]] = []
    for slot in config.slots:
        candidates = [p for p in players if p.eligible_for(slot)]
        candidates.sort(key=lambda p: _player_objective(p, config, rng), reverse=True)
        # Keep search tractable while retaining meaningful alternatives.
        slot_candidates.append(candidates[:32])

    best_players: list[PlayerProjection] | None = None
    best_obj = -inf

    def search(slot_idx: int, selected: list[PlayerProjection], salary: int, objective: float) -> None:
        nonlocal best_players, best_obj
        if salary > config.salary_cap:
            return
        if slot_idx == len(config.slots):
            if salary < config.min_salary:
                return
            if objective > best_obj:
                best_obj = objective
                best_players = list(selected)
            return

        # Cheap optimistic pruning using the best remaining raw projections.
        optimistic = objective
        for j in range(slot_idx, len(config.slots)):
            if slot_candidates[j]:
                optimistic += max(p.projection for p in slot_candidates[j]) * 1.25
        if optimistic < best_obj:
            return

        for candidate in slot_candidates[slot_idx]:
            if _lineup_conflict(selected, candidate, config):
                continue
            # Exposure cap is applied prospectively after at least one lineup exists.
            if lineup_index > 0:
                used = exposure_counts.get(candidate.player_id, 0)
                projected_exposure = (used + 1) / (lineup_index + 1)
                if projected_exposure > config.max_player_exposure:
                    continue
            selected.append(candidate)
            search(
                slot_idx + 1,
                selected,
                salary + candidate.salary,
                objective + _player_objective(candidate, config, rng),
            )
            selected.pop()

    search(0, [], 0, 0.0)
    if best_players is None:
        return None
    lineup = Lineup(tuple(best_players), config.slots, best_obj)
    valid, _ = validate_lineup(lineup, config)
    return lineup if valid else None


def _unique_enough(candidate: Lineup, existing: Sequence[Lineup], min_unique: int) -> bool:
    for lineup in existing:
        overlap = len(candidate.player_ids & lineup.player_ids)
        unique = len(candidate.players) - overlap
        if unique < min_unique:
            return False
    return True


def generate_lineups(
    players: Iterable[PlayerProjection],
    config: DFSConfig | None = None,
    *,
    seed: int = 20260815,
) -> list[Lineup]:
    """Generate a diversified DFS portfolio from SportsEdge player projections."""
    cfg = config or DFSConfig()
    pool = tuple(players)
    rng = Random(seed)
    lineups: list[Lineup] = []
    exposure_counts: dict[str, int] = {}

    # Multiple attempts per requested lineup allow randomness + uniqueness to work.
    for lineup_index in range(cfg.max_lineups):
        accepted: Lineup | None = None
        for _ in range(40):
            candidate = _build_single_lineup(pool, cfg, rng, exposure_counts, lineup_index)
            if candidate is None:
                continue
            if not _unique_enough(candidate, lineups, cfg.min_unique_players):
                continue
            accepted = candidate
            break
        if accepted is None:
            break
        lineups.append(accepted)
        for p in accepted.players:
            exposure_counts[p.player_id] = exposure_counts.get(p.player_id, 0) + 1

    return lineups


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * q))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def simulate_portfolio(
    lineups: Sequence[Lineup],
    *,
    n_sims: int = 20_000,
    seed: int = 20260815,
    team_corr: float = 0.28,
    game_corr: float = 0.14,
    boom_multiplier: float = 1.45,
) -> list[SimulatedLineupResult]:
    """Run a correlated Monte Carlo for lineup fantasy-point distributions.

    Hitters from the same team share a latent team factor; all players in the same
    game share a smaller game factor. Pitchers receive the inverse opponent-team
    factor, producing the desired negative pitcher-vs-opposing-offense relation.
    This is intentionally a DFS distribution layer, not a replacement for the
    underlying SportsEdge stat projection model.
    """
    if not lineups:
        return []
    rng = Random(seed)
    all_players: dict[str, PlayerProjection] = {}
    for lineup in lineups:
        for p in lineup.players:
            all_players[p.player_id] = p

    teams = sorted({p.team for p in all_players.values()})
    games = sorted({p.game_id or "|".join(sorted((p.team, p.opponent))) for p in all_players.values()})
    lineup_scores: list[list[float]] = [[] for _ in lineups]
    top_counts = [0 for _ in lineups]

    for _ in range(n_sims):
        team_latent = {team: rng.gauss(0.0, 1.0) for team in teams}
        game_latent = {game: rng.gauss(0.0, 1.0) for game in games}
        player_scores: dict[str, float] = {}

        for pid, p in all_players.items():
            game = p.game_id or "|".join(sorted((p.team, p.opponent)))
            residual_scale = max(0.0, 1.0 - team_corr - game_corr) ** 0.5
            if p.is_pitcher:
                shared = -team_corr * team_latent.get(p.opponent, 0.0) + game_corr * game_latent[game]
            else:
                shared = team_corr * team_latent[p.team] + game_corr * game_latent[game]
            z = shared + residual_scale * rng.gauss(0.0, 1.0)
            player_scores[pid] = max(0.0, p.projection + p.stdev * z)

        sim_scores = [sum(player_scores[p.player_id] for p in lineup.players) for lineup in lineups]
        best = max(sim_scores)
        for i, score in enumerate(sim_scores):
            lineup_scores[i].append(score)
            if score == best:
                top_counts[i] += 1

    results: list[SimulatedLineupResult] = []
    for i, lineup in enumerate(lineups):
        scores = lineup_scores[i]
        mean = sum(scores) / len(scores)
        median = _percentile(scores, 0.50)
        p90 = _percentile(scores, 0.90)
        p95 = _percentile(scores, 0.95)
        boom_threshold = lineup.projection * boom_multiplier
        boom_rate = sum(1 for s in scores if s >= boom_threshold) / len(scores)
        results.append(
            SimulatedLineupResult(
                lineup=lineup,
                mean=mean,
                median=median,
                p90=p90,
                p95=p95,
                boom_rate=boom_rate,
                top_lineup_rate=top_counts[i] / n_sims,
            )
        )
    results.sort(key=lambda r: (r.top_lineup_rate, r.p95, r.mean), reverse=True)
    return results


def build_portfolio(
    players: Iterable[PlayerProjection],
    config: DFSConfig | None = None,
    *,
    seed: int = 20260815,
    n_sims: int = 20_000,
) -> PortfolioResult:
    lineups = generate_lineups(players, config, seed=seed)
    simulation = simulate_portfolio(lineups, n_sims=n_sims, seed=seed)
    return PortfolioResult(lineups=lineups, simulation=simulation)
