"""Pure FINAL receipt issue-routing tests; no sportsbook or GitHub network."""
import hashlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.nfl_final_issue_receipt import FinalIssueRouteError, format_final_issue
from sportsedge.pipeline.intake import parse_issue


RAW = b'{"events":[],"markets":[],"selections":[]}'
SHA = hashlib.sha256(RAW).hexdigest()
RECEIVED = datetime(2026, 10, 25, 13, 5, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 10, 25, 13, 30, tzinfo=timezone.utc)
ISSUE = (
    "Pittsburgh Steelers @ New Orleans Saints\n"
    "Captured: 2026-10-24T20:34:00-05:00\n"
    "<!-- DK event: 34118009; older prop info -->\n"
    "ML -162 +136\n"
    "Spread -3 -112 -108\n"
    'Prop "Aaron Rodgers" PassYards 225.5 -113 -111'
)


def sample():
    return {
        "capture_kind": "FINAL", "book": "draftkings",
        "source_class": "DRAFTKINGS_DIRECT_WEB_V1", "no_backfill": True,
        "promotion_authority": False, "retrieved_at_utc": "2026-10-25T13:05:00Z",
        "hashes": {"script_sha256": "a" * 64},
        "schedule": {"matching_semantics": "KICKOFF_UTC_MULTIPLICITY", "sha256": "b" * 64},
        "transport": {
            "raw_sha256": SHA,
            "raw_relative_path": f"raw/draftkings-direct/{SHA}.json",
            "source_uri": "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1",
        },
        "games": [{
            "event_id": "34118009", "away_team": "PIT Steelers",
            "home_team": "NO Saints", "commence_time": "2026-10-25T13:30:00Z",
            "observed_at_utc": "2026-10-25T13:05:00Z",
            "source_class": "DRAFTKINGS_DIRECT_WEB_V1", "book": "draftkings",
            "spread": {"status": "OK", "away_point": -3.0,
                       "home_point": 3.0, "away_price": -112, "home_price": -108},
            "total": {"status": "OK", "point": 43.5,
                      "over_price": -110, "under_price": -110},
        }],
    }


def render(record=None, issue=ISSUE, raw=RAW, now=RECEIVED + timedelta(seconds=30)):
    return format_final_issue(record if record is not None else sample(), raw, issue, now=now)


def test_receipt_produces_only_real_spread_total_and_parses():
    body = render()
    assert body.splitlines()[0] == "Pittsburgh Steelers @ New Orleans Saints"
    assert body.splitlines()[1] == "Captured: 2026-10-25T13:05:00Z"
    assert "Spread -3 -112 -108" in body
    assert "Total 43.5 -110 -110" in body
    assert f"FINAL raw SHA256: {SHA}" in body
    assert "ML " not in body and "PassYards" not in body
    parsed = parse_issue(body, "NFL", resolve_teams=False)
    assert len(parsed.games) == 1
    assert len(parsed.games[0].markets) == 2
    assert parsed.games[0].captured_at == "2026-10-25T13:05:00+00:00"


@pytest.mark.parametrize("issue", [
    "Pittsburgh Steelers @ New Orleans Saints\nSpread -3 -112 -108",
    ISSUE.replace("34118009", "34118088"),
    ISSUE + "\n<!-- DK event: 34118009 -->",
    ISSUE.replace("Pittsburgh Steelers", "Houston Texans"),
])
def test_wrong_or_ambiguous_issue_identity_fails_closed(issue):
    with pytest.raises(FinalIssueRouteError):
        render(issue=issue)


@pytest.mark.parametrize("offset_seconds,reason", [
    (-1, "ROUTE_DELIVERY_STALE_OR_POSTSTART"),
    (181, "ROUTE_DELIVERY_STALE_OR_POSTSTART"),
    (25 * 60, "ROUTE_DELIVERY_STALE_OR_POSTSTART"),
])
def test_delivery_not_retroactively_attributed(offset_seconds, reason):
    with pytest.raises(FinalIssueRouteError, match=reason):
        render(now=RECEIVED + timedelta(seconds=offset_seconds))


@pytest.mark.parametrize("capture,reason", [
    ("2026-10-25T12:59:59Z", "ROUTE_FINAL_RECEIPT_OUTSIDE_WINDOW"),
    ("2026-10-25T13:15:00Z", "ROUTE_FINAL_RECEIPT_OUTSIDE_WINDOW"),
])
def test_source_receipt_outside_frozen_window_is_refused(capture, reason):
    record = sample()
    record["retrieved_at_utc"] = capture
    record["games"][0]["observed_at_utc"] = capture
    with pytest.raises(FinalIssueRouteError, match=reason):
        render(record=record)


def test_response_bytes_and_transport_digest_must_match():
    with pytest.raises(FinalIssueRouteError, match="ROUTE_RAW_DIGEST_MISMATCH"):
        render(raw=b'{"tampered":true}')
    record = sample()
    record["transport"]["raw_relative_path"] = "raw/draftkings-direct/other.json"
    with pytest.raises(FinalIssueRouteError, match="ROUTE_RAW_DIGEST_MISMATCH"):
        render(record=record)


@pytest.mark.parametrize("change,reason", [
    ({"home_point": 4.0}, "ROUTE_MARKET_POINTS_INVALID"),
    ({"away_price": True}, "ROUTE_PRICE_INVALID"),
    ({"home_price": -99}, "ROUTE_PRICE_INVALID"),
    ({"away_point": float("nan")}, "ROUTE_LINE_INVALID"),
])
def test_malformed_spread_is_not_transcribed(change, reason):
    record = sample()
    record["games"][0]["spread"].update(change)
    with pytest.raises(FinalIssueRouteError, match=reason):
        render(record=record)


def test_missing_second_side_and_stale_market_refused():
    record = sample()
    del record["games"][0]["total"]["under_price"]
    with pytest.raises(FinalIssueRouteError, match="ROUTE_PRICE_INVALID"):
        render(record=record)
    record = sample()
    record["games"][0]["total"]["status"] = "UNAVAILABLE"
    with pytest.raises(FinalIssueRouteError, match="ROUTE_TWO_SIDED_MARKETS_MISSING"):
        render(record=record)


def test_no_opener_or_non_direct_payload_becomes_final():
    record = sample()
    record["capture_kind"] = "OPENER"
    with pytest.raises(FinalIssueRouteError, match="ROUTE_SOURCE_NOT_FINAL_DIRECT"):
        render(record=record)
    record = sample()
    record["source_class"] = "DRAFTKINGS_ODDS_API_V1"
    with pytest.raises(FinalIssueRouteError, match="ROUTE_SOURCE_NOT_FINAL_DIRECT"):
        render(record=record)


def test_no_duplicate_event_rows_and_no_future_claim():
    record = sample()
    record["games"].append(deepcopy(record["games"][0]))
    with pytest.raises(FinalIssueRouteError, match="ROUTE_EVENT_NOT_UNIQUE"):
        render(record=record)
    record = sample()
    record["retrieved_at_utc"] = "2026-10-25T13:06:00Z"
    with pytest.raises(FinalIssueRouteError, match="ROUTE_RECEIPT_TIME_MISMATCH"):
        render(record=record)
