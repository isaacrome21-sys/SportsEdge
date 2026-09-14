from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import fmean
from typing import Iterable

from .field import GeneratedField, lineup_key
from .score_paths import AlignedScorePaths
from .types import DKPlayer


@dataclass(frozen=True)
class ContestStructure:
    field_size: int
    entry_fee: float
    payouts: tuple[float, ...]
    name: str = ""
    version: str = "DFS_CONTEST_V1"

    def validate(self) -> None:
        if self.field_size < 2:
            raise ValueError("DFS_CONTEST_FIELD_SIZE_INVALID")
        if self.entry_fee < 0 or not math.isfinite(self.entry_fee):
            raise ValueError("DFS_CONTEST_ENTRY_FEE_INVALID")
        if len(self.payouts) > self.field_size:
            raise ValueError("DFS_CONTEST_PAYOUT_ROWS_EXCEED_FIELD")
        if any(p < 0 or not math.isfinite(p) for p in self.payouts):
            raise ValueError("DFS_CONTEST_PAYOUT_INVALID")
        if any(self.payouts[i] < self.payouts[i + 1] for i in range(len(self.payouts) - 1)):
            raise ValueError("DFS_CONTEST_PAYOUT_NOT_DESCENDING")

    def payout_at(self, rank: int) -> float:
        if rank < 1 or rank > self.field_size:
            return 0.0
        idx = rank - 1
        return self.payouts[idx] if idx < len(self.payouts) else 0.0

    def split_tie_payout(self, rank_start: int, tie_count: int) -> float:
        if tie_count < 1:
            raise ValueError("DFS_CONTEST_TIE_COUNT_INVALID")
        return sum(self.payout_at(rank) for rank in range(rank_start, rank_start + tie_count)) / tie_count


@dataclass(frozen=True)
class ContestEVResult:
    simulations: int
    candidate_key: tuple[str, ...]
    candidate_duplication: int
    mean_gross_payout: float
    mean_profit: float
    roi: float
    cash_rate: float
    first_place_or_tied_rate: float
    top_one_percent_rate: float
    mean_starting_rank: float
    path_set_id: str
    field_version: str
    contest_version: str


def _candidate_key(candidate: Iterable[DKPlayer] | Iterable[str]) -> tuple[str, ...]:
    return lineup_key(candidate)


def evaluate_candidate_ev(
    *,
    candidate: Iterable[DKPlayer] | Iterable[str],
    field: GeneratedField,
    contest: ContestStructure,
    score_paths: AlignedScorePaths,
    max_simulations: int | None = None,
) -> ContestEVResult:
    """Price one lineup against a generated field using aligned joint score paths.

    Every copy of an identical lineup receives the same path score and ties split
    the sum of the occupied finishing-position prizes, matching standard DFS tie
    payout mechanics. The generated field represents opponents only, so contest
    size must equal generated opponents + this candidate entry.
    """
    contest.validate()
    if contest.field_size != field.field_size + 1:
        raise ValueError(
            f"DFS_CONTEST_FIELD_MISMATCH:{contest.field_size}:{field.field_size + 1}"
        )
    key = _candidate_key(candidate)
    all_keys = set(field.counts)
    all_keys.add(key)
    missing = sorted({pid for lineup in all_keys for pid in lineup if pid not in score_paths.player_scores})
    if missing:
        raise ValueError("DFS_CONTEST_SCORE_PATHS_MISSING:" + ",".join(missing))

    sims = score_paths.path_count if max_simulations is None else min(score_paths.path_count, int(max_simulations))
    if sims < 1000:
        raise ValueError(f"DFS_CONTEST_TOO_FEW_SIMULATIONS:{sims}")
    if len(field.counts) * sims > 30_000_000:
        raise ValueError("DFS_CONTEST_EVALUATION_BUDGET_EXCEEDED")

    candidate_ids = key
    gross_payouts: list[float] = []
    start_ranks: list[int] = []
    cashes = 0
    firsts = 0
    top_ones = 0
    top_one_cut = max(1, math.ceil(contest.field_size * 0.01))

    for sim_idx in range(sims):
        candidate_score = sum(score_paths.player_scores[pid][sim_idx] for pid in candidate_ids)
        greater = 0
        equal = 0
        for field_key, count in field.counts.items():
            score = sum(score_paths.player_scores[pid][sim_idx] for pid in field_key)
            if score > candidate_score + 1e-9:
                greater += count
            elif abs(score - candidate_score) <= 1e-9:
                equal += count
        rank_start = greater + 1
        tie_count = equal + 1
        gross = contest.split_tie_payout(rank_start, tie_count)
        gross_payouts.append(gross)
        start_ranks.append(rank_start)
        if gross > 0:
            cashes += 1
        if greater == 0:
            firsts += 1
        if rank_start <= top_one_cut:
            top_ones += 1

    mean_gross = fmean(gross_payouts)
    profit = mean_gross - contest.entry_fee
    roi = profit / contest.entry_fee if contest.entry_fee > 0 else 0.0
    return ContestEVResult(
        simulations=sims,
        candidate_key=key,
        candidate_duplication=1 + field.counts.get(key, 0),
        mean_gross_payout=mean_gross,
        mean_profit=profit,
        roi=roi,
        cash_rate=cashes / sims,
        first_place_or_tied_rate=firsts / sims,
        top_one_percent_rate=top_ones / sims,
        mean_starting_rank=fmean(start_ranks),
        path_set_id=score_paths.path_set_id,
        field_version=field.config.version,
        contest_version=contest.version,
    )
