"""RED regressions for the four #2359 integration-audit findings (owner t208u).

(1) the same offered selection captured twice under different read IDs must
    not survive dedupe as two rows;
(2) a missing/forged set_id must not bypass complete-set enforcement; sets
    are derived from trusted market grammar, never from intake set fields;
(3) a child evaluator emitting PLAY / eligible / official authority is
    refused by the permission guard, and render/grade re-check it;
(4) a self-declared re-read is not proof: every priced quote must bind to a
    pinned capture receipt whose raw sportsbook bytes contain the offer.
"""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from _capture_receipt_fixtures import receipts_for, write_store
from sportsedge import capture_preflight as cp
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


def row(rid, game, sec, *, market="TOTAL", sel="OVER", line=8.5, period="FULL",
        player=None, price=-110, read=None, **extra):
    read = read or f"read-{rid}"
    r = {"row_id": rid, "game_id": game, "book": "DK", "market": market,
         "selection": sel, "period": period, "line": line, "price": price,
         "player": player, "source_read_id": read, "quote_captured_at": iso(sec),
         "verification": {"read_id": read, "row_id": rid, "verified_at": iso(sec),
                          "reread": True}}
    r.update(extra)
    return r


def ou(p, game, s1, s2, **kw):
    return [row(p + "o", game, s1, sel="OVER", **kw), row(p + "u", game, s2, sel="UNDER", **kw)]


def echo(game_id, rows, as_of, context):
    return {"as_of_utc": as_of, "game_id": game_id,
            "rows": [{**cc.row_identity_dict(r), "game_id": r["game_id"],
                      "status": "PRICED_RESEARCH",
                      "quote_captured_at": r["quote_captured_at"]} for r in rows]}


def build(rows, *, evaluator=echo, receipts="auto"):
    if receipts == "auto":
        receipts = receipts_for(rows)
    return cc.build_composite(rows, evaluator=evaluator, revision="r",
                              publication_clock=iso(500), receipts=receipts,
                              clock=_clock_for(rows))


def refused(comp):
    return {r["row_id"]: r["refusal_code"] for r in comp["refused"]}


# ---------------- (1) same selection, different read IDs ----------------

def test_same_selection_two_read_ids_fails_closed_without_supersession():
    rows = ou("a", "G", 0, 0)
    again = row("a2", "G", 20, sel="OVER", read="read-a-second")
    with pytest.raises(cc.CompositeError, match=cc.SELECTION_CAPTURED_TWICE):
        build(rows + [again])


def test_same_selection_two_read_ids_with_price_move_fails_closed():
    rows = ou("a", "G", 0, 0)
    again = row("a2", "G", 20, sel="OVER", read="read-a-second", price=-125)
    with pytest.raises(cc.CompositeError, match=cc.SELECTION_CAPTURED_TWICE):
        build(rows + [again])


def test_declared_later_supersession_keeps_one_row_with_provenance():
    rows = ou("a", "G", 0, 0)
    newer = row("a2", "G", 20, sel="OVER", read="read-a-second",
                supersedes_read_id="read-ao")
    comp = build(rows + [newer])
    over = [r for r in comp["rows"] if r["selection"] == "OVER"]
    assert [r["row_id"] for r in over] == ["a2"]
    assert comp["supersessions"] == [{"selection_key_row": "a2", "superseded_row": "ao",
                                      "superseded_read_id": "read-ao",
                                      "superseding_read_id": "read-a-second"}]


def test_supersession_cannot_point_backwards_in_time():
    rows = ou("a", "G", 30, 30)
    older = row("a2", "G", 10, sel="OVER", read="read-a-second",
                supersedes_read_id="read-ao")
    with pytest.raises(cc.CompositeError, match=cc.SUPERSESSION_NOT_LATER):
        build(rows + [older])


def test_two_row_ids_same_read_same_selection_fails_closed():
    rows = ou("a", "G", 0, 0)
    twin = copy.deepcopy(rows[0])
    twin["row_id"] = "twin"
    twin["verification"]["row_id"] = "twin"
    with pytest.raises(cc.CompositeError, match=cc.ROW_IDENTITY_CONFLICT):
        build(rows + [twin], receipts=receipts_for(rows))


# ---------------- (2) set completeness from market grammar ----------------

def test_missing_set_id_does_not_bypass_completeness():
    lone = [row("x", "G", 0, sel="OVER")]  # no set_id at all
    assert refused(build(lone)) == {"x": cc.REFUSE_SET_INCOMPLETE}


def test_intake_set_size_cannot_prove_completeness():
    lone = [row("x", "G", 0, sel="OVER", set_id="s", set_size=1)]
    assert refused(build(lone)) == {"x": cc.REFUSE_SET_INCOMPLETE}


