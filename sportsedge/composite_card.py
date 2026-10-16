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
import re
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from . import capture_preflight as cp
from .card_correlation import grade_card_positions
from .promotion_screen import norm_code, tokens
from .promotion_screen import promotes
from .quote_freshness import (MAX_QUOTE_AGE_SECONDS, _parse,
                              check_quote_freshness, is_fresh)

F5_PAIR_MAX_SEPARATION_SECONDS = 120

IDENTITY_FIELDS = ("game_id", "book", "market", "selection", "period", "line",
                   "source_read_id", "player", "team")
_OPTIONAL_IDENTITY = {"player", "team", "line"}
SELECTION_FIELDS = tuple(f for f in IDENTITY_FIELDS if f != "source_read_id")

# Trusted market grammar: complete sets are derived from the market itself,
# never from intake ``set_id`` / ``set_size`` (which are ignored).
_OU = frozenset({"OVER", "UNDER"})
_OU_MARKETS = {"TOTAL", "TEAM_TOTAL", "PITCHER_K", "GAME_TOTAL"}
_SIDE_MARKETS = {"MONEYLINE", "SPREAD", "RUN_LINE", "PUCK_LINE"}
_MIRROR_LINE_MARKETS = {"SPREAD", "RUN_LINE", "PUCK_LINE"}
_THREE_WAY = {"GAME_TOTAL_3_WAY": frozenset({"OVER", "EXACTLY", "UNDER"}),
              "MONEYLINE_3WAY": frozenset({"HOME", "DRAW", "AWAY"})}

REFUSE_SET_INCOMPLETE = "REFUSE_COMPLETE_SET_MISSING_MEMBER"
REFUSE_SET_SPLIT = "REFUSE_COMPLETE_SET_SPLIT_ACROSS_GAMES"
REFUSE_SET_MEMBER_REFUSED = "REFUSE_COMPLETE_SET_MEMBER_REFUSED"
REFUSE_F5_PAIR_SEPARATION = "REFUSE_F5_PAIR_SEPARATION_OVER_120S"
REFUSE_CONTEXT_AFTER_AS_OF = "REFUSE_CONTEXT_AFTER_CHILD_AS_OF"
REFUSE_CONTEXT_CROSS_GAME = "REFUSE_CONTEXT_FROM_OTHER_GAME"
REFUSE_CONTEXT_UNGROUNDED = "REFUSE_CONTEXT_SOURCE_TIMESTAMP_MISSING"
REFUSE_CHILD_ROW_NOT_EVALUATED = "REFUSE_CHILD_ROW_NOT_EVALUATED"
REFUSE_CHILD_AUTHORITY_WITHHELD = "REFUSE_CHILD_ROW_WITHHELD_AUTHORITY_OR_PROMOTION"
REFUSE_MARKET_SET_GRAMMAR_UNKNOWN = "REFUSE_MARKET_SET_GRAMMAR_UNKNOWN"
SELECTION_CAPTURED_TWICE = "SELECTION_CAPTURED_TWICE_NO_SUPERSESSION"
SUPERSESSION_NOT_LATER = "SUPERSESSION_NOT_LATER_CAPTURE"

ROW_IDENTITY_CONFLICT = "ROW_IDENTITY_CONFLICT"
ROW_IDENTITY_INCOMPLETE = "ROW_IDENTITY_INCOMPLETE"
CHILD_MIXED_AS_OF = "CHILD_MIXED_AS_OF"
CHILD_CROSS_GAME = "CHILD_CROSS_GAME_CONTAMINATION"
CHILD_UNKNOWN_ROW = "CHILD_UNKNOWN_ROW"
CHILD_DUPLICATE_ROW = "CHILD_DUPLICATE_ROW"
CHILD_ACTIVE_STAKE = "CHILD_EMITTED_STAKE_OR_PLAY"
TIMESTAMP_MUTATED = "QUOTE_TIMESTAMP_MUTATED"
CHILD_EVALUATION_FIELD_NOT_ALLOWED = "CHILD_EVALUATION_FIELD_NOT_ALLOWED"
CHILD_FIELD_NOT_ALLOWED = "CHILD_FIELD_NOT_ALLOWED"
COMPOSITE_UNVERIFIED = "COMPOSITE_MANIFEST_UNVERIFIED"
GRADE_ROW_NOT_ACTIVE = "GRADE_ROW_NOT_ACTIVE"

