"""Attach the NFL both-side board without editing the frozen M2 run machine.

The frozen ``sportsedge/sports/nfl/run_machine.py`` and
``scripts/run_nfl_auto.py`` stay byte-identical. This sidecar only decorates
an already-built report or auto payload.
"""
from __future__ import annotations

from typing import Any, Mapping

from sportsedge.football_full_board import board_from_machine_results


def attach_nfl_both_sides(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of an NFL report with both sides of props, sides, and totals."""
    rows = report.get("results") or []
    if not isinstance(rows, (list, tuple)):
        rows = []
    board = board_from_machine_results("NFL", rows)
    summary = dict(report.get("summary") or {})
    summary["full_board"] = board
    summary["both_sides"] = board["summary"]["both_sides"]
    summary["side_rows"] = board["summary"]["side_rows"]
    summary["total_rows"] = board["summary"]["total_rows"]
    summary["prop_rows"] = board["summary"]["prop_rows"]
    summary["catalog_complete"] = board["summary"]["both_sides"] is True and summary["side_rows"] >= 2 and summary["total_rows"] >= 2 and summary["prop_rows"] >= 2
    out = dict(report)
    out["summary"] = summary
    return out


def attach_nfl_auto_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Decorate a frozen NFL auto payload. Does not run the frozen script."""
    out = dict(payload)
    report = out.get("report")
    if not isinstance(report, Mapping):
        report = {"results": [], "summary": {}}
    attached = attach_nfl_both_sides(report)
    out["report"] = attached
    summary = dict(out.get("summary") or {})
    for key in ("both_sides", "side_rows", "total_rows", "prop_rows", "catalog_complete"):
        summary[key] = attached["summary"][key]
    out["summary"] = summary
    return out
