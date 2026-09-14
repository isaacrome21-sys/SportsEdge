from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .draftkings import DraftKingsClient, resolve_slate
from .optimizer import OptimizedLineup, optimize_single_entry
from .projections import ensure_projection_coverage, load_projection_snapshot, validate_projection_freshness
from .rules import get_rules
from .types import DKPlayer, DKSlate, Projection


@dataclass(frozen=True)
class DfsRunResult:
    sport: str
    slate: DKSlate
    players: tuple[DKPlayer, ...]
    projections: dict[str, Projection]
    lineup: OptimizedLineup
    diagnostics: dict[str, Any]


class DfsEngine:
    def __init__(self, dk_client: DraftKingsClient | None = None) -> None:
        self.dk = dk_client or DraftKingsClient()

    def run(
        self,
        *,
        sport: str,
        requested_start: datetime,
        projection_snapshot: str | Path | None = None,
        allow_dk_fppg_baseline: bool = False,
        beam_width: int = 30_000,
        max_projection_age_hours: float = 36.0,
    ) -> DfsRunResult:
        sport = sport.upper()
        rules = get_rules(sport)
        slates = self.dk.discover_slates(sport)
        slate = resolve_slate(slates, requested_start=requested_start)
        players = self.dk.fetch_draftables(slate.draft_group_id)
        projections: dict[str, Projection] = {}
        if projection_snapshot is not None:
            projections.update(load_projection_snapshot(projection_snapshot, players, sport))
        projections = ensure_projection_coverage(
            players,
            projections,
            allow_dk_fppg_baseline=allow_dk_fppg_baseline,
        )
        freshness = validate_projection_freshness(
            players,
            projections,
            slate_start=slate.start_time,
            max_age=timedelta(hours=max_projection_age_hours),
        )
        lineup = optimize_single_entry(
            sport,
            rules,
            players,
            projections,
            beam_width=beam_width,
        )
        sources: dict[str, int] = {}
        for proj in projections.values():
            sources[proj.source] = sources.get(proj.source, 0) + 1
        return DfsRunResult(
            sport=sport,
            slate=slate,
            players=tuple(players),
            projections=projections,
            lineup=lineup,
            diagnostics={
                "draft_group_id": slate.draft_group_id,
                "slate_start_utc": slate.start_time.isoformat(),
                "player_count": len(players),
                "projection_count": len(projections),
                "projection_sources": sources,
                "salary_cap": rules.salary_cap,
                "lineup_salary": lineup.salary,
                "beam_width": beam_width,
                **freshness,
            },
        )
