from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .dk_contest import DraftKingsContestClient
from .draftkings import DraftKingsClient, resolve_slate
from .field import FieldGenerationConfig
from .optimizer import OptimizedLineup, optimize_single_entry
from .projections import ensure_projection_coverage, load_projection_snapshot, validate_projection_freshness
from .rules import get_rules
from .score_paths import load_aligned_score_paths
from .selection import EVSelectionResult, select_single_entry_by_ev
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
    ev_selection: EVSelectionResult | None = None


class DfsEngine:
    def __init__(
        self,
        dk_client: DraftKingsClient | None = None,
        dk_contest_client: DraftKingsContestClient | None = None,
        mlb_context_client: MLBStatsApiContextClient | None = None,
        football_context_client: EspnFootballContextClient | None = None,
    ) -> None:
        self.dk = dk_client or DraftKingsClient()
        self.dk_contest = dk_contest_client or DraftKingsContestClient()
        self.mlb_context = mlb_context_client or MLBStatsApiContextClient()
        self.football_context = football_context_client or EspnFootballContextClient()

    def run(
        self,
        *,
        sport: str,
        requested_start: datetime,
        projection_snapshot: str | Path | None = None,
        joint_path_snapshot: str | Path | None = None,
        salary_csv: str | Path | None = None,
        allow_dk_fppg_baseline: bool = False,
        beam_width: int = 30_000,
        max_projection_age_hours: float = 36.0,
        auto_context: bool = True,
        allow_context_failure: bool = False,
        contest_ev_enabled: bool = True,
        strict_contest_ev: bool = False,
        contest_ev_max_simulations: int = 1000,
        contest_ev_max_candidates: int = 8,
        field_min_salary: int = 47_000,
        field_seed: int | None = None,
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
        ev_selection: EVSelectionResult | None = None
        ev_diagnostics: dict[str, Any] = {
            "contest_ev_enabled": bool(contest_ev_enabled),
            "contest_ev_state": "DISABLED" if not contest_ev_enabled else "BLOCKED",
            "selection_mode": "OBJECTIVE_FALLBACK",
        }

        path_snapshot = joint_path_snapshot or projection_snapshot
        if contest_ev_enabled and path_snapshot is None:
            ev_diagnostics["contest_ev_reason"] = "NO_JOINT_PATH_SNAPSHOT"
        elif contest_ev_enabled and salary_source != "DK_DRAFTABLES_JSON":
            ev_diagnostics["contest_ev_reason"] = "NO_LIVE_DK_CONTEST_ID_WITH_CSV_TRANSPORT"
        elif contest_ev_enabled:
            try:
                score_paths = load_aligned_score_paths(path_snapshot, players, sport)
                lobby_payload = self.dk.lobby(sport)
                contest_detail = self.dk_contest.find_single_entry(
                    draft_group_id=slate.draft_group_id,
                    lobby_payload=lobby_payload,
                )
                seed = field_seed
                if seed is None:
                    seed_material = f"{sport}|{slate.draft_group_id}|{slate.start_time.isoformat()}|{score_paths.path_set_id}"
                    seed = int(sha256(seed_material.encode("utf-8")).hexdigest()[:8], 16)
                field_config = FieldGenerationConfig(
                    field_size=contest_detail.structure.field_size - 1,
                    seed=int(seed),
                    min_salary=field_min_salary,
                )
                ev_selection = select_single_entry_by_ev(
                    sport=sport,
                    rules=rules,
                    players=players,
                    projections=projections,
                    score_paths=score_paths,
                    contest=contest_detail.structure,
                    field_config=field_config,
                    beam_width=beam_width,
                    max_candidates=contest_ev_max_candidates,
                    max_simulations=contest_ev_max_simulations,
                )
                lineup = ev_selection.lineup
                ev = ev_selection.ev
                ev_diagnostics = {
                    "contest_ev_enabled": True,
                    "contest_ev_state": "PASS",
                    "selection_mode": "CONTEST_EV",
                    "contest_id": contest_detail.contest_id,
                    "contest_name": contest_detail.name,
                    "contest_field_size": contest_detail.maximum_entries,
                    "contest_current_entries": contest_detail.entries,
                    "contest_entry_fee": contest_detail.entry_fee,
                    "contest_total_payouts": contest_detail.total_payouts,
                    "contest_max_entries_per_user": contest_detail.maximum_entries_per_user,
                    "contest_is_guaranteed": contest_detail.is_guaranteed,
                    "field_generation_version": ev_selection.field.config.version,
                    "field_seed": ev_selection.field.config.seed,
                    "field_unique_lineups": ev_selection.field.unique_lineups,
                    "field_duplicate_rate": round(ev_selection.field.duplicate_rate, 6),
                    "field_ownership_coverage": round(ev_selection.field.ownership_coverage, 6),
                    "joint_path_set_id": score_paths.path_set_id,
                    "joint_path_count": score_paths.path_count,
                    "ev_simulations": ev.simulations,
                    "ev_candidates_generated": ev_selection.candidates_generated,
                    "ev_candidates_evaluated": ev_selection.candidates_evaluated,
                    "lineup_expected_profit": round(ev.mean_profit, 6),
                    "lineup_roi": round(ev.roi, 6),
                    "lineup_cash_rate": round(ev.cash_rate, 6),
                    "lineup_top_one_percent_rate": round(ev.top_one_percent_rate, 6),
                    "lineup_first_place_or_tied_rate": round(ev.first_place_or_tied_rate, 6),
                    "lineup_candidate_duplication": ev.candidate_duplication,
                }
            except Exception as exc:
                if strict_contest_ev:
                    raise RuntimeError(f"DFS_CONTEST_EV_FAILED:{type(exc).__name__}:{exc}") from exc
                ev_diagnostics = {
                    "contest_ev_enabled": True,
                    "contest_ev_state": "BLOCKED",
                    "contest_ev_reason": f"{type(exc).__name__}:{exc}",
                    "selection_mode": "OBJECTIVE_FALLBACK",
                }

        sources: dict[str, int] = {}
        for proj in projections.values():
            sources[proj.source] = sources.get(proj.source, 0) + 1
        return DfsRunResult(
            sport=sport,
            slate=slate,
            players=tuple(players),
            projections=projections,
            lineup=lineup,
            ev_selection=ev_selection,
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
                "lineup_objective_version": lineup.objective_version,
                "lineup_objective_sha256": lineup.objective_sha256,
                "beam_width": beam_width,
                **context_diagnostics,
                **freshness,
                **ev_diagnostics,
            },
        )
