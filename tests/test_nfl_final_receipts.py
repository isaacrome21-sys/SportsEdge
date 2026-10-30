"""NFL ESPN final receipts: raw provenance and exact event identity."""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from sportsedge.nfl_final_receipts import (
    FinalReceiptError, bind_espn_final, scoreboard_url,
)

KICKOFF = "2026-10-25T17:00:00+00:00"
FETCHED = "2026-10-25T20:30:00+00:00"


def payload(*, away="PIT", home="NO", status="STATUS_FINAL", complete=True,
            kickoff=KICKOFF, score_a="21", score_h="24", event_id="4011234"):
    return json.dumps({"events": [{
        "id": event_id, "date": kickoff,
        "status": {"type": {"completed": complete, "name": status}},
        "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"abbreviation": away}, "score": score_a},
            {"homeAway": "home", "team": {"abbreviation": home}, "score": score_h},
        ]}],
    }]}).encode()


def bind(raw=None, **fields):
    params = dict(raw=payload() if raw is None else raw,
                  source_url=scoreboard_url(KICKOFF),
                  fetched_at=FETCHED, away="PIT", home="NO", kickoff=KICKOFF)
    params.update(fields)
    return bind_espn_final(**params)


def test_final_receipt_binds_real_bytes_and_exact_fixture():
    raw = payload()
    record = bind(raw)
    assert record["event_id"] == "4011234"
    assert (record["away_points"], record["home_points"]) == (21, 24)
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["url"].startswith("https://site.api.espn.com/")
    assert record["fetched_at"] == FETCHED
    assert record["status"] == "PAPER" and record["pricing_input"] is False


@pytest.mark.parametrize("changes,reason", [
    ({"source_url": "https://attacker.example/scoreboard"}, "FINAL_SOURCE_URL_MISMATCH"),
    ({"fetched_at": KICKOFF}, "FINAL_FETCH_PREKICKOFF"),
    ({"fetched_at": "2026-10-25T20:30:00"}, "FINAL_TIME_OFFSET_REQUIRED"),
    ({"raw": b"bad"}, "FINAL_JSON_INVALID"),
    ({"raw": payload(status="STATUS_IN_PROGRESS", complete=False)}, "FINAL_NOT_COMPLETED"),
    ({"raw": payload(kickoff="2026-10-25T17:05:00Z")}, "FINAL_KICKOFF_MISMATCH"),
    ({"raw": payload(away="SEA")}, "FINAL_MATCH_MISSING_OR_AMBIGUOUS"),
    ({"raw": payload(score_a="NaN")}, "FINAL_POINTS_INVALID"),
    ({"raw": payload(score_h="-1")}, "FINAL_POINTS_INVALID"),
    ({"raw": payload(event_id="not-an-id")}, "FINAL_EVENT_ID_INVALID"),
])
def test_final_receipt_fails_closed(changes, reason):
    with pytest.raises(FinalReceiptError, match=reason):
        bind(**changes)


def test_duplicate_matching_events_refused():
    first = json.loads(payload())["events"][0]
    with pytest.raises(FinalReceiptError, match="FINAL_MATCH_MISSING_OR_AMBIGUOUS"):
        bind(json.dumps({"events": [first, first]}).encode())


def test_night_kickoff_uses_chicago_calendar_date():
    assert scoreboard_url("2026-10-26T00:20:00Z").endswith("dates=20261025&limit=100")
