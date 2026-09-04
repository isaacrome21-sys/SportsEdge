#!/usr/bin/env python3
"""Run the SportsEdge research evaluator over one or more historical JSONL files.

Each JSON line must follow ``sportsedge.research.multi_market_backtest``. Files may
contain multiple sports/markets; this script groups them before evaluation.
Research output never changes production deployment state or Truth Gate floors.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from sportsedge.research.betting_uncertainty import selected_betting_bootstrap
from sportsedge.research.multi_market_backtest import (
    ResearchBacktestError,
    paired_market_bootstrap,
    summarize_binary_market,
)


def _files(inputs: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            out.extend(sorted(path.rglob("*.jsonl")))
        elif path.is_file():
            out.append(path)
        else:
            raise SystemExit(f"input not found: {path}")
    if not out:
        raise SystemExit("no JSONL inputs found")
    return out


def _load(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
                if not isinstance(value, dict):
                    raise SystemExit(f"{path}:{line_no}: each JSONL row must be an object")
                rows.append(value)
    if not rows:
        raise SystemExit("historical input contains no rows")
    return rows


def _identity(row: dict[str, Any]) -> tuple[str, str]:
    sport = str(row.get("sport") or "").strip().upper()
    market = str(row.get("market") or "").strip().upper()
    if not sport or not market:
        raise SystemExit("every row requires sport and market")
    return sport, market


def _safe_pair(rows: list[dict[str, Any]], *, reps: int, seed: int):
    paired = [row for row in rows if row.get("benchmark_p") not in (None, "") and row.get("outcome") in (0, 1, True, False)]
    if len({int(row["season"]) for row in paired}) < 2:
        return {"status": "UNAVAILABLE", "reason": "PAIRED_BENCHMARK_REQUIRES_MULTIPLE_SEASONS"}
    try:
        return {"status": "AVAILABLE", **paired_market_bootstrap(rows, reps=reps, seed=seed)}
    except ResearchBacktestError as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}


def _safe_betting(rows: list[dict[str, Any]], *, reps: int, seed: int):
    selected = [row for row in rows if row.get("selected", True) is True and row.get("offered_decimal") not in (None, "")]
    if len({int(row["season"]) for row in selected}) < 2:
        return {"status": "UNAVAILABLE", "reason": "BETTING_UNCERTAINTY_REQUIRES_MULTIPLE_SEASONS"}
    try:
        return {"status": "AVAILABLE", **selected_betting_bootstrap(rows, reps=reps, seed=seed)}
    except ResearchBacktestError as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", help="JSONL file(s) or directories")
    parser.add_argument("--output", required=True, help="output JSON report")
    parser.add_argument("--bootstrap-reps", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260903)
    args = parser.parse_args()

    paths = _files(args.inputs)
    rows = _load(paths)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_identity(row), []).append(row)

    markets: list[dict[str, Any]] = []
    for (sport, market), market_rows in sorted(grouped.items()):
        try:
            summary = summarize_binary_market(market_rows)
            status = "EVALUATED"
            error = None
        except ResearchBacktestError as exc:
            summary = None
            status = "FAIL_CLOSED"
            error = str(exc)
        markets.append({
            "sport": sport,
            "market": market,
            "status": status,
            "error": error,
            "summary": summary,
            "paired_benchmark_uncertainty": _safe_pair(market_rows, reps=args.bootstrap_reps, seed=args.seed),
            "selected_betting_uncertainty": _safe_betting(market_rows, reps=args.bootstrap_reps, seed=args.seed),
        })

    report = {
        "schema_version": 1,
        "report_type": "SPORTSEDGE_CROSS_SPORT_HISTORICAL_RESEARCH",
        "production_eligibility_changed": False,
        "source_files": [str(path) for path in paths],
        "row_count": len(rows),
        "market_count": len(markets),
        "bootstrap_reps": args.bootstrap_reps,
        "bootstrap_seed": args.seed,
        "markets": markets,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
