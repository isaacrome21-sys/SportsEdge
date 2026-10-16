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


def _norm_game(value: Any) -> str:
    import re
    return re.sub(r"\s+", "", str(value or "")).upper()


def group_correlated_stacks(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Union of same-game and same-thesis links: a thesis can join games but
    can never split one game into several positions. Game keys normalised."""
    items: list[dict[str, Any]] = []
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("ROW_NOT_MAPPING")
        game = _norm_game(raw.get("game_id"))
        thesis = str(raw.get("thesis_id") or "").strip()
        keys = [k for k in (("game", game) if game else None,
                            ("thesis", thesis) if thesis else None) if k]
        if not keys:
            raise ValueError("CORRELATION_KEY_MISSING: row has neither thesis_id nor game_id")
        for k in keys:
            parent.setdefault(k, k)
        if len(keys) == 2:
            union(keys[0], keys[1])
        items.append((keys[0], dict(raw)))
    stacks: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for k, r in items:
        stacks.setdefault(find(k), []).append(r)
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