REQUIRED_REGRESSIONS = ("audit_schema", "pit_context", "freshness", "dedup", "grading")
RELEASE_BLOCKED = "COMPOSITE_RELEASE_BLOCKED_REGRESSIONS_PENDING"
RELEASE_RESEARCH_ONLY_REGRESSIONS_PASSED = "COMPOSITE_RESEARCH_ONLY_REGRESSIONS_PASSED"


_CHILD_ALLOWED_FIELDS = set(IDENTITY_FIELDS) | {"game_id", "quote_captured_at", "status",
                                               "evaluation", "reason", "thesis_id"}
# Any evaluator's ``evaluation`` dict is validated against this projection.
EVALUATION_FIELDS = ("status", "reason", "reason_detail", "blocker", "blocker_detail", "market",
                     "selection", "line", "odds_american", "estimate_p", "push_p",
                     "loss_p", "fair_american", "pricing_lane", "pricing_provenance",
                     "schema", "model_p")


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


def single_as_of_preflight(rows: Iterable[Mapping[str, Any]], *,
                           receipts: Mapping[str, Any] | None, evaluated_at: Any) -> dict:
    """The original one-as-of-per-run topology, for replay comparison."""
    return cp.preflight(rows, receipts=receipts, evaluated_at=evaluated_at)


def _selection_key(row: Mapping[str, Any]) -> str:
    row_identity_dict(row)  # completeness check
    return _digest({f: row.get(f) for f in SELECTION_FIELDS})


def _ts(row):
    try:
        return _parse(row.get("quote_captured_at"))
    except ValueError:
        return None


def _dedupe(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict], int, list[dict]]:
    """Exact duplicates collapse; one offered selection read twice needs an
    explicit, strictly-later ``supersedes_read_id`` chain or fails closed."""
    by_sel: dict[str, list[dict]] = {}
    digests: set[str] = set()
    collapsed = 0
    order: list[str] = []
    for raw in rows:
        r = copy.deepcopy(dict(raw))
        if "game_id" in r and r["game_id"] is not None:
            r["game_id"] = cp.normalize_game_id(r["game_id"])
        d = _digest(r)
        if d in digests:
            collapsed += 1
            continue
        digests.add(d)
        k = _selection_key(r)
        if k not in by_sel:
            order.append(k)
        by_sel.setdefault(k, []).append(r)
    out, supersessions = [], []
    for k in order:
        group = by_sel[k]
        if len(group) == 1:
            out.append(group[0]); continue
        reads = [str(g.get("source_read_id")) for g in group]
        if len(set(reads)) != len(reads):
            raise CompositeError(f"{ROW_IDENTITY_CONFLICT}:{group[0].get('row_id')}")
        by_read = {str(g.get("source_read_id")): g for g in group}
        for g in group:
            sup = g.get("supersedes_read_id")
            if sup is not None and str(sup) in by_read:
                t_new, t_old = _ts(g), _ts(by_read[str(sup)])
                if t_new is None or t_old is None or t_new <= t_old:
                    raise CompositeError(f"{SUPERSESSION_NOT_LATER}:{g.get('row_id')}")
        if any(_ts(g) is None for g in group):
            raise CompositeError(f"{SELECTION_CAPTURED_TWICE}:{group[0].get('row_id')}")
        chain = sorted(group, key=_ts)
        for prev, nxt in zip(chain, chain[1:]):
            if str(nxt.get("supersedes_read_id")) != str(prev.get("source_read_id")):
                raise CompositeError(f"{SELECTION_CAPTURED_TWICE}:{nxt.get('row_id')}")
        keep = chain[-1]
        for old, nxt in zip(chain, chain[1:]):
            supersessions.append({"selection_key_row": keep["row_id"],
                                  "superseded_row": old["row_id"],
                                  "superseded_read_id": old.get("source_read_id"),
                                  "superseding_read_id": nxt.get("source_read_id")})
        out.append(keep)
    ids = [r.get("row_id") for r in out]
    if len(ids) != len(set(ids)) or any(i in (None, "") for i in ids):
        raise CompositeError(f"{ROW_IDENTITY_CONFLICT}:ROW_ID")
    return out, collapsed, supersessions