def test_one_side_missing_set_id_still_pairs_by_grammar():
    rows = ou("a", "G", 0, 1)
    rows[0]["set_id"], rows[0]["set_size"] = "zzz", 2  # forged on one side only
    assert not build(rows)["refused"]


def test_three_way_requires_all_three_by_grammar():
    rows = [row("h", "G", 0, market="MONEYLINE_3WAY", sel="HOME", line=None),
            row("d", "G", 0, market="MONEYLINE_3WAY", sel="DRAW", line=None)]
    assert set(refused(build(rows)).values()) == {cc.REFUSE_SET_INCOMPLETE}
    rows.append(row("w", "G", 0, market="MONEYLINE_3WAY", sel="AWAY", line=None))
    assert not build(rows)["refused"]


def test_unknown_market_grammar_refuses_by_name():
    rows = [row("m", "G", 0, market="MYSTERY_PROP", sel="YES")]
    assert refused(build(rows)) == {"m": cc.REFUSE_MARKET_SET_GRAMMAR_UNKNOWN}


def test_f5_pair_bound_by_grammar_and_120s():
    rows = ou("f", "G", 0, 121, period="FIRST_5")
    assert set(refused(build(rows)).values()) == {cc.REFUSE_F5_PAIR_SEPARATION}


def test_spread_sides_must_mirror_lines():
    rows = [row("h", "G", 0, market="SPREAD", sel="HOME", line=-1.5),
            row("a", "G", 0, market="SPREAD", sel="AWAY", line=+2.5)]
    assert set(refused(build(rows)).values()) == {cc.REFUSE_SET_INCOMPLETE}


# ---------------- (3) permission guard ----------------

@pytest.mark.parametrize("hostile", [
    {"status": "PLAY"}, {"status": "BET_NOW"}, {"status": "OFFICIAL_PICK"},
    {"eligible": True}, {"official_authority": True}, {"staking_authority": True},
    {"evaluation": {"status": "PLAY"}}, {"evaluation": {"nested": {"eligible": True}}},
    {"stake": 1.0}, {"play": True},
])
def test_hostile_child_authority_refused(hostile):
    def ev(g, rows, as_of, ctx):
        out = echo(g, rows, as_of, ctx)
        out["rows"][0].update(hostile)
        return out
    with pytest.raises(cc.CompositeError, match=cc.CHILD_ACTIVE_STAKE):
        build(ou("a", "G", 0, 1), evaluator=ev)


def test_render_and_grade_recheck_authority_after_tamper():
    from sportsedge.composite_run_it import render_composite_markdown
    comp = build(ou("a", "G", 0, 1))
    comp["rows"][0]["status"] = "PLAY"
    with pytest.raises(cc.CompositeError):
        cc.grade_composite(comp, pin=comp["manifest_digest"], results={})
    with pytest.raises(cc.CompositeError):
        render_composite_markdown(comp, pin=comp["manifest_digest"])


def test_research_statuses_pass_guard():
    def ev(g, rows, as_of, ctx):
        out = echo(g, rows, as_of, ctx)
        out["rows"][0]["status"] = "NO_VALIDATION"  # allowlisted research status
        out["rows"][1]["status"] = "BLOCKED_PREPRICING_FIXTURE_UNVERIFIED"
        return out
    assert len(build(ou("a", "G", 0, 1), evaluator=ev)["rows"]) == 2


# ---------------- (4) receipt-bound proof ----------------

def test_self_declared_reread_without_receipts_is_refused():
    rows = ou("a", "G", 0, 1)
    with pytest.raises(ValueError, match="NO_VERIFIED_ROWS"):
        cp.preflight(rows, receipts=None, evaluated_at=_ev(rows))
    comp = build(rows, receipts=None)
    assert set(refused(comp).values()) <= {cp.REFUSE_CAPTURE_RECEIPT_UNPROVEN,
                                            cc.REFUSE_SET_MEMBER_REFUSED}
    assert not comp["rows"]


def test_fabricated_receipt_id_refused():
    rows = ou("a", "G", 0, 1)
    rc = receipts_for(rows)
    rows[0]["verification"]["read_id"] = "read-fabricated"
    out = cp.preflight(rows, receipts=rc, evaluated_at=_ev(rows))
    assert {r["row_id"]: r["refusal_code"] for r in out["refused"]}["ao"] in {
        cp.REFUSE_CAPTURE_RECEIPT_UNPROVEN, cp.REFUSE_CAPTURE_RECEIPT_MISMATCH}


@pytest.mark.parametrize("field,value", [("price", -150), ("line", 9.5),
                                         ("quote_captured_at", None), ("game_id", "OTHER")])
