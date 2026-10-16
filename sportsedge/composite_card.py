"""#2359 B: per-game composite RUN IT card. Research only.

Evaluates each complete game group once with its OWN operative as-of (the
actual final genuine verification instant of that game's quotes, from
``capture_preflight``), then merges child artifacts into an explicitly
MULTI_AS_OF_COMPOSITE with an immutable, recomputable manifest.

Never changed here: the 180s stale bound (strict >180 refuses), the 120s F5
pairing contract, immutable ``quote_captured_at``. A single game whose own
capture spans >180s still refuses its stale rows; per-game grouping only
removes cross-game capture delay. No stake, PLAY, EV or gate override.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any

from . import capture_preflight as cp
from .card_correlation import grade_card_positions
from .quote_freshness import (MAX_QUOTE_AGE_SECONDS, _parse,
                              check_quote_freshness, is_fresh)

F5_PAIR_MAX_SEPARATION_SECONDS = 120

IDENTITY_FIELDS = ("game_id", "book", "market", "selection", "period", "line",
                   "source_read_id", "player")
_OPTIONAL_IDENTITY = {"player"}

REFUSE_SET_INCOMPLETE = "REFUSE_COMPLETE_SET_MISSING_MEMBER"
REFUSE_SET_SPLIT = "REFUSE_COMPLETE_SET_SPLIT_ACROSS_GAMES"
REFUSE_SET_MEMBER_REFUSED = "REFUSE_COMPLETE_SET_MEMBER_REFUSED"
REFUSE_F5_PAIR_SEPARATION = "REFUSE_F5_PAIR_SEPARATION_OVER_120S"
REFUSE_CONTEXT_AFTER_AS_OF = "REFUSE_CONTEXT_AFTER_CHILD_AS_OF"
REFUSE_CONTEXT_CROSS_GAME = "REFUSE_CONTEXT_FROM_OTHER_GAME"
REFUSE_CONTEXT_UNGROUNDED = "REFUSE_CONTEXT_SOURCE_TIMESTAMP_MISSING"
REFUSE_CHILD_ROW_NOT_EVALUATED = "REFUSE_CHILD_ROW_NOT_EVALUATED"

ROW_IDENTITY_CONFLICT = "ROW_IDENTITY_CONFLICT"
ROW_IDENTITY_INCOMPLETE = "ROW_IDENTITY_INCOMPLETE"
CHILD_MIXED_AS_OF = "CHILD_MIXED_AS_OF"
CHILD_CROSS_GAME = "CHILD_CROSS_GAME_CONTAMINATION"
CHILD_UNKNOWN_ROW = "CHILD_UNKNOWN_ROW"
CHILD_DUPLICATE_ROW = "CHILD_DUPLICATE_ROW"
CHILD_ACTIVE_STAKE = "CHILD_EMITTED_STAKE_OR_PLAY"
TIMESTAMP_MUTATED = "QUOTE_TIMESTAMP_MUTATED"
COMPOSITE_UNVERIFIED = "COMPOSITE_MANIFEST_UNVERIFIED"
GRADE_ROW_NOT_ACTIVE = "GRADE_ROW_NOT_ACTIVE"

REQUIRED_REGRESSIONS = ("audit_schema", "pit_context", "freshness", "dedup", "grading")
RELEASE_BLOCKED = "COMPOSITE_RELEASE_BLOCKED_REGRESSIONS_PENDING"
RELEASE_RESEARCH_ONLY_REGRESSIONS_PASSED = "COMPOSITE_RESEARCH_ONLY_REGRESSIONS_PASSED"


class CompositeError(ValueError):
    pass


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def row_identity_dict(row: Mapping[str, Any]) -> dict:
    out = {}
    for f in IDENTITY_FIELDS:
        if f not in _OPTIONAL_IDENTITY and (f not in row or row[f] is None
                                            or str(row[f]).strip() == ""):
            raise CompositeError(f"{ROW_IDENTITY_INCOMPLETE}:{f}")
        out[f] = row.get(f)
    return out


def _identity_key(row: Mapping[str, Any]) -> str:
    return _digest(row_identity_dict(row))


def release_state(passed: Iterable[str]) -> dict:
    missing = sorted(set(REQUIRED_REGRESSIONS) - set(passed))
    return {"state": RELEASE_BLOCKED if missing else RELEASE_RESEARCH_ONLY_REGRESSIONS_PASSED,
            "missing": missing, "research_only": True}


def single_as_of_preflight(rows: Iterable[Mapping[str, Any]]) -> dict:
    """The original one-as-of-per-run topology, for replay comparison."""
    return cp.preflight(rows)


def _dedupe(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict], int]:
    seen: dict[str, tuple[str, dict]] = {}
    collapsed = 0
    for raw in rows:
        r = copy.deepcopy(dict(raw))
        k = _identity_key(r)
        d = _digest(r)
        if k in seen:
            if seen[k][0] != d:
                raise CompositeError(f"{ROW_IDENTITY_CONFLICT}:{r.get('row_id')}")
            collapsed += 1
            continue
        seen[k] = (d, r)
    ids = [v[1].get("row_id") for v in seen.values()]
    if len(ids) != len(set(ids)) or any(i in (None, "") for i in ids):
        raise CompositeError(f"{ROW_IDENTITY_CONFLICT}:ROW_ID")
    return [v[1] for v in seen.values()], collapsed


def _check_context(items: list, game: str, as_of: datetime) -> str | None:
    for it in items:
        if not isinstance(it, Mapping):
            return REFUSE_CONTEXT_UNGROUNDED
        if str(it.get("game_id")) != game:
            return REFUSE_CONTEXT_CROSS_GAME
        try:
            ts = _parse(it.get("source_timestamp"))
        except ValueError:
            return REFUSE_CONTEXT_UNGROUNDED
        if ts is None:
            return REFUSE_CONTEXT_UNGROUNDED
        if ts > as_of:
            return REFUSE_CONTEXT_AFTER_AS_OF
    return None


def build_composite(rows: Iterable[Mapping[str, Any]], *,
                    evaluator: Callable[[str, list, str, list], Mapping],
                    revision: str, publication_clock: str,
                    context: Mapping[str, list] | None = None) -> dict:
    if evaluator is None:
        raise CompositeError("EVALUATOR_REQUIRED")
    _parse(publication_clock)  # aware ISO required; raises otherwise
    context = context or {}
    uniq, collapsed = _dedupe(rows)

    refusal: dict[str, str] = {}
    # Complete-set binding across the whole input (a set never spans games).
    sets: dict[str, list[dict]] = {}
    for r in uniq:
        if r.get("set_id"):
            sets.setdefault(str(r["set_id"]), []).append(r)
    for sid, members in sets.items():
        games = {m["game_id"] for m in members}
        sizes = {m.get("set_size") for m in members}
        code = None
        if len(games) > 1:
            code = REFUSE_SET_SPLIT
        elif len(sizes) != 1 or not isinstance(next(iter(sizes)), int) \
                or isinstance(next(iter(sizes)), bool) \
                or len(members) != next(iter(sizes)):
            code = REFUSE_SET_INCOMPLETE
        if code:
            for m in members:
                refusal[m["row_id"]] = code

    groups: dict[str, list[dict]] = {}
    for r in uniq:
        groups.setdefault(str(r["game_id"]), []).append(r)

    children, out_rows, refused = [], [], []
    by_id = {r["row_id"]: r for r in uniq}
    for game in sorted(groups):
        grows = sorted(groups[game], key=lambda r: str(r["row_id"]))
        try:
            pf = cp.preflight(grows)
        except ValueError:
            pf = None
        as_of_iso = pf["as_of_utc"] if pf else None
        ages: dict[str, float | None] = {}
        if pf:
            for pr in pf["rows"]:
                ages[pr["row_id"]] = pr.get("quote_age_seconds")
                if "refusal_code" in pr:
                    refusal.setdefault(pr["row_id"], pr["refusal_code"])
        else:
            for r in grows:
                refusal.setdefault(r["row_id"], cp.REFUSE_NO_FINAL_VERIFICATION)
        # F5 120s pairing.
        for sid, members in sets.items():
            if members[0]["game_id"] != game:
                continue
            if any(str(m.get("period")).upper() == "FIRST_5" for m in members):
                try:
                    ts = [_parse(m["quote_captured_at"]) for m in members]
                    sep = (max(ts) - min(ts)).total_seconds()
                except (ValueError, TypeError):
                    sep = None
                if sep is not None and sep > F5_PAIR_MAX_SEPARATION_SECONDS:
                    for m in members:
                        refusal.setdefault(m["row_id"], REFUSE_F5_PAIR_SEPARATION)
        # PIT context scoped to this child.
        ctx_items = [copy.deepcopy(c) for c in context.get(game, [])]
        if as_of_iso:
            cctx = _check_context(ctx_items, game, _parse(as_of_iso))
            if cctx:
                for r in grows:
                    refusal.setdefault(r["row_id"], cctx)
        # A refused member refuses its whole set.
        for sid, members in sets.items():
            if members[0]["game_id"] == game and any(m["row_id"] in refusal for m in members):
                for m in members:
                    refusal.setdefault(m["row_id"], REFUSE_SET_MEMBER_REFUSED)

        active = [r for r in grows if r["row_id"] not in refusal]
        input_digest = _digest(grows)
        child_run_id = _digest([game, as_of_iso, input_digest])[:16]
        child_out: dict = {}
        if active:
            child_out = dict(evaluator(game, copy.deepcopy(active), as_of_iso, ctx_items))
            if child_out.get("as_of_utc") != as_of_iso:
                raise CompositeError(f"{CHILD_MIXED_AS_OF}:{game}")
            if "game_id" in child_out and str(child_out["game_id"]) != game:
                raise CompositeError(f"{CHILD_CROSS_GAME}:{game}")
            active_by_key = {_identity_key(r): r for r in active}
            seen_keys = set()
            for cr in child_out.get("rows", []):
                if str(cr.get("game_id")) != game:
                    raise CompositeError(f"{CHILD_CROSS_GAME}:{game}")
                k = _identity_key(cr)
                src = active_by_key.get(k)
                if src is None:
                    raise CompositeError(f"{CHILD_UNKNOWN_ROW}:{game}")
                if k in seen_keys:
                    raise CompositeError(f"{CHILD_DUPLICATE_ROW}:{game}")
                seen_keys.add(k)
                if cr.get("quote_captured_at") != src["quote_captured_at"]:
                    raise CompositeError(f"{TIMESTAMP_MUTATED}:{src['row_id']}")
                if cr.get("stake") not in (None, 0) or cr.get("play") is True:
                    raise CompositeError(f"{CHILD_ACTIVE_STAKE}:{src['row_id']}")
                out_rows.append({**copy.deepcopy(dict(cr)), "row_id": src["row_id"],
                                 "as_of_utc": as_of_iso, "child_run_id": child_run_id,
                                 "quote_age_seconds": ages.get(src["row_id"]),
                                 "research_only": True})
            omitted = [r for r in active if _identity_key(r) not in seen_keys]
            if omitted:
                for r in omitted:
                    refusal[r["row_id"]] = REFUSE_CHILD_ROW_NOT_EVALUATED
                for sid, members in sets.items():
                    if members[0]["game_id"] == game and any(m["row_id"] in refusal for m in members):
                        for m in members:
                            refusal.setdefault(m["row_id"], REFUSE_SET_MEMBER_REFUSED)
                out_rows[:] = [o for o in out_rows if o["row_id"] not in refusal]
        for r in grows:
            if r["row_id"] in refusal:
                refused.append({**row_identity_dict(r), "row_id": r["row_id"],
                                "quote_captured_at": r.get("quote_captured_at"),
                                "refusal_code": refusal[r["row_id"]],
                                "as_of_utc": as_of_iso, "child_run_id": child_run_id})
        children.append({
            "child_run_id": child_run_id, "game_id": game, "as_of_utc": as_of_iso,
            "input_digest": input_digest,
            "rows": [{"row_id": r["row_id"], "identity": row_identity_dict(r),
                      "quote_captured_at": r.get("quote_captured_at"),
                      "quote_age_seconds": ages.get(r["row_id"]),
                      "status": refusal.get(r["row_id"], "ACTIVE")} for r in grows],
            "child_output_digest": _digest(child_out),
            "context_digest": _digest(ctx_items),
            "revision": revision,
            "status": "EVALUATED" if active else "ALL_REFUSED",
        })
    out_rows.sort(key=lambda r: (str(r["game_id"]), str(r["row_id"])))
    refused.sort(key=lambda r: (str(r["game_id"]), str(r["row_id"])))
    manifest = {"artifact_kind": "MULTI_AS_OF_COMPOSITE",
                "publication_clock_utc": publication_clock,
                "publication_clock_note": "publication clock only; never a child operative instant",
                "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
                "children": children,
                "composite_rows_digest": _digest(out_rows),
                "refused_rows_digest": _digest(refused)}
    return {"manifest": manifest, "manifest_digest": _digest(manifest),
            "rows": out_rows, "refused": refused,
            "duplicates_collapsed": collapsed,
            "semantic_digest": _digest([out_rows, refused]),
            "research_only": True, "release_state": RELEASE_BLOCKED}


def verify_composite(comp: Mapping[str, Any]) -> dict:
    problems = []
    m = comp.get("manifest") if isinstance(comp, Mapping) else None
    if not isinstance(m, Mapping):
        return {"ok": False, "problems": ["MANIFEST_MISSING"]}
    if _digest(m) != comp.get("manifest_digest"):
        problems.append("MANIFEST_DIGEST_MISMATCH")
    if m.get("artifact_kind") != "MULTI_AS_OF_COMPOSITE":
        problems.append("ARTIFACT_KIND")
    if _digest(comp.get("rows")) != m.get("composite_rows_digest"):
        problems.append("ROWS_DIGEST_MISMATCH")
    if _digest(comp.get("refused")) != m.get("refused_rows_digest"):
        problems.append("REFUSED_DIGEST_MISMATCH")
    manifest_rows = {}
    for c in m.get("children", []):
        try:
            asof = _parse(c.get("as_of_utc"))
        except ValueError:
            problems.append("CHILD_AS_OF_INVALID")
            continue
        for r in c.get("rows", []):
            manifest_rows[r.get("row_id")] = (c, r)
            if asof is None or r.get("status") != "ACTIVE":
                continue
            f = check_quote_freshness(r.get("quote_captured_at"), now=asof)
            if f["age_seconds"] != r.get("quote_age_seconds"):
                problems.append(f"AGE_NOT_RECOMPUTABLE:{r.get('row_id')}")
            if not is_fresh(f):
                problems.append(f"ACTIVE_ROW_NOT_FRESH:{r.get('row_id')}")
    for r in comp.get("rows", []):
        hit = manifest_rows.get(r.get("row_id"))
        if not hit or hit[1].get("status") != "ACTIVE" \
                or hit[0].get("as_of_utc") != r.get("as_of_utc") \
                or hit[1].get("quote_captured_at") != r.get("quote_captured_at"):
            problems.append(f"ROW_NOT_IN_MANIFEST:{r.get('row_id')}")
    return {"ok": not problems, "problems": problems}


def grade_composite(comp: Mapping[str, Any], results: Mapping[str, Any]) -> dict:
    v = verify_composite(comp)
    if not v["ok"]:
        raise CompositeError(f"{COMPOSITE_UNVERIFIED}:{v['problems']}")
    active = {r["row_id"]: r for r in comp["rows"]}
    for rid in results:
        if rid not in active:
            raise CompositeError(f"{GRADE_ROW_NOT_ACTIVE}:{rid}")
    legs = [{"row_id": rid, "game_id": r["game_id"], "thesis_id": r.get("thesis_id"),
             "result": results.get(rid)} for rid, r in active.items()]
    return grade_card_positions(legs)
