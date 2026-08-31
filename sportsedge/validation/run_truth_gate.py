"""
Unified SportsEdge Truth Gate entry point.

Automatic, manual, and hybrid execution all call the same frozen sport adapter,
which in turn calls the shared TruthGateCore semantics. This module only handles
evidence I/O, report persistence, summaries, and process exit status.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Type

from sportsedge.validation.gate_report import GateReport
from sportsedge.sports.cfb.truth_gate import CFBTruthGate
from sportsedge.sports.nfl.truth_gate import NFLTruthGate
from sportsedge.sports.mlb.truth_gate import MLBTruthGate


class TruthGateRunnerError(ValueError):
    pass


GATES: dict[str, Type[Any]] = {
    "CFB": CFBTruthGate,
    "NFL": NFLTruthGate,
    "MLB": MLBTruthGate,
}


def _canonical(value: Any) -> str:
    return str(value or "").strip().upper()


def load_evidence(path: Path) -> dict[str, Any]:
    """Load one market/family/surface evidence object without modifying it."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError as exc:
        raise TruthGateRunnerError(f"EVIDENCE_UNREADABLE:{path}") from exc
    except json.JSONDecodeError as exc:
        raise TruthGateRunnerError(f"EVIDENCE_JSON_INVALID:{path}") from exc
    if not isinstance(payload, dict):
        raise TruthGateRunnerError("EVIDENCE_OBJECT_REQUIRED")
    return payload


def _evaluate(gate: Any, sport: str, market: str, evidence: Mapping[str, Any]) -> GateReport:
    """Dispatch through the sport's thin adapter; never bypass sport-specific contracts."""
    kwargs = dict(evidence)
    if sport == "CFB":
        return gate.evaluate(market=market, **kwargs)
    if sport == "NFL":
        return gate.evaluate_surface(surface=market, **kwargs)
    if sport == "MLB":
        return gate.evaluate_family(family=market, **kwargs)
    raise TruthGateRunnerError(f"SPORT_UNSUPPORTED:{sport}")


def _report_bytes(report: GateReport) -> bytes:
    return (
        json.dumps(
            report.to_dict(),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_report(report: GateReport, out_dir: Path) -> Path:
    """Persist an immutable report under its full content hash."""
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = report.content_hash()
    target = out_dir / f"{report.sport.lower()}_{report.market.lower()}_{digest}.json"
    body = _report_bytes(report)
    try:
        with target.open("xb") as handle:
            handle.write(body)
    except FileExistsError:
        if target.read_bytes() != body:
            raise TruthGateRunnerError("TRUTH_GATE_REPORT_IMMUTABLE_COLLISION")
    return target


def run_one(
    sport: str,
    market: str,
    evidence: Mapping[str, Any],
    out_dir: Path,
) -> tuple[Path, GateReport]:
    sport_name = _canonical(sport)
    market_name = _canonical(market)
    gate_cls = GATES.get(sport_name)
    if gate_cls is None:
        raise TruthGateRunnerError(f"SPORT_UNSUPPORTED:{sport_name or 'MISSING'}")
    gate = gate_cls()
    report = _evaluate(gate, sport_name, market_name, evidence)
    return write_report(report, out_dir), report


def print_summary(report: GateReport, out_path: Path) -> None:
    print(f"Sport          : {report.sport}")
    print(f"Market         : {report.market}")
    print(f"Market Status  : {report.market_status}")
    print(f"Candidate      : {report.candidate_decision}")
    print(f"Hard Pass      : {report.hard_gate_pass}")
    print(f"Edge           : {report.edge}")
    print(f"Policy SHA     : {report.policy_sha256}")
    print(f"Report Hash    : {report.content_hash()}")
    print(f"Wrote          : {out_path}")
    if report.market_failures:
        print("Market Failures:", report.market_failures)
    if report.candidate_failures:
        print("Candidate Failures:", report.candidate_failures)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SportsEdge Truth Gate - manual, hybrid, or automatic execution"
    )
    parser.add_argument("--sport", required=True, type=str.upper, choices=sorted(GATES))
    parser.add_argument(
        "--market",
        required=True,
        help="Canonical policy identity, e.g. MONEYLINE / SPREAD / TOTAL / V7_GAME / GAME",
    )
    parser.add_argument("--evidence", required=True, type=Path, help="Evidence JSON path")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/truth_gate_reports"),
    )
    parser.add_argument(
        "--fail-on-block",
        action="store_true",
        help="Exit non-zero unless candidate_decision is OFFICIAL_BET",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a human-readable summary without changing the report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = load_evidence(args.evidence)
    out_path, report = run_one(args.sport, args.market, evidence, args.out_dir)
    if args.summary:
        print_summary(report, out_path)
    if args.fail_on_block and report.candidate_decision != "OFFICIAL_BET":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
