"""Wire #2359 A (capture preflight) and B (per-game composite) into RUN IT.

Research only. Nothing here changes the 180s stale bound, the 120s F5
pairing contract, immutable ``quote_captured_at`` or any gate. No stake,
PLAY, EV or probability is created here; child rows carry exactly what the
canonical ``run_full`` path produced for that game at that game's own as-of.
"""
from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from . import capture_preflight as cp
from . import composite_card as cc
from .card_correlation import grade_card_positions
from .quote_freshness import MAX_QUOTE_AGE_SECONDS, _parse, check_quote_freshness

PREFLIGHT_RAN = "CAPTURE_PREFLIGHT_RAN"
PREFLIGHT_NO_VERIFICATION_RECORDS = "CAPTURE_PREFLIGHT_NO_VERIFICATION_RECORDS_UNVERIFIED_CAPTURE"
PREFLIGHT_ALL_REFUSED = "CAPTURE_PREFLIGHT_ALL_ROWS_REFUSED"
CHILD_CARD_ROW_MISMATCH = "CHILD_CARD_ROW_MISMATCH"
K_UNIT_ALREADY_CAPTURED = "PITCHER_K_UNIT_ALREADY_CAPTURED_FIRST_PAIRED_CAPTURE_STANDS"
K_UNIT_NOT_PREGAME = "PITCHER_K_UNIT_NOT_PREGAME"
K_UNIT_FIRST_PITCH_UNKNOWN = "PITCHER_K_UNIT_FIRST_PITCH_UNKNOWN"
K_UNIT_EVENT_UNKNOWN = "PITCHER_K_UNIT_PROVIDER_EVENT_UNKNOWN"
K_UNIT_PRICE_MISSING = "PITCHER_K_UNIT_PRICE_MISSING"
K_UNIT_LATER_PAIR = "PITCHER_K_UNIT_LATER_PAIR_SAME_SUBJECT"
SUPERSEDE_NOT_LATER = "SUPERSEDE_RERUN_AS_OF_NOT_LATER"
SUPERSEDE_CONFLICT = "SUPERSEDE_CONFLICT_SAME_AS_OF"

_COMPOSITE_ONLY_KEYS = ("verification",)
# Projection of a canonical evaluated row carried into the composite. EV,
# edge, kelly and any authority fields are deliberately NOT carried.
EVALUATION_FIELDS = ("status", "reason", "blocker", "blocker_detail", "market",
                     "selection", "line", "odds_american", "estimate_p", "push_p",
                     "loss_p", "fair_american", "pricing_lane", "pricing_provenance",
                     "schema")


def _canonical_run_full():
    from artifacts.run_it_full import run_full
    return run_full


def _strip(row: Mapping[str, Any]) -> dict:
    return {k: copy.deepcopy(v) for k, v in row.items() if k not in _COMPOSITE_ONLY_KEYS}


def _empty_card(min_ev: float) -> dict:
    return {"as_of_utc": None, "min_ev": min_ev,
            "summary": {"rows": 0, "edges": 0, "status_counts": {}},
            "evaluated_rows": [], "selection_intake": [], "research_only": True}


# ---------------------------------------------------------------- A in RUN IT

