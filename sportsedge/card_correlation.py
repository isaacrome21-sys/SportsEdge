"""Correlated-stack accounting for research cards.

A card may surface several selections that express one thesis (e.g. nine
same-game legs that all need the same team to hit). Grading those as nine
independent positions overstates both the sample size and the record.

Rules (fail-closed):
* rows sharing an explicit ``thesis_id`` form one stack, across games;
* otherwise every row in the same ``game_id`` forms one stack (conservative:
  same-game legs are presumed correlated until a thesis split is declared);
* a row with neither key is rejected rather than silently counted alone.

Stack grade: WIN if every action leg won, LOSS if every action leg lost,
MIXED otherwise, PENDING while any leg is unsettled, NO_ACTION if every leg
pushed/voided. Research accounting only; no stakes or EV are produced.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

_ACTION = {"WIN", "LOSS"}
_NO_ACTION = {"PUSH", "VOID"}


def _stack_key(row: Mapping[str, Any]) -> tuple[str, str]:
    thesis = str(row.get("thesis_id") or "").strip()
    if thesis:
        return ("thesis", thesis)
    game = str(row.get("game_id") or "").strip()
    if game:
        return ("game", game)
    raise ValueError("CORRELATION_KEY_MISSING: row has neither thesis_id nor game_id")


def group_correlated_stacks(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    stacks: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("ROW_NOT_MAPPING")
        stacks.setdefault(_stack_key(raw), []).append(dict(raw))
    return [
        {"stack_kind": k[0], "stack_key": k[1], "n_legs": len(v), "legs": v}
        for k, v in stacks.items()
    ]


def _grade_stack(legs: list[dict[str, Any]]) -> str:
    results = []
    for leg in legs:
        r = leg.get("result")
        if r is None:
            return "PENDING"
        r = str(r).strip().upper()
        if r not in _ACTION | _NO_ACTION:
            raise ValueError(f"UNKNOWN_RESULT:{r}")
        results.append(r)
    action = [r for r in results if r in _ACTION]
    if not action:
        return "NO_ACTION"
    if all(r == "WIN" for r in action):
        return "WIN"
    if all(r == "LOSS" for r in action):
        return "LOSS"
    return "MIXED"


def grade_card_positions(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    stacks = group_correlated_stacks(rows)
    counts = {"WIN": 0, "LOSS": 0, "MIXED": 0, "PENDING": 0, "NO_ACTION": 0}
    graded = []
    for s in stacks:
        g = _grade_stack(s["legs"])
        counts[g] += 1
        graded.append({**s, "grade": g})
    return {
        "positions": len(stacks),
        "legs": sum(s["n_legs"] for s in stacks),
        "wins": counts["WIN"],
        "losses": counts["LOSS"],
        "mixed": counts["MIXED"],
        "pending": counts["PENDING"],
        "no_action": counts["NO_ACTION"],
        "stacks": graded,
        "accounting": "CORRELATED_STACK_AS_SINGLE_POSITION",
    }
