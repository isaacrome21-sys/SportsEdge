"""Adversarial zero-network tests: OddsPapi archive cache SHA/restart contract.

No API tokens, provider requests, user files or betting conclusions are
needed. This test only verifies storage consistency, not an authenticated
source or market admission.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import backfill_mlb_v8_oddspapi as H

DATE = "2026-06-05"
FID = "id_test_001"
FIXTURE = {
    "fixtureId": FID, "sportId": 13, "tournamentId": 109,
    "tournamentName": "MLB", "startTime": "2026-06-05T19:10:00Z",
    "participant1Name": "Boston Red Sox",
    "participant2Name": "New York Yankees",
}
HISTORY = {
    "fixtureId": FID,
    "bookmakers": {"draftkings": {"markets": {}}},
}
BOOKS = ("draftkings",)


def paths(root: Path) -> dict:
    fixture_key = f"fixtures_{DATE}_{DATE}"
    fd = root / "fixtures"
    hd = root / DATE / FID
    return {
        "fixture": fd / f"{fixture_key}.json",
        "fixture_meta": fd / f"{fixture_key}.meta.json",
        "history": hd / "history_draftkings.json",
        "history_meta": hd / "history_draftkings.meta.json",
    }


def run(root, state, fake_request):
    with patch.object(H, "_request", side_effect=fake_request), patch.dict(
            H.os.environ, {"SPORTSEDGE_ODDSPAPI_KEY": "stub_secret_for_test"}):
        return H.collect(
            start_date=DATE, end_date=DATE, root=root, state_path=state,
            books=BOOKS, max_history_requests=1, cooldown_seconds=0.0)


def fake_calls(log):
    def fake(path, *, key, params):
        assert key == "stub_secret_for_test"
        log.append(path)
        if path == "/fixtures":
            return json.dumps([FIXTURE]).encode(), {"etag": "fixtures-fake"}
        if path == "/historical-odds":
            assert params == {"fixtureId": FID, "bookmakers": "draftkings"}
            return json.dumps(HISTORY).encode(), {"etag": "history-fake"}
        raise AssertionError("Unexpected API path")
    return fake


def no_calls(*args, **kwargs):
    raise AssertionError("Would have made a paid/unexpected API call")


def seeded(tmp_path):
    root, state = tmp_path / "archive", tmp_path / "state.json"
    log = []
    result = run(root, state, fake_calls(log))
    assert result["status"] == "COMPLETE_RANGE"
    assert log == ["/fixtures", "/historical-odds"]
    return root, state, paths(root)


def test_first_download_and_verified_resume_never_repeat_request(tmp_path):
    root, state, file = seeded(tmp_path)
    before = {k: v.read_bytes() for k, v in file.items()}
    result = run(root, state, no_calls)
    assert result["status"] == "COMPLETE_RANGE"
    assert result["fixture_requests"] == 0
    assert result["history_requests"] == 0
    for k, v in file.items():
        assert v.read_bytes() == before[k]
        assert H._verified_cached_raw(
            file["history"], file["history_meta"],
            endpoint="/v4/historical-odds",
            params={"fixtureId": FID, "bookmakers": "draftkings"}) == before["history"]


def test_fixture_valid_json_tamper_with_old_sha_fails_before_history_or_fetch(tmp_path):
    root, state, file = seeded(tmp_path)
    raw = json.loads(file["fixture"].read_text())
    raw[0]["tournamentName"] = "NPB"
    file["fixture"].write_text(json.dumps(raw))
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_METADATA_OR_SHA_MISMATCH"
    assert report["history_requests"] == 0


def test_history_valid_json_tamper_with_old_sha_fails_before_fetch(tmp_path):
    root, state, file = seeded(tmp_path)
    data = json.loads(file["history"].read_text())
    data["bookmakers"]["draftkings"]["markets"]["fake"] = {}
    file["history"].write_text(json.dumps(data))
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_METADATA_OR_SHA_MISMATCH"


@pytest.mark.parametrize("which", ["fixture", "history"])
def test_missing_meta_never_silently_redownloads(which, tmp_path):
    root, state, file = seeded(tmp_path)
    file[f"{which}_meta"].unlink()
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_PARTIAL_OR_NONFILE"


@pytest.mark.parametrize("which", ["fixture", "history"])
def test_missing_raw_but_completed_state_refuses_rerequest(which, tmp_path):
    root, state, file = seeded(tmp_path)
    file[which].unlink()
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_PARTIAL_OR_NONFILE"


@pytest.mark.parametrize("field,value", [
    ("payload_sha256", "0"*64),
    ("bytes", 0),
    ("bytes", True),
    ("source", "ESPN"),
    ("endpoint", "/v4/not-history"),
    ("request_params_secret_free", {"bookmakers": "draftkings", "fixtureId": "wrong"}),
])
def test_sidecar_conflicts_refuse_instead_of_skipping(tmp_path, field, value):
    root, state, file = seeded(tmp_path)
    data = json.loads(file["history_meta"].read_text())
    data[field] = value
    file["history_meta"].write_text(json.dumps(data))
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_METADATA_OR_SHA_MISMATCH"


def test_bad_meta_json_refuses_without_credential_reprint(tmp_path):
    root, state, file = seeded(tmp_path)
    file["history_meta"].write_text("{bad-json")
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_UNREADABLE"
    assert "stub_secret_for_test" not in str(report)


def test_crash_after_raw_meta_before_state_restores_state_without_refetch(tmp_path):
    root, state, file = seeded(tmp_path)
    current = json.loads(state.read_text())
    assert len(current["history_completed"]) == 1
    current["history_completed"] = []
    state.write_text(json.dumps(current))
    report = run(root, state, no_calls)
    assert report["status"] == "COMPLETE_RANGE"
    recovered = json.loads(state.read_text())
    assert len(recovered["history_completed"]) == 1
    assert recovered["history_completed"][0] == f"{FID}|draftkings"
    assert file["history"].is_file()


def test_missing_completed_history_bytes_with_state_fails_even_if_both_deleted(tmp_path):
    root, state, file = seeded(tmp_path)
    file["history"].unlink()
    file["history_meta"].unlink()
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_COMPLETED_HISTORY_BYTES_MISSING"


def test_missing_completed_fixture_bytes_with_state_fails_even_if_both_deleted(tmp_path):
    root, state, file = seeded(tmp_path)
    file["fixture"].unlink()
    file["fixture_meta"].unlink()
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_COMPLETED_FIXTURE_BYTES_MISSING"


def test_valid_sha_but_wrong_cached_history_fixture_id_refused(tmp_path):
    root, state, file = seeded(tmp_path)
    data = json.loads(file["history"].read_text())
    data["fixtureId"] = "another_game"
    raw = json.dumps(data).encode()
    file["history"].write_bytes(raw)
    meta = json.loads(file["history_meta"].read_text())
    meta["payload_sha256"] = H._sha(raw)
    meta["bytes"] = len(raw)
    file["history_meta"].write_text(json.dumps(meta))
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_HISTORY_FIXTURE_INVALID"


def test_valid_sha_but_invalid_cached_fixture_json_refused(tmp_path):
    root, state, file = seeded(tmp_path)
    raw = b"{oops"
    file["fixture"].write_bytes(raw)
    meta = json.loads(file["fixture_meta"].read_text())
    meta["payload_sha256"] = H._sha(raw)
    meta["bytes"] = len(raw)
    file["fixture_meta"].write_text(json.dumps(meta))
    report = run(root, state, no_calls)
    assert report["status"] == "BLOCKED_LOCAL_ARCHIVE_INTEGRITY"
    assert report["reason"] == "ODDSPAPI_CACHE_FIXTURES_INVALID"


def test_no_source_authentication_or_market_promotion_from_clean_cache(tmp_path):
    root, state, _ = seeded(tmp_path)
    report = run(root, state, no_calls)
    assert report["status"] == "COMPLETE_RANGE"
    assert "admitted" not in str(report).lower()
    assert "model_p" not in str(report).lower()
    assert "eligible" not in str(report).lower()
