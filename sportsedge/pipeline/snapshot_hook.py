"""Hook to the shared line-snapshot store (owned by another lane).

The store module is being built separately (``sportsedge.line_snapshots``,
branch ``claude/line-snapshot-store``). This file does not implement it; it
only calls it when present, so every sport records snapshots the same way once
that lands. Until then ``record`` returns ``"SNAPSHOT_STORE_UNAVAILABLE"`` and
changes nothing.
"""
from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import Any

from .picks import PickRecord


def record(*, sport: str, issue_number: int, body: str, title: str | None,
           game: dict[str, Any], board: list[dict[str, Any]],
           picks: Iterable[PickRecord], recorded_at: str) -> str:
    try:
        store = importlib.import_module("sportsedge.line_snapshots")
    except ModuleNotFoundError:
        return "SNAPSHOT_STORE_UNAVAILABLE"
    rows = []
    for p in picks:
        row = p.to_dict()
        row["pick"] = " ".join(x for x in (p.subject, p.selection, "" if p.line is None else f"{p.line:g}") if x)
        row["price"] = p.dk_price
        rows.append(row)
    snap = store.build_snapshot(sport=sport, issue_number=issue_number, body=body, title=title,
                                game=game, board=board, picks=rows, recorded_at=recorded_at)
    return "APPENDED" if store.append_snapshot(snap) else "DUPLICATE"
