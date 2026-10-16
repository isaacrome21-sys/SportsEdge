"""RED battery: wire #2359 A preflight + B composite into RUN IT (research only).

* A preflight runs automatically inside the RUN IT entry before pricing.
* B's per-game evaluator drives the canonical run_full path per game.
* Renderer, quote audit, pitcher-K forward first-paired-capture units and
  rerun supersession consume the MULTI_AS_OF_COMPOSITE shape.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from artifacts import run_it_full as full
from _capture_receipt_fixtures import receipts_for
from sportsedge import composite_card as cc
from sportsedge import composite_run_it as cri
from sportsedge.phone_display import render_phone_card

import re
from datetime import datetime as _dt_
T0 = datetime(2026, 10, 15, 23, 0, 0, tzinfo=timezone.utc)
KICK = "2026-10-16T00:20:00Z"

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


def line(rid, game, sec, *, side="OVER", market="TOTAL", line_=54.5, set_id=None,
         player=None, verified=True, sport="NFL", period="FULL"):
    r = {"row_id": rid, "game_id": game, "book": "DK", "sport": sport,
         "away": f"{game} Away", "home": f"{game} Home", "market": market,
         "side": side, "selection": side, "period": period, "line": line_,
         "odds": -110, "kickoff": KICK, "player": player,
         "source_read_id": f"read-{rid}", "quote_captured_at": iso(sec)}
    if set_id:
        r["set_id"], r["set_size"] = set_id, 2
    if verified:
        r["verification"] = {"read_id": f"read-{rid}", "row_id": rid,
                             "verified_at": iso(sec), "reread": True}
    return r


def pair(p, game, s1, s2, **kw):
    kw.setdefault("line_", 0.5 + sum(map(ord, p)) % 40)
    return [line(p + "o", game, s1, side="OVER", set_id=p, **kw),
            line(p + "u", game, s2, side="UNDER", set_id=p, **kw)]


def _rp(payload, **kw):
    kw.setdefault("receipts", receipts_for(payload["lines"]))
    kw.setdefault("evaluated_at", _ev(payload["lines"]))
    return cri.run_it_with_preflight(payload, **kw)


def _rc(payload, **kw):
    kw.setdefault("receipts", receipts_for(payload["lines"]))
    kw.setdefault("clock", _clock_for(payload["lines"]))
    return cri.run_composite(payload, **kw)


class FakeRunFull:
    """Records calls; returns a minimal canonical-shaped card."""
    def __init__(self):
        self.calls = []

    def __call__(self, payload, **kw):
        self.calls.append((copy.deepcopy(payload), kw))
        rows = payload["lines"]
        return {"as_of_utc": kw.get("as_of"), "min_ev": 0.02,
                "summary": {"rows": len(rows), "edges": 0, "status_counts": {}},
                "evaluated_rows": [{"input_index": i, "status": "PRICED_RESEARCH",
                                    "market": r["market"], "selection": r["side"],
                                    "line": r["line"], "odds_american": r["odds"],
                                    "quote_captured_at": r["quote_captured_at"]}
                                   for i, r in enumerate(rows)],
                "selection_intake": [dict(r) for r in rows]}


# ---------------- A preflight inside RUN IT ----------------

def test_preflight_runs_before_pricing_and_drops_stale_rows():
    fake = FakeRunFull()
    rows = pair("tt", "G", 0, 0) + pair("gl", "G", 200, 200)
    card = _rp({"lines": rows}, run_full=fake)
    assert len(fake.calls) == 1
    priced = fake.calls[0][0]["lines"]
    assert {r["row_id"] for r in priced} == {"glo", "glu"}
    assert fake.calls[0][1]["as_of"] == iso(200)
    cp = card["capture_preflight"]
    assert cp["status"] == cri.PREFLIGHT_RAN
    assert {r["row_id"] for r in cp["refused"]} == {"tto", "ttu"}
    assert cp["priced_original_input_indexes"] == [2, 3]
    assert card["research_only"] is True
    assert all("verification" not in r for r in priced)


def test_preflight_217s_capture_still_refuses_197s_rows():
    fake = FakeRunFull()
    rows = [line("a", "G", 20), line("b", "G", 217)]
    card = _rp({"lines": rows}, run_full=fake)
    assert [r["row_id"] for r in card["capture_preflight"]["refused"]] == ["a"]


def test_preflight_declared_as_of_must_equal_final_read():
    with pytest.raises(ValueError, match="AS_OF_NOT_FINAL_VERIFICATION"):
        _rp({"lines": [line("a", "G", 0)]}, as_of=iso(30),
                                  run_full=FakeRunFull())


def test_mixed_verified_and_unverified_rows_refuse_unverified():
    fake = FakeRunFull()
    rows = [line("a", "G", 0), line("b", "G", 5, verified=False)]
    card = _rp({"lines": rows}, run_full=fake)
    assert [r["row_id"] for r in card["capture_preflight"]["refused"]] == ["b"]


def test_no_verification_records_is_disclosed_not_silently_passed():
    fake = FakeRunFull()
    rows = [line("a", "G", 0, verified=False)]
    card = _rp({"lines": rows}, run_full=fake)
    assert card["capture_preflight"]["status"] == cri.PREFLIGHT_NO_VERIFICATION_RECORDS
    assert card["capture_preflight"]["capture_verified"] is False


def test_require_verification_refuses_everything_unverified():
    fake = FakeRunFull()
    card = _rp({"lines": [line("a", "G", 0, verified=False)]},
                                     run_full=fake, require_verification=True)
    assert fake.calls == []
    assert card["capture_preflight"]["status"] == cri.PREFLIGHT_ALL_REFUSED
    assert card["evaluated_rows"] == []


def test_all_rows_refused_never_calls_pricing():
    fake = FakeRunFull()
    a = line("a", "G", 0)
    a["verification"]["reread"] = False
    with pytest.raises(ValueError, match="NO_VERIFIED_ROWS"):
        _rp({"lines": [a]}, run_full=fake)
    assert fake.calls == []


def test_cli_main_routes_through_preflight(tmp_path, monkeypatch):
    seen = {}

    def spy(payload, **kw):
        seen["kw"] = kw
        return {"capture_preflight": {}, "research_only": True}
    monkeypatch.setattr(cri, "run_it_with_preflight", spy)
    p = tmp_path / "lines.json"
    p.write_text('{"lines": []}')
    full.main(["--lines", str(p), "--no-fetch", "--output", str(tmp_path / "o.json")])
    assert seen["kw"]["require_verification"] is False
    assert seen["kw"]["auto_context"] is False


def test_cli_has_no_preflight_bypass_flag():
    import argparse
    with pytest.raises(SystemExit):
        full.main(["--lines", "x.json", "--skip-capture-preflight"])


# ---------------- B evaluator on canonical run_full ----------------

def test_run_full_evaluator_calls_canonical_path_per_game_with_own_as_of():
    fake = FakeRunFull()
    rows = pair("a", "G1", 0, 10) + pair("b", "G2", 190, 217)
    comp = _rc({"lines": rows}, run_full=fake, revision="r",
                             publication_clock=iso(300))
    as_ofs = sorted(kw["as_of"] for _, kw in fake.calls)
    assert as_ofs == [iso(10), iso(217)]
    for payload, _ in fake.calls:
        assert len({r["game_id"] for r in payload["lines"]}) == 1
    assert cc.verify_composite(comp, pin=comp["manifest_digest"])["ok"]
    assert {r["row_id"] for r in comp["rows"]} == {"ao", "au", "bo", "bu"}
    assert all(r["research_only"] for r in comp["rows"])


def test_evaluator_row_count_mismatch_fails_closed():
    def short(payload, **kw):
        card = FakeRunFull()(payload, **kw)
        card["evaluated_rows"].pop()
        return card
    with pytest.raises(cc.CompositeError, match=cri.CHILD_CARD_ROW_MISMATCH):
        _rc({"lines": pair("a", "G", 0, 1)}, run_full=short,
                          revision="r", publication_clock=iso(9))


def test_evaluator_carries_child_status_not_inventing_probability():
    comp = _rc({"lines": pair("a", "G", 0, 1)}, run_full=FakeRunFull(),
                             revision="r", publication_clock=iso(9))
    for r in comp["rows"]:
        assert r["status"] == "PRICED_RESEARCH"
        assert "stake" not in r and r.get("play") is not True


def test_real_canonical_run_full_runs_per_game_offline():
    rows = pair("a", "DET@ARI", 0, 5)
    for r in rows:
        r["away"], r["home"] = "Detroit Lions", "Arizona Cardinals"
    comp = _rc({"lines": rows}, revision="r", publication_clock=iso(60),
                             auto_context=False)
    assert cc.verify_composite(comp, pin=comp["manifest_digest"])["ok"]
    assert len(comp["rows"]) + len(comp["refused"]) == 2
    for r in comp["rows"]:
        assert r["as_of_utc"] == iso(5)
        assert r.get("status")


# ---------------- renderer ----------------

def test_renderer_reads_composite_and_discloses_per_game_as_of():
    comp = _rc({"lines": pair("a", "G1", 0, 10) + pair("b", "G2", 190, 217)
                              + pair("s", "G3", 0, 0) + pair("t", "G3", 200, 200)},
                             run_full=FakeRunFull(), revision="r", publication_clock=iso(300))
    md = render_phone_card(comp, composite_pin=comp["manifest_digest"])
    assert "RESEARCH ONLY" in md
    assert "multi-as-of" in md.lower()
    assert iso(10) in md and iso(217) in md and iso(200) in md
    assert "QUOTE_STALE_OVER_180S" in md
    assert "positions" in md.lower()


def test_renderer_refuses_tampered_composite():
    comp = _rc({"lines": pair("a", "G1", 0, 10)}, run_full=FakeRunFull(),
                             revision="r", publication_clock=iso(300))
    comp["manifest"]["children"][0]["as_of_utc"] = iso(1)
    with pytest.raises(ValueError, match=cc.COMPOSITE_UNVERIFIED):
        render_phone_card(comp, composite_pin=comp["manifest_digest"])


# ---------------- quote audit ----------------

def test_quote_audit_recomputes_every_age_from_manifest():
    comp = _rc({"lines": pair("a", "G1", 0, 10) + pair("t", "G1", 200, 200)},
                             run_full=FakeRunFull(), revision="r", publication_clock=iso(300))
    audit = cri.composite_quote_audit(comp, pin=comp["manifest_digest"])
    assert audit["artifact_kind"] == "MULTI_AS_OF_COMPOSITE"
    assert audit["max_quote_age_seconds"] == 180
    by = {r["row_id"]: r for r in audit["rows"]}
    assert by["ao"]["recomputed_age_seconds"] == 200.0
    assert by["ao"]["freshness_code"] == "QUOTE_STALE_OVER_180S"
    assert by["to"]["freshness_code"] == "QUOTE_FRESH_UNDER_180S"
    assert audit["ok"] is True


def test_quote_audit_flags_tamper():
    comp = _rc({"lines": pair("a", "G1", 0, 10)}, run_full=FakeRunFull(),
                             revision="r", publication_clock=iso(300))
    comp["manifest"]["children"][0]["rows"][0]["quote_age_seconds"] = 1.0
    assert cri.composite_quote_audit(comp, pin=comp["manifest_digest"])["ok"] is False


# ---------------- pitcher-K forward first paired capture ----------------

def k_pair(game, s1, s2, *, player="Tyler Glasnow", line_=5.5):
    return pair("k" + game, game, s1, s2, market="PITCHER_K", line_=line_,
                player=player, sport="MLB")


def test_pitcher_k_units_from_composite_first_paired_capture():
    comp = _rc({"lines": k_pair("LAD@MIL", 0, 30)}, run_full=FakeRunFull(),
                             revision="r", publication_clock=iso(300))
    units = cri.composite_pitcher_k_units(
        comp, first_pitch_by_game={"LAD@MIL": KICK},
        provider_event_by_game={"LAD@MIL": "dk-1"}, existing_units=[], pin=comp["manifest_digest"])
    assert len(units["units"]) == 1
    u = units["units"][0]
    assert u["market"] == "PITCHER_K"
    assert u["observed_at"] == iso(30)  # pair complete at its later genuine read
    assert u["over_odds"] == -110 and u["under_odds"] == -110
    assert u["line"] == 5.5 and u["entity_name"] == "Tyler Glasnow"
    assert u["as_of_utc"] == iso(30)


def test_pitcher_k_rerun_does_not_restart_or_double_count():
    comp = _rc({"lines": k_pair("LAD@MIL", 0, 30)}, run_full=FakeRunFull(),
                             revision="r", publication_clock=iso(300))
    existing = [{"provider_event_id": "dk-1", "entity_name": "Tyler Glasnow",
                 "observed_at": iso(-600)}]
    units = cri.composite_pitcher_k_units(
        comp, first_pitch_by_game={"LAD@MIL": KICK},
        provider_event_by_game={"LAD@MIL": "dk-1"}, existing_units=existing, pin=comp["manifest_digest"])
    assert units["units"] == []
    assert units["skipped"][0]["reason"] == cri.K_UNIT_ALREADY_CAPTURED


def test_pitcher_k_refused_or_unpaired_rows_not_units():
    rows = k_pair("LAD@MIL", 0, 200)  # pair separated >180 -> stale over row
    comp = _rc({"lines": rows}, run_full=FakeRunFull(), revision="r",
                             publication_clock=iso(300))
    units = cri.composite_pitcher_k_units(
        comp, first_pitch_by_game={"LAD@MIL": KICK},
        provider_event_by_game={"LAD@MIL": "dk-1"}, existing_units=[], pin=comp["manifest_digest"])
    assert units["units"] == []


def test_pitcher_k_after_first_pitch_refused():
    comp = _rc({"lines": k_pair("LAD@MIL", 0, 30)}, run_full=FakeRunFull(),
                             revision="r", publication_clock=iso(300))
    units = cri.composite_pitcher_k_units(
        comp, first_pitch_by_game={"LAD@MIL": iso(10)},
        provider_event_by_game={"LAD@MIL": "dk-1"}, existing_units=[], pin=comp["manifest_digest"])
    assert units["units"] == []
    assert units["skipped"][0]["reason"] == cri.K_UNIT_NOT_PREGAME


# ---------------- rerun supersession ----------------

def _comp(rows, pub=300):
    return _rc({"lines": rows}, run_full=FakeRunFull(), revision="r",
                             publication_clock=iso(pub))


def test_rerun_supersedes_game_with_later_as_of_and_grades_once():
    first = _comp(pair("a", "G1", 0, 10) + pair("b", "G2", 0, 10))
    rerun = _comp([dict(r, source_read_id=r["source_read_id"] + "-r2",
                        quote_captured_at=iso(100),
                        verification={**r["verification"], "read_id": r["source_read_id"] + "-r2",
                                      "verified_at": iso(100)})
                   for r in pair("a", "G1", 0, 10)], pub=400)
    chain = cri.supersede([first, rerun], pins=[x["manifest_digest"] for x in [first, rerun]])
    games = {c["game_id"]: c for c in chain["active_children"]}
    assert games["G1"]["as_of_utc"] == iso(100)
    assert games["G2"]["as_of_utc"] == iso(10)
    assert chain["superseded"][0]["game_id"] == "G1"
    g = cri.grade_chain(chain, {})
    assert g["positions"] == 2 and g["legs"] == 4


def test_rerun_with_earlier_as_of_cannot_supersede():
    first = _comp(pair("a", "G1", 0, 50))
    older = _comp(pair("a", "G1", 0, 10))
    with pytest.raises(cc.CompositeError, match=cri.SUPERSEDE_NOT_LATER):
        cri.supersede([first, older], pins=[x["manifest_digest"] for x in [first, older]])


def test_identical_rerun_is_idempotent():
    a = _comp(pair("a", "G1", 0, 10))
    b = _comp(pair("a", "G1", 0, 10), pub=900)
    chain = cri.supersede([a, b], pins=[x["manifest_digest"] for x in [a, b]])
    assert chain["superseded"] == []
    assert cri.grade_chain(chain, {})["positions"] == 1


def test_supersede_refuses_tampered_member():
    a = _comp(pair("a", "G1", 0, 10))
    a["manifest"]["children"][0]["as_of_utc"] = iso(3)
    with pytest.raises(cc.CompositeError, match=cc.COMPOSITE_UNVERIFIED):
        cri.supersede([a], pins=[x["manifest_digest"] for x in [a]])


def test_rerun_keeps_stale_refusal_against_stored_as_of():
    a = _comp(pair("s", "G1", 0, 0) + pair("t", "G1", 200, 200))
    chain = cri.supersede([a, _comp(pair("s", "G1", 0, 0) + pair("t", "G1", 200, 200), pub=999)], pins=[x["manifest_digest"] for x in [a, _comp(pair("s", "G1", 0, 0) + pair("t", "G1", 200, 200), pub=999)]])
    refused = {r["row_id"] for r in chain["refused"]}
    assert {"so", "su"} <= refused
