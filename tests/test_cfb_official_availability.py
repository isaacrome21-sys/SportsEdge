"""Recorded synthetic official-report admissions: source trust is external."""
from datetime import datetime, timezone
import hashlib
import json
import pytest
from sportsedge.prepricing.cfb_official_availability import (
    admit_official_availability, CFBAvailabilityError, OFFICIAL_HOST,
)

KICKOFF = "2026-10-17T19:30:00Z"
NOW = datetime(2026, 10, 17, 17, 30, tzinfo=timezone.utc)


def _data(conference="SEC"):
    return {
        "schema": "SPORTSEDGE_OFFICIAL_CFB_AVAILABILITY_V1",
        "conference": conference, "report_type": "FINAL_GAMEDAY",
        "official_source_url": "https://" + OFFICIAL_HOST[conference] + "/football/reports",
        "event_id": "401900012", "home_team_id": "61", "away_team_id": "333",
        "kickoff_utc": KICKOFF,
        "published_at_utc": "2026-10-17T16:30:00Z",
        "fetch_completed_at_utc": "2026-10-17T17:00:00Z",
        "teams": [
            {"espn_team_id": "61", "complete_final_report": True,
             "players": [{"espn_athlete_id": "123", "availability": "OUT"}]},
            {"espn_team_id": "333", "complete_final_report": True,
             "players": []},
        ],
    }


def _run(d, **overrides):
    data = json.dumps(d, sort_keys=True).encode("utf-8")
    args = dict(trusted_sha256=hashlib.sha256(data).hexdigest(),
                conference=d.get("conference", "SEC"), event_id="401900012",
                home_team_id="61", away_team_id="333", qb_team_id="61",
                qb_athlete_id="123", kickoff=KICKOFF, as_of=NOW)
    args.update(overrides)
    return admit_official_availability(data, **args)


def test_current_sec_out_only_research():
    r = _run(_data())
    assert r["qb_availability"] == "OUT"
    assert r["research_only"] and not r["eligible"] and not r["play_authority"]
    assert not r["qb_starter_identity_verified"]


def test_big12_final_explicit_available_not_starter_verification():
    d = _data("BIG_12")
    d["teams"][0]["players"][0]["availability"] = "AVAILABLE"
    assert _run(d)["qb_availability"] == "AVAILABLE"
    assert not _run(d)["activation_allowed"]


def test_absent_is_unknown_not_automatically_healthy():
    d = _data("BIG_TEN")
    d["teams"][0]["players"] = []
    assert _run(d)["qb_availability"] == "NOT_LISTED_AVAILABILITY_UNKNOWN"


@pytest.mark.parametrize("mutator", [
    lambda d: d.update(report_type="MIDWEEK"),
    lambda d: d.update(event_id="401900099"),
    lambda d: d.update(home_team_id="333"),
    lambda d: d.update(kickoff_utc="2026-10-17T22:00:00Z"),
    lambda d: d.update(official_source_url="https://www.secsports.com.evil.test/reports"),
    lambda d: d.update(official_source_url="http://www.secsports.com/reports"),
    lambda d: d.update(published_at_utc="2026-10-17T18:30:00Z"),
    lambda d: d.update(fetch_completed_at_utc="2026-10-17T20:00:00Z"),
    lambda d: d["teams"].pop(),
    lambda d: d["teams"][0].update(complete_final_report=False),
    lambda d: d["teams"][0]["players"].append({"espn_athlete_id": "123", "availability": "AVAILABLE"}),
    lambda d: d["teams"][0]["players"][0].update(availability="QUESTIONABLE"),
])
def test_bad_evidence_rejected(mutator):
    d = _data()
    mutator(d)
    with pytest.raises(CFBAvailabilityError):
        _run(d)


def test_untrusted_digest_and_future_asof_rejected():
    with pytest.raises(CFBAvailabilityError, match="EXTERNAL_ANCHOR_MISMATCH"):
        _run(_data(), trusted_sha256="a" * 64)
    with pytest.raises(CFBAvailabilityError, match="REPORT_NOT_AVAILABLE"):
        _run(_data(), as_of=datetime(2026, 10, 17, 16, 0, tzinfo=timezone.utc))


def test_duplicate_json_key_rejected_even_if_hash_matches():
    original = json.dumps(_data())
    raw = original.replace('"event_id": "401900012"', '"event_id": "401900012", "event_id": "401900012"')
    payload = raw.encode()
    with pytest.raises(CFBAvailabilityError, match="DUPLICATE_JSON_KEY"):
        admit_official_availability(
            payload, trusted_sha256=hashlib.sha256(payload).hexdigest(),
            conference="SEC", event_id="401900012", home_team_id="61",
            away_team_id="333", qb_team_id="61", qb_athlete_id="123",
            kickoff=KICKOFF, as_of=NOW)
