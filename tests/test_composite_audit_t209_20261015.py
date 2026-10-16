"""RED regressions for the independent t209 audit of #2359 A/B + wiring.

* manifest digests are unkeyed -> verification requires an external pin;
* child evaluator top-level fields are allowlisted;
* same-game legs with distinct thesis_ids still form ONE position;
* game keys are normalised ('NYY@BOS' == 'NYY @ BOS');
* A ages are measured against the evaluation (wall-clock) instant too;
* the re-read is bound to the raw read bytes hash.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from _capture_receipt_fixtures import receipts_for
from sportsedge import capture_preflight as cp
from sportsedge import composite_card as cc
from sportsedge.card_correlation import grade_card_positions

T0 = datetime(2026, 10, 15, 23, 0, 0, tzinfo=timezone.utc)


def iso(sec):
    return (T0 + timedelta(seconds=sec)).isoformat().replace("+00:00", "Z")


def row(rid, game, sec, *, sel="OVER", line=8.5, market="TOTAL", read=None):
    read = read or f"read-{rid}"
    return {"row_id": rid, "game_id": game, "book": "DK", "market": market,
            "selection": sel, "period": "FULL", "line": line, "price": -110,
            "player": None, "source_read_id": read, "quote_captured_at": iso(sec),
            "verification": {"read_id": read, "row_id": rid, "verified_at": iso(sec),
                             "reread": True}}


def ou(p, game, s1, s2, line=8.5):
    return [row(p + "o", game, s1, sel="OVER", line=line),
            row(p + "u", game, s2, sel="UNDER", line=line)]


def echo(game_id, rows, as_of, ctx):
    return {"as_of_utc": as_of, "game_id": game_id,
            "rows": [{**cc.row_identity_dict(r), "game_id": r["game_id"],
                      "status": "PRICED_RESEARCH", "quote_captured_at": r["quote_captured_at"],
                      "evaluation": {"model_p": 0.52}} for r in rows]}


def clock_at(sec_by_game):
    return lambda game: T0 + timedelta(seconds=sec_by_game[game])


def build(rows, *, evaluator=echo, clock=None):
    rc = receipts_for(rows)
    if clock is None:
        finals = {}
        for r in rows:
            finals[r["game_id"].replace(" ", "")] = max(
                finals.get(r["game_id"].replace(" ", ""), -1e9),
                (datetime.fromisoformat(r["quote_captured_at"].replace("Z", "+00:00")) - T0).total_seconds())
        clock = lambda g: T0 + timedelta(seconds=finals[g])
    return cc.build_composite(rows, evaluator=evaluator, revision="r",
                              publication_clock=iso(900), receipts=rc, clock=clock)


# ---------- external pin ----------

def test_tampered_model_p_with_recomputed_digests_fails_against_pin():
    comp = build(ou("a", "G", 0, 1))
    pin = comp["manifest_digest"]
    forged = copy.deepcopy(comp)
    forged["rows"][0]["evaluation"]["model_p"] = 0.99
    forged["manifest"]["composite_rows_digest"] = cc._digest(forged["rows"])
    forged["semantic_digest"] = cc._digest([forged["rows"], forged["refused"]])
    forged["manifest_digest"] = cc._digest(forged["manifest"])
    assert cc.verify_composite(forged, pin=pin)["ok"] is False
    assert cc.verify_composite(comp, pin=pin)["ok"] is True


def test_unpinned_verification_fails_closed():
    comp = build(ou("a", "G", 0, 1))
    v = cc.verify_composite(comp, pin=None)
    assert v["ok"] is False and "MANIFEST_DIGEST_NOT_PINNED" in v["problems"]


def test_grade_requires_pin():
    comp = build(ou("a", "G", 0, 1))
    with pytest.raises(cc.CompositeError, match=cc.COMPOSITE_UNVERIFIED):
        cc.grade_composite(comp, {}, pin="0" * 64)
    assert cc.grade_composite(comp, {}, pin=comp["manifest_digest"])["positions"] == 1


# ---------- child field allowlist ----------

@pytest.mark.parametrize("extra", [{"ev_per_dollar": 0.4}, {"kelly": 0.1}, {"note": "x"}])
def test_child_extra_top_level_field_refused(extra):
    def ev(g, rows, as_of, ctx):
        out = echo(g, rows, as_of, ctx)
        out["rows"][0].update(extra)
        return out
    with pytest.raises(cc.CompositeError, match=cc.CHILD_FIELD_NOT_ALLOWED):
        build(ou("a", "G", 0, 1), evaluator=ev)


# ---------- thesis cannot split a game ----------

def test_same_game_distinct_theses_are_one_position():
    rows = [{"game_id": "G1", "selection": "a", "thesis_id": "T1", "result": "LOSS"},
            {"game_id": "G1", "selection": "b", "thesis_id": "T2", "result": "LOSS"}]
    assert grade_card_positions(rows)["positions"] == 1


def test_thesis_still_joins_across_games_transitively():
    rows = [{"game_id": "G1", "selection": "a", "thesis_id": "T"},
            {"game_id": "G2", "selection": "b", "thesis_id": "T"},
            {"game_id": "G2", "selection": "c", "thesis_id": "U"},
            {"game_id": "G3", "selection": "d"}]
    assert grade_card_positions(rows)["positions"] == 2


# ---------- game key normalisation ----------

def test_game_keys_normalised_for_grading():
    rows = [{"game_id": "NYY@BOS", "selection": "a"}, {"game_id": "nyy @ bos", "selection": "b"}]
    assert grade_card_positions(rows)["positions"] == 1


def test_game_keys_normalised_for_composite_grouping_and_dedupe():
    rows = ou("a", "NYY@BOS", 0, 1)
    rows[1]["game_id"] = "NYY @ BOS"
    comp = build(rows)
    assert len(comp["manifest"]["children"]) == 1
    assert not comp["refused"]
    again = row("dup", " nyy@bos ", 5, sel="OVER", read="read-other")
    with pytest.raises(cc.CompositeError, match=cc.SELECTION_CAPTURED_TWICE):
        build(rows + [again])


# ---------- A: evaluation-clock ages ----------

def test_preflight_refuses_rows_stale_at_evaluation_instant():
    rows = [row("a", "G", 0), row("b", "G", 60)]
    out = cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=iso(200))
    codes = {r["row_id"]: r.get("refusal_code") for r in out["rows"]}
    assert codes["a"] == cp.QUOTE_STALE_AT_EVALUATION
    assert codes["b"] is None
    assert out["evaluated_at_utc"] == iso(200)


def test_preflight_requires_evaluation_instant_and_refuses_future_capture():
    rows = [row("a", "G", 0)]
    with pytest.raises(TypeError):
        cp.preflight(rows, receipts=receipts_for(rows))
    with pytest.raises(ValueError, match="EVALUATED_BEFORE_FINAL_READ"):
        cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=iso(-1))


def test_composite_child_evaluated_late_refuses_stale_rows():
    rows = ou("a", "G1", 0, 10) + ou("b", "G2", 190, 217, line=9.5)
    comp = build(rows, clock=clock_at({"G1": 300, "G2": 220}))
    ref = {r["row_id"]: r["refusal_code"] for r in comp["refused"]}
    assert ref["ao"] == ref["au"] == cp.QUOTE_STALE_AT_EVALUATION
    assert {r["row_id"] for r in comp["rows"]} == {"bo", "bu"}
    ev = {c["game_id"]: c["evaluated_at_utc"] for c in comp["manifest"]["children"]}
    assert ev == {"G1": iso(300), "G2": iso(220)}


def test_oct15_slate_per_game_evaluation_still_prices_each_fresh_game():
    rows = ou("a", "G1", 20, 20) + ou("b", "G2", 190, 217, line=9.5)
    comp = build(rows, clock=clock_at({"G1": 30, "G2": 220}))
    assert {r["row_id"] for r in comp["rows"]} == {"ao", "au", "bo", "bu"}


# ---------- reread bound to raw bytes ----------

def test_verification_must_carry_receipt_raw_hash():
    rows = [row("a", "G", 0), row("z", "G", 1)]
    rc = receipts_for(rows)
    rows[0]["verification"]["raw_sha256"] = "0" * 64
    out = cp.preflight(rows, receipts=rc, evaluated_at=iso(1))
    codes = {r["row_id"]: r.get("refusal_code") for r in out["rows"]}
    assert codes["a"] == cp.REFUSE_CAPTURE_RECEIPT_MISMATCH


def test_verification_without_raw_hash_refused():
    rows = [row("a", "G", 0), row("z", "G", 1)]
    rc = receipts_for(rows)
    del rows[0]["verification"]["raw_sha256"]
    out = cp.preflight(rows, receipts=rc, evaluated_at=iso(1))
    codes = {r["row_id"]: r.get("refusal_code") for r in out["rows"]}
    assert codes["a"] == cp.REFUSE_CAPTURE_RECEIPT_UNPROVEN