def run_it_with_preflight(payload: Mapping[str, Any], *, as_of: Any = None,
                          require_verification: bool = False,
                          receipts: Mapping[str, Any] | None = None,
                          evaluated_at: Any = None,
                          run_full: Callable | None = None, **kw) -> dict:
    """Run the A capture preflight, then price only the rows it admits."""
    rf = run_full or _canonical_run_full()
    lines = list((payload.get("lines") if isinstance(payload, Mapping) else payload) or [])
    has_records = any(isinstance(r, Mapping) and "verification" in r for r in lines)
    if not has_records and not require_verification:
        card = rf(payload, as_of=as_of, **kw)
        card["capture_preflight"] = {
            "status": PREFLIGHT_NO_VERIFICATION_RECORDS, "capture_verified": False,
            "note": "intake carried no genuine final-read records; existing 180s "
                    "freshness checks still apply; capture not verified",
            "research_only": True}
        card["research_only"] = True
        return card
    if not has_records:
        card = _empty_card(kw.get("min_ev", 0.02))
        card["capture_preflight"] = {
            "status": PREFLIGHT_ALL_REFUSED, "capture_verified": False,
            "refused": [{"row_id": r.get("row_id") if isinstance(r, Mapping) else None,
                         "original_input_index": i,
                         "refusal_code": cp.REFUSE_NO_FINAL_VERIFICATION}
                        for i, r in enumerate(lines)],
            "priced_original_input_indexes": [], "research_only": True}
        return card
    pf = cp.preflight(lines, receipts=receipts, declared_as_of=as_of,
                      evaluated_at=evaluated_at or datetime.now(timezone.utc))
    refused, keep = [], []
    for i, (src, r) in enumerate(zip(lines, pf["rows"])):
        if "refusal_code" in r:
            refused.append({"row_id": r.get("row_id"), "original_input_index": i,
                            "refusal_code": r["refusal_code"],
                            "quote_age_seconds": r.get("quote_age_seconds")})
        else:
            keep.append(i)
    section = {"status": PREFLIGHT_RAN if keep else PREFLIGHT_ALL_REFUSED,
               "capture_verified": True, "as_of_utc": pf["as_of_utc"],
               "as_of_source": pf["as_of_source"], "span_seconds": pf["span_seconds"],
               "span_status": pf["span_status"], "refused": refused,
               "priced_original_input_indexes": keep,
               "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS, "research_only": True}
    if not keep:
        card = _empty_card(kw.get("min_ev", 0.02))
    else:
        base = dict(payload) if isinstance(payload, Mapping) else {}
        card = rf({**base, "lines": [_strip(lines[i]) for i in keep]},
                  as_of=pf["as_of_utc"], **kw)
    card["capture_preflight"] = section
    card["research_only"] = True
    return card


# ---------------------------------------------------------------- B evaluator

def run_full_evaluator(run_full: Callable | None = None, **kw) -> Callable:
    rf = run_full or _canonical_run_full()

    def evaluate(game_id: str, rows: list, as_of: str, context: list) -> dict:
        card = rf({"lines": [_strip(r) for r in rows]}, as_of=as_of, **kw)
        ev = card.get("evaluated_rows")
        if not isinstance(ev, list) or len(ev) != len(rows):
            raise cc.CompositeError(f"{CHILD_CARD_ROW_MISMATCH}:{game_id}")
        out = []
        for i, (src, e) in enumerate(zip(rows, ev)):
            if not isinstance(e, Mapping) or e.get("input_index", i) != i:
                raise cc.CompositeError(f"{CHILD_CARD_ROW_MISMATCH}:{game_id}")
            proj = {k: copy.deepcopy(e[k]) for k in EVALUATION_FIELDS if k in e}
            row_out = {**cc.row_identity_dict(src), "game_id": src["game_id"],
                       "quote_captured_at": src["quote_captured_at"],
                       "status": e.get("status"), "evaluation": proj}
            if src.get("thesis_id"):
                row_out["thesis_id"] = src["thesis_id"]
            out.append(row_out)
        return {"as_of_utc": as_of, "game_id": game_id, "rows": out,
                "child_card_summary": copy.deepcopy(card.get("summary"))}
    return evaluate


def run_composite(payload: Mapping[str, Any], *, revision: str, publication_clock: str,
                  context: Mapping[str, list] | None = None,
                  receipts: Mapping[str, Any] | None = None,
                  run_full: Callable | None = None, clock: Callable | None = None,
                  **kw) -> dict:
    comp = cc.build_composite(list((payload or {}).get("lines") or []),
                              evaluator=run_full_evaluator(run_full, **kw),
                              revision=revision, publication_clock=publication_clock,
                              context=context, receipts=receipts, clock=clock)
    comp["card_kind"] = "COMPOSITE_RUN_IT"
    return comp


def is_composite(card: Any) -> bool:
    return isinstance(card, Mapping) and isinstance(card.get("manifest"), Mapping) \
        and card["manifest"].get("artifact_kind") == "MULTI_AS_OF_COMPOSITE"


def _require_verified(comp: Mapping[str, Any], pin: str | None) -> None:
    v = cc.verify_composite(comp, pin=pin)
    if not v["ok"]:
        raise cc.CompositeError(f"{cc.COMPOSITE_UNVERIFIED}:{v['problems']}")


# ---------------------------------------------------------------- renderer

def _safe(v: Any) -> str:
    import re
    return re.sub(r"[\r\n\t|<>`*\[\]!]", " ", str(v if v is not None else "—")).strip()


def render_composite_markdown(comp: Mapping[str, Any], *, pin: str | None,
                              run_url: str = "") -> str:
    _require_verified(comp, pin)
    m = comp["manifest"]
    graded = cc.grade_composite(comp, {}, pin=pin)
    lines = ["## SportsEdge · RUN IT · RESEARCH ONLY", "",
             "Multi-as-of composite: each game is evaluated at its own operative as-of "
             "(its final genuine quote read). There is no single board snapshot.",
             f"Publication clock (not an operative instant): {_safe(m['publication_clock_utc'])}",
             f"Release state: {_safe(comp.get('release_state'))}",
             f"{graded['legs']} active legs grade as {graded['positions']} correlated positions.",
             ""]
    rows_by = {}
    for r in comp.get("rows", []):
        rows_by.setdefault(r["game_id"], []).append(("ACTIVE", r))
    for r in comp.get("refused", []):
        rows_by.setdefault(r["game_id"], []).append(("REFUSED", r))
    for c in m["children"]:
        g = c["game_id"]
        lines += [f"### {_safe(g)}", "", f"Operative as-of: {_safe(c['as_of_utc'])}",
                  f"Evaluated at: {_safe(c.get('evaluated_at_utc'))}", "",
                  "| Selection / market | Line | Quote age (s) | Status |",
                  "| --- | ---: | ---: | --- |"]
        ages = {r["row_id"]: r.get("quote_age_seconds") for r in c["rows"]}
        for kind, r in rows_by.get(g, []):
            name = " ".join(_safe(x) for x in (r.get("player"), r.get("market"), r.get("selection")) if x)
            status = r.get("status") if kind == "ACTIVE" else r.get("refusal_code")
            lines.append(f"| {name} | {_safe(r.get('line'))} | {_safe(ages.get(r['row_id']))} | {_safe(status)} |")
        lines.append("")
    if run_url:
        lines += [f"Run receipt: {_safe(run_url)}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- quote audit

def composite_quote_audit(comp: Mapping[str, Any], *, pin: str | None) -> dict:
    v = cc.verify_composite(comp, pin=pin)
    rows, problems = [], list(v["problems"])
    m = comp.get("manifest") or {}
    for c in m.get("children", []):
        try:
            asof = _parse(c.get("as_of_utc"))
        except ValueError:
            asof = None
        for r in c.get("rows", []):
            rec = {"row_id": r.get("row_id"), "game_id": c.get("game_id"),
                   "as_of_utc": c.get("as_of_utc"),
                   "quote_captured_at": r.get("quote_captured_at"),
                   "recorded_age_seconds": r.get("quote_age_seconds"),
                   "status": r.get("status")}
            if asof is not None:
                f = check_quote_freshness(r.get("quote_captured_at"), now=asof)
                rec["recomputed_age_seconds"] = f["age_seconds"]
                rec["freshness_code"] = f["code"]
                if r.get("quote_age_seconds") is not None and f["age_seconds"] != r["quote_age_seconds"]:
                    problems.append(f"AGE_MISMATCH:{r.get('row_id')}")
            rows.append(rec)
    return {"artifact_kind": m.get("artifact_kind"), "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
            "rows": rows, "problems": problems, "ok": not problems}


# ---------------------------------------------------------------- pitcher-K forward

def composite_pitcher_k_units(comp: Mapping[str, Any], *, first_pitch_by_game: Mapping[str, str],
                              provider_event_by_game: Mapping[str, str],
                              existing_units: Iterable[Mapping[str, Any]],
                              pin: str | None) -> dict:
    """Forward-protocol units from a verified composite: first paired capture only."""
    _require_verified(comp, pin)
    taken = {(str(u.get("provider_event_id")), str(u.get("entity_name"))) for u in existing_units}
    pairs: dict[tuple, dict] = {}
    for r in comp.get("rows", []):
        if str(r.get("market") or "").upper() != "PITCHER_K":
            continue
        side = str(r.get("selection") or "").upper()
        if side not in {"OVER", "UNDER"}:
            continue
        pairs.setdefault((r["game_id"], r.get("player"), r.get("line")), {})[side] = r
    units, skipped = [], []
    for (game, player, ln), sides in sorted(pairs.items(), key=lambda kv: str(kv[0])):
        if set(sides) != {"OVER", "UNDER"}:
            continue
        o, u = sides["OVER"], sides["UNDER"]
        observed = max((o["quote_captured_at"], u["quote_captured_at"]), key=lambda s: _parse(s))
        base = {"game_id": game, "entity_name": player, "line": ln}
        fp, ev = first_pitch_by_game.get(game), provider_event_by_game.get(game)
        if not fp:
            skipped.append({**base, "reason": K_UNIT_FIRST_PITCH_UNKNOWN}); continue
        if not ev:
            skipped.append({**base, "reason": K_UNIT_EVENT_UNKNOWN}); continue
        if _parse(o["as_of_utc"]) >= _parse(fp):
            skipped.append({**base, "reason": K_UNIT_NOT_PREGAME}); continue
        if (str(ev), str(player)) in taken:
            skipped.append({**base, "reason": K_UNIT_ALREADY_CAPTURED}); continue
        oo = (o.get("evaluation") or {}).get("odds_american")
        uo = (u.get("evaluation") or {}).get("odds_american")
        if oo is None or uo is None:
            skipped.append({**base, "reason": K_UNIT_PRICE_MISSING}); continue
        taken.add((str(ev), str(player)))
        units.append({"market": "PITCHER_K", "entity_name": player, "line": ln,
                      "over_odds": int(oo), "under_odds": int(uo), "observed_at": observed,
                      "first_pitch_at": fp, "provider_event_id": str(ev), "game_id": game,
                      "as_of_utc": o["as_of_utc"], "child_run_id": o["child_run_id"],
                      "forward_validation_evidence_only": True})
    return {"units": units, "skipped": skipped, "research_only": True}


# ---------------------------------------------------------------- rerun supersession

def supersede(composites: Iterable[Mapping[str, Any]], *, pins: Iterable[str]) -> dict:
    """Apply reruns in order; each game keeps the child with the latest as-of.
    Every composite is verified against its own externally published pin."""
    active: dict[str, tuple[dict, Mapping]] = {}
    superseded = []
    composites, pins = list(composites), list(pins)
    if len(pins) != len(composites):
        raise cc.CompositeError(f"{cc.COMPOSITE_UNVERIFIED}:PIN_COUNT")
    for comp, pin in zip(composites, pins):
        _require_verified(comp, pin)
        for c in comp["manifest"]["children"]:
            g = c["game_id"]
            if g not in active:
                active[g] = (c, comp); continue
            old = active[g][0]
            if old["child_run_id"] == c["child_run_id"]:
                continue  # identical rerun: idempotent
            oa, na = old.get("as_of_utc"), c.get("as_of_utc")
            if oa is not None and (na is None or _parse(na) < _parse(oa)):
                raise cc.CompositeError(f"{SUPERSEDE_NOT_LATER}:{g}")
            if oa is not None and _parse(na) == _parse(oa):
                raise cc.CompositeError(f"{SUPERSEDE_CONFLICT}:{g}")
            superseded.append({"game_id": g, "as_of_utc": oa, "child_run_id": old["child_run_id"],
                               "superseded_by": c["child_run_id"]})
            active[g] = (c, comp)
    rows, refused = [], []
    for g in sorted(active):
        c, comp = active[g]
        rows += [copy.deepcopy(r) for r in comp["rows"] if r["child_run_id"] == c["child_run_id"]]
        refused += [copy.deepcopy(r) for r in comp["refused"] if r["child_run_id"] == c["child_run_id"]]
    return {"active_children": [copy.deepcopy(active[g][0]) for g in sorted(active)],
            "superseded": superseded, "rows": rows, "refused": refused, "research_only": True}


def grade_chain(chain: Mapping[str, Any], results: Mapping[str, Any]) -> dict:
    active = {r["row_id"]: r for r in chain["rows"]}
    for rid in results:
        if rid not in active:
            raise cc.CompositeError(f"{cc.GRADE_ROW_NOT_ACTIVE}:{rid}")
    return grade_card_positions([{"row_id": rid, "game_id": r["game_id"],
                                  "thesis_id": r.get("thesis_id"), "result": results.get(rid)}
                                 for rid, r in active.items()])
