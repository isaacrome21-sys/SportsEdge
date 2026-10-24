"""Phase 6: promotion only under ruling 2026-10-23i; forward-only CLV/ROI tracker."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.cfb.promotion_gate import market_status, card_label
from sportsedge.sports.cfb.forward_clv_tracker import ForwardTracker, TrackerError

GATE_TODAY = {"ruling": "2026-10-23i", "split": "fit 2024 / score 2025 out of sample; market = closing no-vig",
              "markets": {"OPP:SPREAD": {"n": 917, "diff_ci95": [-0.00032, 0.00018]},
                          "OPP:TOTAL": {"n": 928, "diff_ci95": [-0.0009, 0.00482]},
                          "OPP:ML": {"n": 864, "diff_ci95": [0.00353, 0.01675]}}}


def test_no_cfb_market_passes_today():
    for m in GATE_TODAY["markets"]:
        assert market_status(GATE_TODAY, m) == "RESEARCH_ONLY"


def test_market_passes_only_when_whole_ci_below_zero():
    g = {**GATE_TODAY, "markets": {"X": {"n": 500, "diff_ci95": [-0.004, -0.0001]}}}
    assert market_status(g, "X") == "POTENTIAL_PLAY"
    g["markets"]["X"]["diff_ci95"] = [-0.004, 0.0]
    assert market_status(g, "X") == "RESEARCH_ONLY"


@pytest.mark.parametrize("bad", [{"ruling": "other"}, {"split": "in sample"}, {"markets": {}},
                                 {"markets": {"X": {"n": 50, "diff_ci95": [-1, -0.5]}}},
                                 {"markets": {"X": {"n": 500, "diff_ci95": [-0.5]}}},
                                 {"markets": {"X": {"n": 500, "diff_ci95": [0.1, -0.5]}}},
                                 {"markets": {"X": {"n": 500, "diff_ci95": ["nan", -0.5]}}}])
def test_missing_or_malformed_evidence_is_research_only(bad):
    g = {**GATE_TODAY, "markets": {"X": {"n": 500, "diff_ci95": [-0.004, -0.001]}}, **bad}
    assert market_status(g, "X") == "RESEARCH_ONLY"


def test_card_label_never_sets_play_allowed():
    lab = card_label(GATE_TODAY, "OPP:SPREAD")
    assert lab["play_allowed"] is False and lab["status_label"] == "SCREEN/NOT_VALIDATED"


NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=2)


def rec(**kw):
    r = dict(record_id="r1", market="OPP:SPREAD", side="HOME", line=-3.5, odds=-110,
             created_at=NOW.isoformat(), captured_at=NOW.isoformat(), kickoff=KO.isoformat())
    r.update(kw)
    return r


def test_accepts_forward_record():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    assert len(t.records) == 1


@pytest.mark.parametrize("bad", [
    dict(captured_at=(NOW - timedelta(seconds=1)).isoformat()),  # before its own creation
    dict(captured_at=(KO + timedelta(seconds=1)).isoformat()),   # after kickoff
    dict(captured_at=KO.isoformat()),                            # at kickoff
    dict(created_at=(NOW - timedelta(days=300)).isoformat(),
         captured_at=(NOW - timedelta(days=300)).isoformat(),
         kickoff=(NOW - timedelta(days=299)).isoformat()),       # historical backfill
    dict(created_at=(NOW + timedelta(minutes=10)).isoformat()),  # created in future
    dict(kickoff="2026-10-24T17:00:00"), dict(captured_at=None), dict(odds="x"),
])
def test_rejects_invalid_or_backfilled(bad):
    with pytest.raises(TrackerError):
        ForwardTracker().add(rec(**bad), now=NOW)


def test_duplicate_id_rejected():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    with pytest.raises(TrackerError):
        t.add(rec(), now=NOW)


def test_close_only_after_kickoff_and_clv_roi():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    with pytest.raises(TrackerError):
        t.close("r1", closing_odds=-130, closing_line=-3.5, now=NOW)
    t.close("r1", closing_odds=-130, closing_line=-3.5, now=KO + timedelta(minutes=1))
    t.settle("r1", result="WIN", now=KO + timedelta(hours=4))
    s = t.summary()
    assert s["n_settled"] == 1 and s["roi_units"] == pytest.approx(100 / 110)
    assert s["mean_clv_implied_prob"] > 0  # -110 beat a -130 close
    assert s["play_allowed"] is False


def test_settle_requires_close_and_valid_result():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    with pytest.raises(TrackerError):
        t.settle("r1", result="WIN", now=KO + timedelta(hours=4))


def test_second_settle_rejected_already_settled():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    t.close("r1", closing_odds=-120, closing_line=-3.5, now=KO + timedelta(minutes=1))
    t.settle("r1", result="WIN", now=KO + timedelta(hours=4))
    with pytest.raises(TrackerError, match="ALREADY_SETTLED"):
        t.settle("r1", result="LOSS", now=KO + timedelta(hours=5))
    assert t.summary()["roi_units"] == pytest.approx(100 / 110)


def test_settle_verifies_recorded_close_time_not_before_kickoff():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    t.close("r1", closing_odds=-120, closing_line=-3.5, now=KO + timedelta(minutes=1))
    t.records["r1"]["closed_at"] = KO - timedelta(seconds=1)  # tampered close time
    with pytest.raises(TrackerError, match="CLOSE_TIME_BEFORE_KICKOFF"):
        t.settle("r1", result="WIN", now=KO + timedelta(hours=4))


def _settled():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    t.close("r1", closing_odds=-120, closing_line=-3.5, now=KO + timedelta(minutes=1))
    t.settle("r1", result="WIN", now=KO + timedelta(hours=4))
    return t


def test_settlement_records_timestamp_and_audit_entry():
    t = _settled()
    r = t.records["r1"]
    assert r["settled_at"] == KO + timedelta(hours=4)
    assert [e["event"] for e in t.audit_history] == ["ADD", "CLOSE", "SETTLE"]


def test_second_settle_changes_nothing():
    t = _settled()
    before = (t.records["r1"]["result"], t.records["r1"]["settled_at"], list(map(dict, t.audit_history)))
    for res in ("LOSS", "WIN", "PUSH"):
        with pytest.raises(TrackerError, match="ALREADY_SETTLED"):
            t.settle("r1", result=res, now=KO + timedelta(hours=6))
    after = (t.records["r1"]["result"], t.records["r1"]["settled_at"], list(map(dict, t.audit_history)))
    assert before == after


def test_audit_history_is_append_only_view():
    t = _settled()
    hist = t.audit_history
    with pytest.raises((TypeError, AttributeError)):
        hist.append({"event": "FORGED"})
    with pytest.raises(TypeError):
        hist[0]["event"] = "FORGED"
    assert len(t.audit_history) == 3


def test_correct_settlement_appends_traceable_entry():
    t = _settled()
    when = KO + timedelta(days=1)
    t.correct_settlement("r1", supersedes_event_id=t.audit_history[2]["event_id"], result="LOSS",
                         reason="stat correction", actor="auditor-1", now=when)
    h = t.audit_history
    assert len(h) == 4 and h[2]["event"] == "SETTLE" and h[2]["result"] == "WIN"  # original untouched
    c = h[3]
    assert c["event"] == "CORRECT_SETTLEMENT" and c["supersedes_event_id"] == h[2]["event_id"]
    assert c["previous_result"] == "WIN" and c["result"] == "LOSS"
    assert c["reason"] == "stat correction" and c["actor"] == "auditor-1" and c["at"] == when
    assert t.records["r1"]["result"] == "LOSS"
    assert t.summary()["roi_units"] == pytest.approx(-1.0)


@pytest.mark.parametrize("bad", [dict(reason=""), dict(reason=None), dict(actor=""), dict(actor=None),
                                 dict(now=None), dict(result="MAYBE"), dict(result="WIN")])
def test_correct_settlement_rejects_untraceable_or_noop(bad):
    t = _settled()
    kw = dict(supersedes_event_id=t.audit_history[2]["event_id"], result="LOSS", reason="stat correction",
              actor="auditor-1", now=KO + timedelta(days=1))
    kw.update(bad)
    with pytest.raises(TrackerError):
        t.correct_settlement("r1", **kw)
    assert t.records["r1"]["result"] == "WIN" and len(t.audit_history) == 3


def test_correct_settlement_requires_prior_settlement_and_monotonic_time():
    t = ForwardTracker()
    t.add(rec(), now=NOW)
    with pytest.raises(TrackerError):
        t.correct_settlement("r1", supersedes_event_id="r1:1", result="LOSS", reason="x", actor="a",
                             now=KO + timedelta(days=1))
    t2 = _settled()
    with pytest.raises(TrackerError):
        t2.correct_settlement("r1", supersedes_event_id=t2.audit_history[2]["event_id"], result="LOSS",
                              reason="x", actor="a", now=KO + timedelta(hours=3))


# --- Correction must reference the original settlement by event id (pt266u) ---
import copy


def _settle_event(t):
    return [e for e in t.audit_history if e["event"] == "SETTLE"][0]


def test_events_have_unique_ids():
    t = _settled()
    ids = [e["event_id"] for e in t.audit_history]
    assert len(ids) == len(set(ids)) and all(isinstance(i, str) and i for i in ids)


def test_correction_references_original_by_event_id_and_original_unchanged():
    t = _settled()
    orig = copy.deepcopy(dict(_settle_event(t)))
    t.correct_settlement("r1", supersedes_event_id=orig["event_id"], result="LOSS",
                         reason="stat correction", actor="auditor-1", now=KO + timedelta(days=1))
    hist = t.audit_history
    assert dict(_settle_event(t)) == orig  # deep-equal, never modified
    corr = [e for e in hist if e["event"] == "CORRECT_SETTLEMENT"]
    assert len(corr) == 1 and corr[0]["supersedes_event_id"] == orig["event_id"]
    assert {e["event_id"] for e in hist} >= {orig["event_id"], corr[0]["event_id"]}
    assert len(hist) == 4


@pytest.mark.parametrize("ref", [None, "", "nonexistent", "r1:0", "r1:1"])
def test_correction_with_bad_or_nonexistent_reference_refused(ref):
    t = _settled()
    before = copy.deepcopy([dict(e) for e in t.audit_history])
    with pytest.raises(TrackerError):
        t.correct_settlement("r1", supersedes_event_id=ref, result="LOSS", reason="x", actor="a",
                             now=KO + timedelta(days=1))
    assert [dict(e) for e in t.audit_history] == before and t.records["r1"]["result"] == "WIN"


@pytest.mark.parametrize("missing", ["reason", "actor", "now"])
def test_correction_missing_reason_actor_timestamp_refused(missing):
    t = _settled()
    kw = dict(supersedes_event_id=_settle_event(t)["event_id"], result="LOSS", reason="x", actor="a",
              now=KO + timedelta(days=1))
    kw.pop(missing)
    with pytest.raises((TrackerError, TypeError)):
        t.correct_settlement("r1", **kw)
    assert t.records["r1"]["result"] == "WIN" and len(t.audit_history) == 3


def test_second_correction_must_reference_latest_correction():
    t = _settled()
    sid = _settle_event(t)["event_id"]
    t.correct_settlement("r1", supersedes_event_id=sid, result="LOSS", reason="x", actor="a",
                         now=KO + timedelta(days=1))
    with pytest.raises(TrackerError):  # stale reference to already-superseded original
        t.correct_settlement("r1", supersedes_event_id=sid, result="PUSH", reason="y", actor="b",
                             now=KO + timedelta(days=2))
    cid = t.audit_history[-1]["event_id"]
    t.correct_settlement("r1", supersedes_event_id=cid, result="PUSH", reason="y", actor="b",
                         now=KO + timedelta(days=2))
    assert len(t.audit_history) == 5 and t.records["r1"]["result"] == "PUSH"
