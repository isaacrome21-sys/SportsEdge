"""RED battery for #2359 B: per-game composite RUN IT card (research only).

Covers the acceptance list: Oct 15 replay, boundaries, multi-game 217s slate,
F5/3-way/set completeness, duplicate/conflict, mixed-as-of and cross-game
children, PIT context, manifest tamper, reruns, idempotent rebuild, clustered
grading and the research-only release gate.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from _capture_receipt_fixtures import receipts_for
from sportsedge import composite_card as cc

import re
from datetime import datetime as _dt_
T0 = datetime(2026, 10, 15, 23, 0, 0, tzinfo=timezone.utc)

def _ev(rows):
    from datetime import datetime as _dt
    best = None
    for r in rows:
        if not isinstance(r.get("verification"), dict):
            continue
        try:
            t = _dt.fromisoformat(str(r["quote_captured_at"]).replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if t.tzinfo is None:
            continue
        best = t if best is None or t > best else best
    return (best or T0).isoformat()


def _clock_for(rows):
    finals = {}
    for r in rows:
        g = re.sub(r"\s+", "", str(r.get("game_id"))).upper()
        try:
            t = _dt_.fromisoformat(str(r["quote_captured_at"]).replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if t.tzinfo is None or not isinstance(r.get("verification"), dict):
            continue
        finals[g] = max(finals.get(g, t), t)
    return lambda g: finals.get(g, T0)



def iso(sec):
    return (T0 + timedelta(seconds=sec)).isoformat().replace("+00:00", "Z")


def row(rid, game, sec, *, market="total", sel="over", line=8.5, period="FULL",
        set_id=None, set_size=None, player=None, price=-110):
    r = {"row_id": rid, "game_id": game, "book": "DK", "market": market,
         "selection": sel, "period": period, "line": line, "price": price,
         "player": player, "source_read_id": f"read-{rid}",
         "quote_captured_at": iso(sec),
         "verification": {"read_id": f"read-{rid}", "row_id": rid,
                          "verified_at": iso(sec), "reread": True}}
    if set_id:
        r["set_id"], r["set_size"] = set_id, set_size
    return r


def pair(prefix, game, s1, s2, **kw):
    kw.setdefault("line", 0.5 + sum(map(ord, prefix)) % 40)
    return [row(prefix + "o", game, s1, sel="over", set_id=prefix, set_size=2, **kw),
            row(prefix + "u", game, s2, sel="under", set_id=prefix, set_size=2, **kw)]


def echo_eval(game_id, rows, as_of, context):
    return {"as_of_utc": as_of, "game_id": game_id,
            "rows": [{**cc.row_identity_dict(r), "game_id": r["game_id"],
                      "status": "RESEARCH_ESTIMATE", "quote_captured_at": r["quote_captured_at"]}
                     for r in rows]}


def build(rows, **kw):
    kw.setdefault("evaluator", echo_eval)
    kw.setdefault("revision", "deadbeef")
    kw.setdefault("publication_clock", iso(400))
    kw.setdefault("receipts", receipts_for(rows))
    kw.setdefault("clock", _clock_for(rows))
    return cc.build_composite(rows, **kw)


def statuses(comp):
    return {r["row_id"]: r for r in comp["refused"]}


# --- Oct 15 replay --------------------------------------------------------

def oct15_rows():
    # NLCS game: team totals + first inning read at t=20, game lines t=177,
    # pitchers t=136; a second game (ALCS) read t=190..217.
    return (pair("tt", "NLCS", 20, 20, market="team_total")
            + pair("gl", "NLCS", 177, 177, market="total")
            + pair("al", "ALCS", 190, 217, market="total"))


def test_single_as_of_slate_refuses_197s_rows():
    _r = oct15_rows()
    single = cc.single_as_of_preflight(_r, receipts=receipts_for(_r), evaluated_at=iso(217))
    refused = {r["row_id"] for r in single["refused"]}
    assert {"tto", "ttu"} <= refused


def test_per_game_grouping_prices_fresh_but_stale_within_game_still_refuses():
    comp = build(oct15_rows())
    by_game = {c["game_id"]: c for c in comp["manifest"]["children"]}
    assert by_game["NLCS"]["as_of_utc"] == iso(177)
    assert by_game["ALCS"]["as_of_utc"] == iso(217)
    # NLCS team totals are 157s old against NLCS's own final read: fresh.
    priced = {r["row_id"] for r in comp["rows"]}
    assert {"tto", "ttu", "glo", "glu", "alo", "alu"} == priced


def test_single_game_spanning_over_180s_still_refuses():
    rows = pair("tt", "NLCS", 0, 0, market="team_total") + pair("gl", "NLCS", 200, 200)
    comp = build(rows)
    ref = statuses(comp)
    assert ref["tto"]["refusal_code"] == "QUOTE_STALE_OVER_180S"
    assert ref["ttu"]["refusal_code"] == "QUOTE_STALE_OVER_180S"
    assert {r["row_id"] for r in comp["rows"]} == {"glo", "glu"}


def test_boundaries_180_000_fresh_180_001_stale_per_game():
    comp = build(pair("a", "G", 0, 0) + pair("b", "G", 180, 180))
    assert not comp["refused"]
    comp = build(pair("a", "G", 0, 0) + pair("b", "G", 180.001, 180.001))
    assert set(statuses(comp)) == {"ao", "au"}


def test_naive_timezone_refuses():
    rows = pair("a", "G", 0, 0)
    rows[0]["quote_captured_at"] = "2026-10-15T23:00:00"
    rows[0]["verification"]["verified_at"] = "2026-10-15T23:00:00"
    comp = build(rows)
    ref = statuses(comp)
    assert ref["ao"]["refusal_code"].startswith("QUOTE_TIMESTAMP_INVALID")
    assert ref["au"]["refusal_code"] == cc.REFUSE_SET_MEMBER_REFUSED


# --- set binding ------------------------------------------------------------

def test_f5_pair_over_120s_separation_refuses():
    rows = pair("f", "G", 0, 121, period="FIRST_5")
    ref = statuses(build(rows))
    assert ref["fo"]["refusal_code"] == cc.REFUSE_F5_PAIR_SEPARATION
    rows = pair("f", "G", 0, 120, period="FIRST_5")
    assert not build(rows)["refused"]


def test_incomplete_pair_and_three_way_refuse_by_name():
    rows = [row("x", "G", 0, set_id="ml3", set_size=3, market="MONEYLINE_3WAY", sel="HOME"),
            row("y", "G", 1, set_id="ml3", set_size=3, market="MONEYLINE_3WAY", sel="DRAW")]
    ref = statuses(build(rows))
    assert ref["x"]["refusal_code"] == cc.REFUSE_SET_INCOMPLETE
    assert ref["y"]["refusal_code"] == cc.REFUSE_SET_INCOMPLETE


def test_set_split_across_games_refuses():
    rows = pair("s", "G1", 0, 1)
    rows[1]["game_id"] = "G2"
    ref = statuses(build(rows))
    assert set(ref) == {"so", "su"}


# --- duplicates / identity ---------------------------------------------------

def test_exact_duplicate_is_idempotent():
    rows = pair("a", "G", 0, 1)
    comp = build(rows + [copy.deepcopy(rows[0])])
    assert len(comp["rows"]) == 2
    assert comp["duplicates_collapsed"] == 1


def test_conflicting_same_identity_fails_closed():
    rows = pair("a", "G", 0, 1)
    bad = copy.deepcopy(rows[0])
    bad["price"] = -150
    with pytest.raises(cc.CompositeError, match=cc.ROW_IDENTITY_CONFLICT):
        build(rows + [bad])


def test_missing_identity_field_fails_closed():
    rows = pair("a", "G", 0, 1)
    del rows[0]["market"]
    with pytest.raises(cc.CompositeError, match=cc.ROW_IDENTITY_INCOMPLETE):
        build(rows)


# --- child contamination ----------------------------------------------------

def test_child_with_mixed_as_of_fails_closed():
    def ev(g, rows, as_of, ctx):
        out = echo_eval(g, rows, as_of, ctx)
        out["as_of_utc"] = iso(999)
        return out
    with pytest.raises(cc.CompositeError, match=cc.CHILD_MIXED_AS_OF):
        build(pair("a", "G", 0, 1), evaluator=ev)


def test_child_cross_game_contamination_fails_closed():
    def ev(g, rows, as_of, ctx):
        out = echo_eval(g, rows, as_of, ctx)
        out["rows"][0]["game_id"] = "OTHER"
        return out
    with pytest.raises(cc.CompositeError, match=cc.CHILD_CROSS_GAME):
        build(pair("a", "G", 0, 1), evaluator=ev)


def test_child_inventing_row_fails_closed():
    def ev(g, rows, as_of, ctx):
        out = echo_eval(g, rows, as_of, ctx)
        out["rows"].append({**out["rows"][0], "selection": "invented"})
        return out
    with pytest.raises(cc.CompositeError, match=cc.CHILD_UNKNOWN_ROW):
        build(pair("a", "G", 0, 1), evaluator=ev)


def test_child_rewriting_timestamp_fails_closed():
    def ev(g, rows, as_of, ctx):
        out = echo_eval(g, rows, as_of, ctx)
        out["rows"][0]["quote_captured_at"] = as_of
        return out
    with pytest.raises(cc.CompositeError, match=cc.TIMESTAMP_MUTATED):
        build(pair("a", "G", 0, 1), evaluator=ev)


# --- PIT context --------------------------------------------------------------

def test_context_after_as_of_or_other_game_refuses_child():
    rows = pair("a", "G", 0, 10) + pair("b", "H", 0, 10)
    ctx = {"G": [{"kind": "lineup", "game_id": "G", "source_timestamp": iso(11)}],
           "H": [{"kind": "lineup", "game_id": "G", "source_timestamp": iso(5)}]}
    comp = build(rows, context=ctx)
    ref = statuses(comp)
    assert ref["ao"]["refusal_code"] == cc.REFUSE_CONTEXT_AFTER_AS_OF
    assert ref["bo"]["refusal_code"] == cc.REFUSE_CONTEXT_CROSS_GAME
    assert not comp["rows"]


def test_context_without_timestamp_refuses():
    ctx = {"G": [{"kind": "injury", "game_id": "G"}]}
    ref = statuses(build(pair("a", "G", 0, 1), context=ctx))
    assert ref["ao"]["refusal_code"] == cc.REFUSE_CONTEXT_UNGROUNDED


def test_context_scoped_to_child():
    seen = {}
    def ev(g, rows, as_of, ctx):
        seen[g] = ctx
        return echo_eval(g, rows, as_of, ctx)
    ctx = {"G": [{"kind": "lineup", "game_id": "G", "source_timestamp": iso(0)}],
           "H": [{"kind": "lineup", "game_id": "H", "source_timestamp": iso(0)}]}
    build(pair("a", "G", 0, 1) + pair("b", "H", 0, 1), context=ctx, evaluator=ev)
    assert all(c["game_id"] == "G" for c in seen["G"])
    assert all(c["game_id"] == "H" for c in seen["H"])


# --- manifest / audit-schema ---------------------------------------------------

def test_manifest_schema_and_multi_as_of_disclosure():
    comp = build(oct15_rows())
    m = comp["manifest"]
    assert m["artifact_kind"] == "MULTI_AS_OF_COMPOSITE"
    assert m["publication_clock_utc"] == iso(400)
    assert "as_of_utc" not in m  # no false global world-state
    for c in m["children"]:
        for k in ("child_run_id", "input_digest", "game_id", "as_of_utc",
                  "rows", "child_output_digest", "context_digest",
                  "revision", "status"):
            assert k in c
        for r in c["rows"]:
            assert set(r) >= {"identity", "quote_captured_at", "quote_age_seconds"}
    assert cc.verify_composite(comp, pin=comp["manifest_digest"])["ok"] is True


def test_third_party_recomputes_every_age():
    comp = build(oct15_rows())
    for c in comp["manifest"]["children"]:
        asof = datetime.fromisoformat(c["as_of_utc"].replace("Z", "+00:00"))
        for r in c["rows"]:
            cap = datetime.fromisoformat(r["quote_captured_at"].replace("Z", "+00:00"))
            assert round((asof - cap).total_seconds(), 3) == r["quote_age_seconds"]


@pytest.mark.parametrize("mutate", [
    lambda m: m["children"][0]["rows"][0].__setitem__("quote_captured_at", iso(100)),
    lambda m: m["children"][0].__setitem__("as_of_utc", iso(500)),
    lambda m: m["children"][0].__setitem__("child_output_digest", "0" * 64),
    lambda m: m.__setitem__("publication_clock_utc", iso(1)),
    lambda m: m["children"].pop(),
])
def test_tampered_manifest_fails_closed(mutate):
    comp = build(oct15_rows())
    mutate(comp["manifest"])
    v = cc.verify_composite(comp, pin=comp["manifest_digest"])
    assert v["ok"] is False


def test_missing_manifest_fails_closed():
    comp = build(oct15_rows())
    del comp["manifest"]
    assert cc.verify_composite(comp, pin=comp["manifest_digest"])["ok"] is False


def test_rerun_recomputes_against_stored_as_of_and_stays_stale():
    rows = pair("tt", "G", 0, 0) + pair("gl", "G", 200, 200)
    a = build(rows)
    b = build(rows, publication_clock=iso(9000))
    assert statuses(a).keys() == statuses(b).keys() == {"tto", "ttu"}
    assert [c["as_of_utc"] for c in a["manifest"]["children"]] == \
           [c["as_of_utc"] for c in b["manifest"]["children"]]


def test_idempotent_rebuild_identical_semantic_rows():
    a = build(oct15_rows())
    b = build(list(reversed(oct15_rows())))
    assert a["semantic_digest"] == b["semantic_digest"]
    assert a["rows"] == b["rows"]


# --- grading ------------------------------------------------------------------

def test_grading_clusters_same_game_across_merged_composite():
    comp = build(oct15_rows())
    results = {r["row_id"]: "LOSS" for r in comp["rows"]}
    g = cc.grade_composite(comp, pin=comp["manifest_digest"], results=results)
    assert g["legs"] == 6
    assert g["positions"] == 2  # NLCS cluster + ALCS cluster
    assert g["losses"] == 2
    assert g["accounting"] == "CORRELATED_STACK_AS_SINGLE_POSITION"


def test_grading_duplicate_rows_not_double_counted():
    rows = oct15_rows()
    comp = build(rows + [copy.deepcopy(rows[0])])
    g = cc.grade_composite(comp, pin=comp["manifest_digest"], results={r["row_id"]: "WIN" for r in comp["rows"]})
    assert g["legs"] == 6 and g["positions"] == 2


def test_grading_refuses_unverified_composite():
    comp = build(oct15_rows())
    comp["manifest"]["children"][0]["as_of_utc"] = iso(1)
    with pytest.raises(cc.CompositeError, match=cc.COMPOSITE_UNVERIFIED):
        cc.grade_composite(comp, pin=comp["manifest_digest"], results={})


def test_grading_rejects_results_for_refused_or_unknown_rows():
    comp = build(pair("tt", "G", 0, 0) + pair("gl", "G", 200, 200))
    with pytest.raises(cc.CompositeError, match=cc.GRADE_ROW_NOT_ACTIVE):
        cc.grade_composite(comp, pin=comp["manifest_digest"], results={"tto": "WIN"})


# --- release gate ---------------------------------------------------------------

def test_release_stays_research_only_until_all_regressions_pass():
    comp = build(oct15_rows())
    assert comp["research_only"] is True
    assert comp["release_state"] == cc.RELEASE_BLOCKED
    partial = cc.release_state({"audit_schema", "freshness"})
    assert partial["state"] == cc.RELEASE_BLOCKED
    assert set(partial["missing"]) == {"pit_context", "dedup", "grading"}
    full = cc.release_state(set(cc.REQUIRED_REGRESSIONS))
    assert full["state"] == cc.RELEASE_RESEARCH_ONLY_REGRESSIONS_PASSED
    assert full["research_only"] is True
    for r in comp["rows"]:
        assert "stake" not in r and r.get("play") is not True


def test_required_regressions_named():
    assert set(cc.REQUIRED_REGRESSIONS) == {"audit_schema", "pit_context", "freshness", "dedup", "grading"}


# --- audit follow-ups ------------------------------------------------------------

def test_child_omitting_active_row_refuses_it_and_its_set_by_name():
    def ev(g, rows, as_of, ctx):
        out = echo_eval(g, rows, as_of, ctx)
        drop = next(i for i, r in enumerate(out["rows"]) if r["selection"] == "under")
        out["rows"].pop(drop)
        return out
    comp = build(pair("a", "G", 0, 1) + pair("s", "G", 2, 2), evaluator=ev)
    ref = statuses(comp)
    assert ref["au"]["refusal_code"] == cc.REFUSE_CHILD_ROW_NOT_EVALUATED
    assert ref["ao"]["refusal_code"] == cc.REFUSE_SET_MEMBER_REFUSED
    assert {r["row_id"] for r in comp["rows"]} == {"so", "su"}
    assert cc.verify_composite(comp, pin=comp["manifest_digest"])["ok"] is True


def test_boolean_set_size_is_not_a_complete_set():
    rows = [row("x", "G", 0, set_id="s", set_size=True)]
    assert statuses(build(rows))["x"]["refusal_code"] == cc.REFUSE_SET_INCOMPLETE
