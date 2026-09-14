from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .draftkings import DraftKingsClient, resolve_slate
from .optimizer import OptimizedLineup, optimize_single_entry
from .projections import ensure_projection_coverage, load_projection_snapshot, validate_projection_freshness
from .rules import get_rules
from .sources.football_espn import EspnFootballContextClient
from .sources.mlb_statsapi import MLBStatsApiContextClient
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
    def __init__(
        self,
        dk_client: DraftKingsClient | None = None,
        mlb_context_client: MLBStatsApiContextClient | None = None,
        football_context_client: EspnFootballContextClient | None = None,
    ) -> None:
        self.dk = dk_client or DraftKingsClient()
        self.mlb_context = mlb_context_client or MLBStatsApiContextClient()
        self.football_context = football_context_client or EspnFootballContextClient()

    def run(
        self,
        *,
        sport: str,
        requested_start: datetime,
        projection_snapshot: str | Path | None = None,
        salary_csv: str | Path | None = None,
        allow_dk_fppg_baseline: bool = False,
        beam_width: int = 30_000,
        max_projection_age_hours: float = 36.0,
        auto_context: bool = True,
        allow_context_failure: bool = False,
    ) -> DfsRunResult:
        sport = sport.upper()
        if requested_start.tzinfo is None:
            raise ValueError("DFS_REQUESTED_START_MUST_BE_TIMEZONE_AWARE")
        rules = get_rules(sport)
        requested_date = requested_start.date()
        if salary_csv is not None:
            slate = DKSlate(sport, -1, requested_start.astimezone(timezone.utc), name="DKSalaries.csv fallback")
            players = self.dk.load_salary_csv(salary_csv)
            salary_source = "DKSALARIES_CSV"
        else:
            slates = self.dk.discover_slates(sport)
            slate = resolve_slate(slates, requested_start=requested_start)
            players = self.dk.fetch_draftables(slate.draft_group_id)
            salary_source = "DK_DRAFTABLES_JSON"

        context_diagnostics: dict[str, Any] = {"auto_context": auto_context}
        if auto_context:
            try:
                if sport == "MLB":
                    evidence = self.mlb_context.build_context(requested_date)
                    players, context_diagnostics = self.mlb_context.apply_to_players(players, evidence)
                    context_diagnostics["auto_context"] = True
                elif sport in {"NFL", "CFB"}:
                    evidence = self.football_context.build_context(sport, requested_date)
                    players, context_diagnostics = self.football_context.apply_to_players(players, evidence)
                    context_diagnostics["auto_context"] = True
            except Exception as exc:
                if not allow_context_failure:
                    raise RuntimeError(f"DFS_LIVE_CONTEXT_FAILED:{sport}:{type(exc).__name__}:{exc}") from exc
                context_diagnostics = {
                    "auto_context": True,
                    "context_state": "FAILED_ALLOWED",
                    "context_error": f"{type(exc).__name__}:{exc}",
                }

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
        lineup = optimize_single_entry(sport, rules, players, projections, beam_width=beam_width)
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
                "salary_source": salary_source,
                "slate_start_utc": slate.start_time.isoformat(),
                "player_count": len(players),
                "active_player_count": sum(1 for p in players if not p.is_disabled),
                "projection_count": len(projections),
                "projection_sources": sources,
                "salary_cap": rules.salary_cap,
                "lineup_salary": lineup.salary,
                "beam_width": beam_width,
                **context_diagnostics,
                **freshness,
            },
        )