def test_receipt_mismatch_refused(field, value):
    rows = ou("a", "G", 0, 1)
    rc = receipts_for(rows)
    if field == "quote_captured_at":
        rows[0]["quote_captured_at"] = iso(0.5)
        rows[0]["verification"]["verified_at"] = iso(0.5)
    else:
        rows[0][field] = value
    out = cp.preflight([rows[0], rows[1]] if field != "game_id" else rows, receipts=rc, evaluated_at=_ev(rows))
    codes = {r["row_id"]: r.get("refusal_code") for r in out["rows"]}
    assert codes["ao"] == cp.REFUSE_CAPTURE_RECEIPT_MISMATCH


def test_manifest_pin_mismatch_refused(tmp_path):
    root, pin = write_store(ou("a", "G", 0, 1), tmp_path)
    with pytest.raises(ValueError, match=cp.RECEIPT_MANIFEST_PIN_MISMATCH):
        cp.load_capture_receipts(root, manifest_sha256="0" * 64)


def test_tampered_receipt_file_refused(tmp_path):
    root, pin = write_store(ou("a", "G", 0, 1), tmp_path)
    p = root / "receipts" / "read-ao.json"
    d = json.loads(p.read_text())
    d["price"] = 100
    p.write_text(json.dumps(d, sort_keys=True))
    with pytest.raises(ValueError, match=cp.RECEIPT_HASH_MISMATCH):
        cp.load_capture_receipts(root, manifest_sha256=pin)


def test_tampered_raw_read_refused(tmp_path):
    root, pin = write_store(ou("a", "G", 0, 1), tmp_path)
    (root / "raw" / "read-ao.json").write_text('{"offers": []}')
    with pytest.raises(ValueError, match=cp.RECEIPT_RAW_HASH_MISMATCH):
        cp.load_capture_receipts(root, manifest_sha256=pin)


def test_raw_read_must_contain_offer(tmp_path):
    import hashlib
    root, _ = write_store(ou("a", "G", 0, 1), tmp_path)
    # Rebuild a consistent chain whose raw bytes do not contain the offer.
    raw = json.dumps({"read_id": "read-ao", "captured_at": iso(0), "offers": []},
                     sort_keys=True).encode()
    (root / "raw" / "read-ao.json").write_bytes(raw)
    rp = root / "receipts" / "read-ao.json"
    d = json.loads(rp.read_text()); d["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    rb = json.dumps(d, sort_keys=True).encode(); rp.write_bytes(rb)
    m = json.loads((root / "manifest.json").read_text())
    for e in m["receipts"]:
        if e["path"] == "receipts/read-ao.json":
            e["sha256"] = hashlib.sha256(rb).hexdigest()
    mb = json.dumps(m, sort_keys=True).encode(); (root / "manifest.json").write_bytes(mb)
    with pytest.raises(ValueError, match=cp.RECEIPT_OFFER_NOT_IN_RAW_READ):
        cp.load_capture_receipts(root, manifest_sha256=hashlib.sha256(mb).hexdigest())


def test_receipt_path_escape_refused(tmp_path):
    import hashlib
    root, _ = write_store(ou("a", "G", 0, 1), tmp_path)
    m = json.loads((root / "manifest.json").read_text())
    m["receipts"][0]["path"] = "../escape.json"
    mb = json.dumps(m, sort_keys=True).encode(); (root / "manifest.json").write_bytes(mb)
    with pytest.raises(ValueError, match=cp.RECEIPT_PATH_INVALID):
        cp.load_capture_receipts(root, manifest_sha256=hashlib.sha256(mb).hexdigest())


def test_proof_level_disclosed():
    rows = ou("a", "G", 0, 1)
    out = cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows))
    assert out["proof_level"] == cp.PROOF_PINNED_CAPTURE_RECEIPT


# ---------------- acceptance: multi-game card ----------------

def test_multi_game_card_per_game_timestamps_stale_incomplete_refused_one_position():
    rows = (ou("n", "NLCS", 20, 20, market="TEAM_TOTAL", team="LAD")
            + ou("g", "NLCS", 177, 177)
            + ou("x", "ALCS", 190, 217)
            + ou("s", "WS", 0, 0) + ou("t", "WS", 200, 200, line=9.5)
            + [row("lone", "ALCS", 200, market="PITCHER_K", player="Gerrit Cole", line=6.5)])
    comp = build(rows)
    asof = {c["game_id"]: c["as_of_utc"] for c in comp["manifest"]["children"]}
    assert asof == {"NLCS": iso(177), "ALCS": iso(217), "WS": iso(200)}
    ref = refused(comp)
    assert ref["so"] == ref["su"] == "QUOTE_STALE_OVER_180S"
    assert ref["lone"] == cc.REFUSE_SET_INCOMPLETE
    g = cc.grade_composite(comp, pin=comp["manifest_digest"], results={r["row_id"]: "LOSS" for r in comp["rows"]})
    assert g["legs"] == 8 and g["positions"] == 3 and g["losses"] == 3
