"""Governed wrapper over the canonical CFB run machine.

The underlying run machine owns prediction/pricing. This wrapper adds full-board
coverage accounting, historical-vs-live policy separation and narrative override
controls without changing Model_P, fair price, edge or EV.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from .audit_contracts import CFBOverride, CoverageItem, CoverageReport
from .decision_policy import historical_candidate_policy, live_candidate_decision
from .run_machine import CFBMachineReport, CFBMachineResult


class CFBGovernedRunError(ValueError):
    pass


@dataclass(frozen=True)
class GovernedCFBResult:
    engine_result: CFBMachineResult
    governed_status: str
    governed_reason: str
    historical_status: str
    override_id: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


@dataclass(frozen=True)
class GovernedCFBReport:
    mode: str
    decision_stage: str
    machine_report: CFBMachineReport
    coverage_report: CoverageReport
    results: tuple[GovernedCFBResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "decision_stage": self.decision_stage,
            "machine_report": self.machine_report.to_dict(),
            "coverage_report": self.coverage_report.to_dict(),
            "results": [row.to_dict() for row in self.results],
        }


def build_coverage_report(
    *,
    expected_games: Sequence[Mapping[str, Any]],
    machine_report: CFBMachineReport,
) -> CoverageReport:
    """Account for every in-scope schedule game, including games with no market quotes."""

    expected_ids: list[str] = []
    classification: dict[str, str] = {}
    for row in expected_games:
        game_id = str(row.get("game_id") or "").strip()
        cls = str(row.get("classification") or "").strip().upper()
        if not game_id:
            raise CFBGovernedRunError("EXPECTED_GAME_ID_REQUIRED")
        expected_ids.append(game_id)
        classification[game_id] = cls
    seen_results: dict[str, list[CFBMachineResult]] = {}
    for result in machine_report.results:
        seen_results.setdefault(result.game_id, []).append(result)
    source_failures = bool(machine_report.source_failures)
    items: list[CoverageItem] = []
    for game_id in expected_ids:
        rows = seen_results.get(game_id, [])
        if rows and any(row.engine_status == "PRICED" for row in rows):
            items.append(CoverageItem(game_id, classification[game_id], "SCORED"))
        elif rows:
            reasons = sorted({row.reason for row in rows})
            items.append(CoverageItem(game_id, classification[game_id], "BLOCKED", ";".join(reasons)))
        else:
            reason = "SOURCE_FAILURE_NO_GAME_RESULT" if source_failures else "NO_MARKET_QUOTES_OR_RESULT"
            items.append(CoverageItem(game_id, classification[game_id], "UNAVAILABLE", reason))
    return CoverageReport(tuple(expected_ids), tuple(items)).validate()


def _override_index(overrides: Iterable[CFBOverride]) -> dict[str, CFBOverride]:
    index: dict[str, CFBOverride] = {}
    for override in overrides:
        value = override.validate()
        if value.game_id in index:
            raise CFBGovernedRunError(f"MULTIPLE_NARRATIVE_OVERRIDES:{value.game_id}")
        index[value.game_id] = value
    return index


def govern_cfb_report(
    machine_report: CFBMachineReport,
    *,
    expected_games: Sequence[Mapping[str, Any]],
    decision_stage: str,
    historical_market_status: Mapping[str, str],
    exposure_ok: bool,
    data_quality_ok: bool,
    policy_sha_ok: bool,
    overrides: Iterable[CFBOverride] = (),
    min_edge: float = 0.03,
) -> GovernedCFBReport:
    stage = str(decision_stage or "").upper()
    if stage not in {"HISTORICAL", "LIVE"}:
        raise CFBGovernedRunError("DECISION_STAGE_INVALID")
    mode = str(machine_report.mode).upper()
    override_map = _override_index(overrides)
    if mode == "AUTOMATIC" and override_map:
        raise CFBGovernedRunError("AUTOMATIC_NARRATIVE_OVERRIDE_FORBIDDEN")
    coverage = build_coverage_report(expected_games=expected_games, machine_report=machine_report)
    coverage_ok = coverage.coverage_ok
    governed: list[GovernedCFBResult] = []
    for result in machine_report.results:
        historical_status = str(historical_market_status.get(result.market, "UNRUN")).upper()
        override = override_map.get(result.game_id)
        if result.engine_status != "PRICED" or result.edge is None or result.ev_per_dollar is None:
            governed.append(GovernedCFBResult(
                result, "BLOCKED", result.reason, historical_status, override.override_id if override else None,
            ))
            continue
        quote_fresh = result.reason != "CFB_QUOTE_STALE"
        two_sided = result.fair_market_p is not None
        if stage == "HISTORICAL":
            decision = historical_candidate_policy(
                edge=result.edge,
                ev_per_dollar=result.ev_per_dollar,
                quote_fresh=quote_fresh,
                two_sided=two_sided,
                data_quality_ok=bool(data_quality_ok),
                pit_ok=bool(data_quality_ok),
                coverage_ok=coverage_ok,
                policy_sha_ok=bool(policy_sha_ok),
                min_edge=min_edge,
            )
        else:
            decision = live_candidate_decision(
                edge=result.edge,
                ev_per_dollar=result.ev_per_dollar,
                quote_fresh=quote_fresh,
                two_sided=two_sided,
                exposure_ok=bool(exposure_ok),
                data_quality_ok=bool(data_quality_ok),
                coverage_ok=coverage_ok,
                override_log_complete=True,
                policy_sha_ok=bool(policy_sha_ok),
                historical_status=historical_status,
                min_edge=min_edge,
            )
        status, reason = decision.status, decision.reason
        if override is not None:
            action = override.action.upper()
            if action == "BLOCK":
                status, reason = "BLOCKED", f"NARRATIVE_OVERRIDE_BLOCK:{override.reason_code}"
            elif action == "DOWNGRADE" and status in {"OFFICIAL_BET", "SHADOW_QUALIFIED"}:
                status, reason = "NO_BET", f"NARRATIVE_OVERRIDE_DOWNGRADE:{override.reason_code}"
            # NO_CHANGE leaves mathematical decision untouched.
        governed.append(GovernedCFBResult(
            result, status, reason, historical_status, override.override_id if override else None,
        ))
    return GovernedCFBReport(
        mode=mode,
        decision_stage=stage,
        machine_report=machine_report,
        coverage_report=coverage,
        results=tuple(governed),
    )