def _grammar_sets(rows: list[dict]) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Derive complete-set groups from market grammar; name every refusal."""
    sets: dict[str, list[dict]] = {}
    refusal: dict[str, str] = {}
    kinds: dict[str, tuple] = {}
    for r in rows:
        m = str(r.get("market") or "").upper()
        sel = str(r.get("selection") or "").upper()
        base = (r.get("game_id"), r.get("book"), m, str(r.get("period") or "").upper())
        if m in _OU_MARKETS or m.startswith("PLAYER_"):
            key, kind = base + (r.get("line"), r.get("player"), r.get("team")), ("FIXED", _OU)
        elif m in _THREE_WAY:
            key, kind = base + (r.get("line"),), ("FIXED", _THREE_WAY[m])
        elif m in _SIDE_MARKETS:
            key, kind = base, ("SIDES", m)
        else:
            refusal[r["row_id"]] = REFUSE_MARKET_SET_GRAMMAR_UNKNOWN
            continue
        sk = _digest(list(key))
        sets.setdefault(sk, []).append(r)
        kinds[sk] = kind
    for sk, members in sets.items():
        kind, spec = kinds[sk]
        sels = [str(x.get("selection") or "").upper() for x in members]
        ok = len(sels) == len(set(sels))
        if kind == "FIXED":
            ok = ok and set(sels) == set(spec)
        else:
            ok = ok and len(sels) == 2
            if ok and spec in _MIRROR_LINE_MARKETS:
                try:
                    ok = abs(float(members[0]["line"]) + float(members[1]["line"])) < 1e-9
                except (TypeError, ValueError, KeyError):
                    ok = False
        if not ok:
            for x in members:
                refusal[x["row_id"]] = REFUSE_SET_INCOMPLETE
    return sets, refusal


def _load_allowlist() -> tuple[frozenset, frozenset]:
    import json
    from pathlib import Path
    doc = json.loads((Path(__file__).with_name("composite_status_allowlist.json"))
                     .read_text(encoding="utf-8"))
    statuses = frozenset(norm_code(x) for x in doc["statuses"])
    return statuses, statuses | frozenset(norm_code(x) for x in doc.get("codes", ()))


# STRUCTURAL guard (t211d). Owner-reviewable code sets
# (sportsedge/composite_status_allowlist.json, built by
# scripts/build_composite_status_allowlist.py from the repo's own literals;
# only codes whose MEANING is promotion are excluded). status must be an exact
# member of the status set, reason/blocker of the status|code set, after NFKC
# + single-letter joining. Unknown codes are refused. Identity fields and
# free text are never word-screened.
STATUS_ALLOWLIST, CODE_ALLOWLIST = _load_allowlist()
_CODE_KEYS = frozenset({"reason", "blocker"})
_AUTHORITY_FIELDS = frozenset({"eligible", "play", "playable", "official", "lock", "approved",
                               "actionable", "promotion", "production_activation"})
_MONEY_FIELDS = frozenset({"recommendation", "pick", "estimated_ev", "units", "edge",
                           "to_win", "roi"})
_MONEY_PATTERNS = (re.compile(r"^ev($|_)"), re.compile(r"expected_value"),
                   re.compile(r"^edge_"), re.compile(r"^kelly"), re.compile(r"^stake"),
                   re.compile(r"^bet($|_)"), re.compile(r"_bet$"), re.compile(r"^wager"),
                   re.compile(r"^unit_"), re.compile(r"_units$"), re.compile(r"^risk"),
                   re.compile(r"official"), re.compile(r"^ok_to_"))
# Parameter / identifier names, not authority or money values (t211e).
_EXEMPT_SUFFIXES = ("_id", "_floor", "_cap", "_type", "_policy", "_policy_id")
# ...also when the parameter word is followed by a unit tag (edge_floor_pp).
_EXEMPT_SEGMENT = re.compile(r"_(id|floor|cap|type|policy)(_[a-z0-9]{1,4})?$")
# Keys that may carry a truthy boolean inside pricing_provenance: none.
_TRUE_BOOL_KEYS = frozenset({"research_only"})
# pricing_provenance has its own key allowlist (matches sportsedge.pricing_provenance).
PROVENANCE_KEYS = frozenset({"lane", "mechanism", "source", "engine_lane", "play_eligible"})


def _status_allowed(value: Any) -> bool:
    return isinstance(value, str) and norm_code(value) in STATUS_ALLOWLIST


def _code_allowed(value: Any) -> bool:
    return isinstance(value, str) and norm_code(value) in CODE_ALLOWLIST


# reason_detail / blocker_detail are DIAGNOSTICS ONLY (t211e): the renderer,
# quote audit, grading and pitcher-K units must never display or consume them.
DIAGNOSTIC_ONLY_FIELDS = ("reason_detail", "blocker_detail")


def strip_diagnostics(row: Any) -> Any:
    """Copy of a row with diagnostic-only evaluation fields removed."""
    if not isinstance(row, Mapping):
        return row
    out = copy.deepcopy(dict(row))
    ev = out.get("evaluation")
    if isinstance(ev, Mapping):
        out["evaluation"] = {k: v for k, v in ev.items() if k not in DIAGNOSTIC_ONLY_FIELDS}
    return out


def _norm_key(key: str) -> str:
    return "_".join(t.lower() for t in tokens(key))


def _authority_key(key: str) -> bool:
    if key.endswith(_EXEMPT_SUFFIXES) or _EXEMPT_SEGMENT.search(key):
        return False
    return key in _AUTHORITY_FIELDS or key.endswith("_eligible") or key.endswith("_authority")


def _money_key(key: str) -> bool:
    if key.endswith(_EXEMPT_SUFFIXES) or _EXEMPT_SEGMENT.search(key):
        return False
    return key in _MONEY_FIELDS or any(p.search(key) for p in _MONEY_PATTERNS)


def _live(v: Any) -> bool:
    """Numeric (0 included) or boolean True. Strings, False and None are inert
    (t211e: refuse only numeric or boolean-truthy values)."""
    if isinstance(v, bool):
        return v
    return isinstance(v, (int, float))


# Keys the composite itself adds to a child row (stripped nowhere; allowlisted).
_COMPOSITE_ADDED_FIELDS = frozenset({"row_id", "as_of_utc", "child_run_id",
                                     "quote_age_seconds", "research_only"})
# Evaluation values that may be structured; every other evaluation value is scalar.
_STRUCTURED_EVAL_FIELDS = frozenset({"blocker_detail", "pricing_provenance", "reason_detail"})


_NESTED_PARENTS = frozenset({"evaluation", "pricing_provenance", "blocker_detail"})


def _structure_violation(obj: Mapping, parent: str) -> str | None:
    if parent == "":
        extra = {str(k) for k in obj} - _CHILD_ALLOWED_FIELDS - _COMPOSITE_ADDED_FIELDS
        if extra:
            return f"row_keys={sorted(extra)}"
    elif parent == "evaluation":
        extra = {str(k) for k in obj} - set(EVALUATION_FIELDS)
        if extra:
            return f"evaluation_keys={sorted(extra)}"
        for k, v in obj.items():
            if k not in _STRUCTURED_EVAL_FIELDS and isinstance(v, (Mapping, list, tuple)):
                return f"evaluation.{k}=NOT_SCALAR"
    return None


def authority_violation(obj: Any, _parent: str = "") -> str | None:
    """Structural fail-closed guard, recursive over mappings/lists.

    * any key matching the authority/money/EV patterns with a live value refuses;
    * status / reason / blocker values must be exact allowlisted codes;
    * pricing_provenance: key allowlist, and no truthy boolean;
    * nothing else (identity, free text, blocker_detail diagnostics) is screened."""
    if isinstance(obj, Mapping):
        hit = _structure_violation(obj, _parent)
        if hit:
            return hit
        if _parent == "pricing_provenance":
            unknown = {str(k) for k in obj} - PROVENANCE_KEYS
            if unknown:
                return f"pricing_provenance_keys={sorted(unknown)}"
        for k, v in obj.items():
            raw = str(k).strip()
            norm = _norm_key(raw)
            for key in {raw.lower(), norm}:
                if (_authority_key(key) or _money_key(key)) and _live(v):
                    return f"{k}={v}"
            if norm == "status" and v is not None and not _status_allowed(v):
                return f"status={v}"
            if norm in _CODE_KEYS and v not in (None, "") and not _code_allowed(v):
                return f"{norm}={v}"
            if _parent == "pricing_provenance" and v is True:
                return f"{k}=True"
            hit = authority_violation(v, norm if norm in _NESTED_PARENTS else "*")
            if hit:
                return hit
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            hit = authority_violation(v, _parent)
            if hit:
                return hit
    return None


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
                    context: Mapping[str, list] | None = None,
                    receipts: Mapping[str, Any] | None = None,
                    clock: Callable[[str], datetime] | None = None) -> dict:
    if evaluator is None:
        raise CompositeError("EVALUATOR_REQUIRED")
    _parse(publication_clock)  # aware ISO required; raises otherwise
    context = context or {}
    uniq, collapsed, supersessions = _dedupe(rows)
    # Complete-set binding from trusted market grammar (intake set fields ignored).
    sets, refusal = _grammar_sets(uniq)

    groups: dict[str, list[dict]] = {}
    for r in uniq:
        groups.setdefault(str(r["game_id"]), []).append(r)

    children, out_rows, refused = [], [], []
    by_id = {r["row_id"]: r for r in uniq}
    for game in sorted(groups):
        grows = sorted(groups[game], key=lambda r: str(r["row_id"]))
        evaluated_at = (clock(game) if clock else datetime.now(timezone.utc))
        evaluated_iso = evaluated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        pf_error = None
        try:
            pf = cp.preflight(grows, receipts=receipts, evaluated_at=evaluated_iso)
        except ValueError as exc:
            pf, pf_error = None, str(exc)
        as_of_iso = pf["as_of_utc"] if pf else None
        ages: dict[str, float | None] = {}
        eval_ages: dict[str, float | None] = {}
        if pf:
            for pr in pf["rows"]:
                ages[pr["row_id"]] = pr.get("quote_age_seconds")
                eval_ages[pr["row_id"]] = pr.get("quote_age_at_evaluation_seconds")
                if "refusal_code" in pr:
                    refusal.setdefault(pr["row_id"], pr["refusal_code"])
        else:
            for r in grows:
                refusal.setdefault(r["row_id"], cp._verify(r, receipts)[1]
                                   or pf_error or cp.REFUSE_NO_FINAL_VERIFICATION)
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
                extra = set(cr) - _CHILD_ALLOWED_FIELDS
                hit = authority_violation(cr)
                evd = cr.get("evaluation", {})
                bad = (sorted(set(evd) - set(EVALUATION_FIELDS)) if isinstance(evd, Mapping)
                       else "NOT_A_MAPPING")
                if hit or extra or bad:
                    codes = ([f"{CHILD_ACTIVE_STAKE}:{hit}"] if hit else []) + \
                            ([f"{CHILD_FIELD_NOT_ALLOWED}:{sorted(extra)}"] if extra else []) + \
                            ([f"{CHILD_EVALUATION_FIELD_NOT_ALLOWED}:{game}:{bad}"] if bad else [])
                    raise CompositeError(f"{game}:" + "|".join(codes))
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
                hit = authority_violation(cr)
                if hit:
                    raise CompositeError(f"{CHILD_ACTIVE_STAKE}:{src['row_id']}:{hit}")
                out_rows.append({**copy.deepcopy(dict(cr)), "row_id": src["row_id"],
                                 "as_of_utc": as_of_iso, "child_run_id": child_run_id,
                                 "quote_age_seconds": ages.get(src["row_id"]),
                                 "research_only": True})
            withheld = {}
            for w in child_out.get("withheld", []) or []:
                k = _identity_key(w)
                if k not in active_by_key or k in seen_keys:
                    raise CompositeError(f"{CHILD_UNKNOWN_ROW}:{game}:withheld")
                withheld[k] = str(w.get("code") or "")
            omitted = [r for r in active if _identity_key(r) not in seen_keys]
            if omitted:
                for r in omitted:
                    refusal[r["row_id"]] = (REFUSE_CHILD_AUTHORITY_WITHHELD
                                            if _identity_key(r) in withheld
                                            else REFUSE_CHILD_ROW_NOT_EVALUATED)
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
            "evaluated_at_utc": evaluated_iso,
            "input_digest": input_digest,
            "rows": [{"row_id": r["row_id"], "identity": row_identity_dict(r),
                      "quote_captured_at": r.get("quote_captured_at"),
                      "quote_age_seconds": ages.get(r["row_id"]),
                      "quote_age_at_evaluation_seconds": eval_ages.get(r["row_id"]),
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
            "supersessions": supersessions,
            "semantic_digest": _digest([out_rows, refused]),
            "research_only": True, "release_state": RELEASE_BLOCKED}


def verify_composite(comp: Mapping[str, Any], *, pin: str | None) -> dict:
    """Digests are unkeyed, so verification requires ``pin``: the manifest
    digest published through an independent channel when the card was built."""
    problems = []
    m = comp.get("manifest") if isinstance(comp, Mapping) else None
    if not isinstance(m, Mapping):
        return {"ok": False, "problems": ["MANIFEST_MISSING"]}
    if not pin:
        problems.append("MANIFEST_DIGEST_NOT_PINNED")
    elif _digest(m) != str(pin).lower():
        problems.append("MANIFEST_PIN_MISMATCH")
    if _digest(m) != comp.get("manifest_digest"):
        problems.append("MANIFEST_DIGEST_MISMATCH")
    if m.get("artifact_kind") != "MULTI_AS_OF_COMPOSITE":
        problems.append("ARTIFACT_KIND")
    hit = authority_violation(comp.get("rows"))
    if hit:
        problems.append(f"AUTHORITY_PROMOTION:{hit}")
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
            try:
                ev_at = _parse(c.get("evaluated_at_utc"))
            except ValueError:
                ev_at = None
            fe = check_quote_freshness(r.get("quote_captured_at"), now=ev_at) if ev_at else None
            if fe is None or not is_fresh(fe) \
                    or fe["age_seconds"] != r.get("quote_age_at_evaluation_seconds"):
                problems.append(f"ACTIVE_ROW_NOT_FRESH_AT_EVALUATION:{r.get('row_id')}")
    for r in comp.get("rows", []):
        hit = manifest_rows.get(r.get("row_id"))
        if not hit or hit[1].get("status") != "ACTIVE" \
                or hit[0].get("as_of_utc") != r.get("as_of_utc") \
                or hit[1].get("quote_captured_at") != r.get("quote_captured_at"):
            problems.append(f"ROW_NOT_IN_MANIFEST:{r.get('row_id')}")
    return {"ok": not problems, "problems": problems}


def grade_composite(comp: Mapping[str, Any], results: Mapping[str, Any], *,
                    pin: str | None) -> dict:
    v = verify_composite(comp, pin=pin)
    if not v["ok"]:
        raise CompositeError(f"{COMPOSITE_UNVERIFIED}:{v['problems']}")
    active = {r["row_id"]: strip_diagnostics(r) for r in comp["rows"]}
    for rid in results:
        if rid not in active:
            raise CompositeError(f"{GRADE_ROW_NOT_ACTIVE}:{rid}")
    legs = [{"row_id": rid, "game_id": r["game_id"], "thesis_id": r.get("thesis_id"),
             "result": results.get(rid)} for rid, r in active.items()]
    return grade_card_positions(legs)
