"""Offline historical-odds admission contract tests, no API calls or secret."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from urllib.error import HTTPError

import pytest

from scripts import oddspapi_history_admission as H

ANCHOR = {
    "fixtureId": "id10000012345",
    "scheduled_start_utc": "2026-10-20T20:00:00Z",
    "canonical_event_id": "MLB:1234:fixture-verification-pending",
    "fixture_anchor_sha256": "a" * 64,
}
MAP = {
    "version": H.CATALOG_VERSION,
    "fixtureId": ANCHOR["fixtureId"],
    "bookmaker": "draftkings",
    "market_id": "101",
    "canonical_market": "MLB_MONEYLINE",
    "market_catalog_sha256": "b" * 64,
    "player_id": "0",
    "selection_by_outcome_id": {"10": "HOME", "20": "AWAY"},
}


def row(at, price, id):
    return {"createdAt": at, "price": price, "id": id, "active": True}


def payload():
    return {
        "fixtureId": ANCHOR["fixtureId"],
        "bookmakers": {"draftkings": {
            "markets": {"101": {"outcomes": {
                "10": {"players": {"0": [
                    row("2026-10-20T19:57:30Z", 1.91, 11),
                    row("2026-10-20T19:59:00Z", 1.92, 12),
                    row("2026-10-20T20:02:00Z", 1.2, 13),
                ]}},
                "20": {"players": {"0": [
                    row("2026-10-20T19:58:30Z", 1.99, 21),
                    row("2026-10-20T19:59:20Z", 1.98, 22),
                ]}},
            }}},
        }},
    }


def screen(payload_override=None, anchor=None, mapping=None):
    return H.inspect_historical_payload(
        payload() if payload_override is None else payload_override,
        ANCHOR if anchor is None else anchor,
        MAP if mapping is None else mapping)


def test_two_sided_same_fixture_candidate_is_explicitly_unverified():
    output = screen()
    assert output["status"] == "STRUCTURAL_CANDIDATE_UNVERIFIED"
    assert output["eligible"] is False
    assert output["play_authority"] is False
    assert output["market_test"] == "NOT_ADMITTED"
    assert output["close_status"] == "NOT_CERTIFIED_ACTUAL_FIRST_PLAY"
    assert not output["independent_fixture_verified"]
    assert not output["independent_market_mapping_verified"]
    assert output["capture_span_seconds"] == 20.0
    assert output["post_start_entries_ignored"] == 1
    rows = {r["selection"]: r for r in output["source_selection_rows"]}
    assert rows["HOME"]["decimal_price"] == 1.92
    assert rows["AWAY"]["decimal_price"] == 1.98
    assert rows["HOME"]["quote_id"] == 12
    assert rows["AWAY"]["quote_id"] == 22
    assert not hasattr(output, "model_p")


def test_a_second_exact_read_yields_same_hash_and_no_credential_field():
    a, b = screen(), screen()
    assert a["admission_sha256"] == b["admission_sha256"]
    assert "apiKey" not in json.dumps(a)
    assert "secret" not in json.dumps(a).lower()
    assert "staking" not in a


def test_actual_post_first_pitch_quote_does_not_override_pregame():
    obj = payload()
    obj["bookmakers"]["draftkings"]["markets"]["101"][
        "outcomes"]["20"]["players"]["0"].append(
        row("2026-10-20T23:00:00Z", 1000, 23))
    result = screen(obj)
    assert result["post_start_entries_ignored"] == 2
    assert {r["selection"]: r["decimal_price"]
            for r in result["source_selection_rows"]}["AWAY"] == 1.98


def test_pair_span_cannot_claim_two_noncoincident_sides():
    obj = payload()
    arr = obj["bookmakers"]["draftkings"]["markets"]["101"][
        "outcomes"]["20"]["players"]["0"]
    arr[:] = [row("2026-10-20T18:00:00Z", 1.93, 30)]
    with pytest.raises(H.OddsPapiCandidateError,
                       match="PREGAME_OUTCOME_CAPTURE_SPAN_EXCEEDS_150S"):
        screen(obj)


@pytest.mark.parametrize("bad", [0.0, -3, float("nan"), float("inf"), 1.0,
                                    "invalid", None])
def test_invalid_decimal_quotes_fail_closed(bad):
    obj = payload()
    arr = obj["bookmakers"]["draftkings"]["markets"]["101"][
        "outcomes"]["10"]["players"]["0"]
    arr[1]["price"] = bad
    with pytest.raises(H.OddsPapiCandidateError):
        screen(obj)


def test_bookmaker_outcome_player_sets_are_exact():
    obj = payload()
    obj["bookmakers"]["draftkings"]["markets"]["101"]["outcomes"][
        "30"] = {"players": {"0": []}}
    with pytest.raises(H.OddsPapiCandidateError,
                       match="ODDSPAPI_OUTCOME_SET_MISMATCH"):
        screen(obj)
    obj = payload()
    obj["bookmakers"]["draftkings"]["markets"]["101"][
        "outcomes"]["10"]["players"]["7"] = []
    with pytest.raises(H.OddsPapiCandidateError,
                       match="ODDSPAPI_UNVERIFIED_PLAYER_SET"):
        screen(obj)


def test_identity_and_market_mapping_fail_closed():
    obj = payload()
    obj["fixtureId"] = "another-fixture"
    with pytest.raises(H.OddsPapiCandidateError,
                       match="ODDSPAPI_RESPONSE_FIXTURE_MISMATCH"):
        screen(obj)
    badmap = deepcopy(MAP)
    badmap["player_id"] = "4712"
    with pytest.raises(H.OddsPapiCandidateError,
                       match="PLAYER_SUBJECT_BINDING_NOT_ADMITTED"):
        screen(mapping=badmap)
    badmap = deepcopy(MAP)
    badmap["selection_by_outcome_id"]["20"] = "HOME"
    with pytest.raises(H.OddsPapiCandidateError,
                       match="OUTCOME_SIDE_COLLISION_OR_UNKNOWN"):
        screen(mapping=badmap)


def test_archive_before_january_2026_refused():
    old = deepcopy(ANCHOR)
    old["scheduled_start_utc"] = "2025-04-20T20:00:00Z"
    with pytest.raises(H.OddsPapiCandidateError,
                       match="NO_PROVIDER_HISTORICAL_COVERAGE_PRE_2026"):
        screen(anchor=old)


def test_provider_key_absent_never_attempts_live_network(monkeypatch):
    def must_not_run(*args, **kwargs):
        raise AssertionError("network must not be called without key")
    monkeypatch.setattr(H, "urlopen", must_not_run)
    with pytest.raises(H.OddsPapiCandidateError,
                       match="BLOCKED_NO_ODDSPAPI_KEY"):
        H.fetch_single_fixture_history(ANCHOR["fixtureId"], "draftkings", secret="")


def test_credentials_never_leak_on_http_failure(monkeypatch):
    key = "sk-PRIVATE-KEY-DO-NOT-LOG"
    def mock_http_error(req, timeout=30):
        raise HTTPError(req.full_url, 401, "Unauthorized", None, None)
    monkeypatch.setattr(H, "urlopen", mock_http_error)
    with pytest.raises(H.OddsPapiCandidateError) as raised:
        H.fetch_single_fixture_history(
            ANCHOR["fixtureId"], "draftkings", secret=key)
    assert str(raised.value) == "BLOCKED_ODDSPAPI_CREDENTIAL_UNAUTHORIZED"
    assert key not in str(raised.value)


def test_offline_cli_is_research_only_and_no_raw_response_saved(tmp_path, capsys):
    anchor, mapping, response = (
        tmp_path / "anchor.json", tmp_path / "map.json",
        tmp_path / "response.json")
    for file, value in [(anchor, ANCHOR), (mapping, MAP),
                        (response, payload())]:
        file.write_text(json.dumps(value))
    output = tmp_path / "candidate.json"
    code = H.main([
        "--fixture-anchor-json", str(anchor),
        "--market-map-json", str(mapping),
        "--response-json", str(response),
        "--output-json", str(output),
    ])
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["research_only"] is True
    assert summary["market_test"] == "NOT_ADMITTED"
    saved = json.loads(output.read_text())
    assert saved["eligible"] is False
    assert "apiKey" not in output.read_text()
    assert "raw_response" not in saved
