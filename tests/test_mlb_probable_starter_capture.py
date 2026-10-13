import copy
import json
from pathlib import Path

import pytest

from sportsedge import mlb_probable_starter_capture as c

FX = json.loads(Path(__file__).parent.joinpath("fixtures/mlb_capture_statsapi_recorded_20261013.json").read_text())
WS = FX["responses"]["2025-10-24_W"]
REG = FX["responses"]["2025-09-20_R"]


def raw(d):
    return json.dumps(d, sort_keys=True).encode()


def test_postseason_and_regular_recorded_responses_parse():
    ws = c.parse_games(WS)[0]
    assert ws["gamePk"] == 813027 and ws["gameType"] == "W" and ws["postseason"] is True
    assert ws["first_pitch_utc"] == "2025-10-25T00:00:00+00:00" and ws["away_probable_id"]
    reg = c.parse_games(REG)
    assert {g["gameType"] for g in reg} == {"R"} and not any(g["postseason"] for g in reg)
    bad = copy.deepcopy(REG)
    bad["dates"][0]["games"][0]["gameType"] = "Z"
    with pytest.raises(c.CaptureError):
        c.parse_games(bad)


def test_five_slots_keyed_to_first_pitch():
    p = c.plan_slots("2025-10-25T00:00:00Z")
    assert list(p) == ["T-24h", "T-6h", "T-90m", "T-30m", "T-5m"]
    assert p["T-5m"]["due_utc"] == "2025-10-24T23:55:00+00:00"
    assert p["T-24h"]["due_utc"] == "2025-10-24T00:00:00+00:00"


def test_actual_receipt_time_and_late_status_and_no_guarantee():
    on = c.record_snapshot(raw=raw(WS), received_at="2025-10-24T22:31:00Z", slot="T-90m", game_pk=813027)
    late = c.record_snapshot(raw=raw(WS), received_at="2025-10-24T22:45:00Z", slot="T-90m", game_pk=813027)
    after = c.record_snapshot(raw=raw(WS), received_at="2025-10-25T00:01:00Z", slot="T-5m", game_pk=813027)
    assert on["status"] == "ON_TIME" and on["received_at_utc"] == "2025-10-24T22:31:00+00:00"
    assert late["status"] == "LATE" and after["status"] == "AFTER_FIRST_PITCH"
    assert on["guarantee"] == c.GUARANTEE and on["response_sha256"] == c.sha256_bytes(raw(WS))
    assert not {"probability", "price", "eligible"} & set(on)


def test_missed_slots_recorded_including_t5():
    got = [c.record_snapshot(raw=raw(WS), received_at="2025-10-24T18:05:00Z", slot="T-6h", game_pk=813027)]
    missed = c.close_slots(got, game_pk=813027, first_pitch="2025-10-25T00:00:00Z", now="2025-10-25T00:00:00Z")
    assert {m["slot"] for m in missed} == {"T-24h", "T-90m", "T-30m", "T-5m"}
    assert all(m["status"] == "MISSED" for m in missed)


def test_starter_and_schedule_changes_detected():
    first = c.record_snapshot(raw=raw(REG), received_at="2025-09-20T11:05:00Z", slot="T-6h", game_pk=776258)
    changed = copy.deepcopy(REG)  # derived from the recorded response: starter scratched + delayed
    g = changed["dates"][0]["games"][0]
    g["teams"]["away"]["probablePitcher"] = {"id": 1, "fullName": "Replacement"}
    g["gameDate"] = "2025-09-20T18:10:00Z"
    second = c.record_snapshot(raw=raw(changed), received_at="2025-09-20T16:30:00Z", slot="T-90m",
                               game_pk=776258, prior=first)
    kinds = {x["kind"] for x in second["changes"]}
    assert kinds == {"STARTER_CHANGE", "SCHEDULE_CHANGE"}
    assert second["due_utc"] == "2025-09-20T16:40:00+00:00"  # re-keyed to new first pitch


def test_external_anchor_detects_tampering():
    recs = [c.record_snapshot(raw=raw(WS), received_at="2025-10-24T22:31:00Z", slot="T-90m", game_pk=813027)]
    anchor = c.anchor_digest(recs)
    assert c.verify(recs, anchor)
    recs[0]["received_at_utc"] = "2025-10-24T22:30:00+00:00"
    assert not c.verify(recs, anchor)
