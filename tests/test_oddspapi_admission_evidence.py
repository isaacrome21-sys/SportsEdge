"""Fixture-driven tests for the admission evidence-acquisition layer:
frozen pull, R1 cohort assembly, first-play anchors. No network anywhere:
the only fetch used is a recorded-fixture fake. Nothing here admits."""
import json
from pathlib import Path

import pytest

from sportsedge.oddspapi_first_play_anchors import (
    AnchorRefusal,
    anchor_provenance_sha256,
    get_anchor,
    load_anchor_book,
    to_instrument_anchor,
)
from sportsedge.oddspapi_frozen_pull import (
    FrozenPullRefusal,
    pull_frozen_targets,
    verify_pull_dir,
)
from sportsedge.oddspapi_numeric_admission_ad import (
    evaluate_numeric_admission_dryrun,
)
from sportsedge.oddspapi_r1_cohort import (
    CohortAssemblyRefusal,
    assemble_cohort,
    build_close_candidate,
    build_numeric_dryrun_envelope,
)

HASH = "f" * 64
REAL_CAPTURES = [
    Path.home() / "workspace/sportsedge/dk_line_archive/nba/2026-10-20/1023_ct.json",
    Path.home() / "workspace/sportsedge/dk_line_archive/nba/2026-10-20/1722_ct.json",
]


# ---------------------------------------------------------------- frozen pull

PAYLOADS = {
    "evt-1": (200, b'{"fixtureId":"evt-1","bookmakers":{}}'),
    "evt-2": (200, b'{"fixtureId":"evt-2","bookmakers":{}}'),
}


def fake_fetch(path, params):
    assert path == "/v4/historical-odds"
    assert params["bookmakers"] == "draftkings"
    return PAYLOADS[params["fixtureId"]]


TARGETS = [
    {"sport": "NBA", "event_id": "evt-1", "date": "2026-10-20"},
    {"sport": "NBA", "event_id": "evt-2", "date": "2026-10-20"},
]


def test_pull_freezes_payloads_and_manifest(tmp_path):
    manifest = pull_frozen_targets(TARGETS, fake_fetch, tmp_path,
                                   retrieved_at="2026-10-21T12:00:00Z")
    assert manifest["admission"] == "NOT_ADMITTED"
    assert manifest["verdict"] == "NO_VERDICT"
    assert manifest["target_count"] == 2
    for entry in manifest["entries"]:
        raw = (tmp_path / entry["raw_file"]).read_bytes()
        assert len(raw) == entry["bytes"]
        from hashlib import sha256
        assert sha256(raw).hexdigest() == entry["sha256"]
    result = verify_pull_dir(tmp_path)
    assert result["verified_entries"] == 2


def test_pull_tampered_raw_refused(tmp_path):
    pull_frozen_targets(TARGETS, fake_fetch, tmp_path,
                        retrieved_at="2026-10-21T12:00:00Z")
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    victim = tmp_path / manifest["entries"][0]["raw_file"]
    victim.write_bytes(victim.read_bytes() + b" ")
    with pytest.raises(FrozenPullRefusal, match="PULL_MANIFEST_SHA_MISMATCH"):
        verify_pull_dir(tmp_path)


def test_pull_http_failure_writes_no_manifest(tmp_path):
    def failing_fetch(path, params):
        return 503, b""
    with pytest.raises(FrozenPullRefusal, match="PULL_HTTP_STATUS_NOT_200"):
        pull_frozen_targets(TARGETS, failing_fetch, tmp_path,
                            retrieved_at="2026-10-21T12:00:00Z")
    assert not (tmp_path / "manifest.json").exists()


def test_pull_rejects_duplicate_and_malformed_targets(tmp_path):
    with pytest.raises(FrozenPullRefusal, match="PULL_DUPLICATE_TARGET"):
        pull_frozen_targets(TARGETS + [TARGETS[0]], fake_fetch, tmp_path,
                            retrieved_at="2026-10-21T12:00:00Z")
    bad = [{"sport": "NBA", "event_id": "evt-1"}]  # missing date
    with pytest.raises(FrozenPullRefusal, match="PULL_TARGET_SCHEMA_INVALID"):
        pull_frozen_targets(bad, fake_fetch, tmp_path,
                            retrieved_at="2026-10-21T12:00:00Z")


# ---------------------------------------------------------------- R1 cohort

def _game(**overrides):
    game = {
        "game_date": "2026-10-20", "start_time_ct": "18:00",
        "away": "BOS", "away_name": "Boston Celtics",
        "home": "DET", "home_name": "Detroit Pistons",
        "spread": {"away_line": -1.5, "away_price": -110,
                   "home_line": 1.5, "home_price": -110,
                   "captured_at": "2026-10-20T10:23:50-05:00"},
        "moneyline": {"away_price": -122, "home_price": 102,
                      "captured_at": "2026-10-20T10:23:50-05:00"},
        "total": {"line": 219.5, "over_price": -108, "under_price": -112,
                  "captured_at": "2026-10-20T10:23:50-05:00"},
        "team_totals": [
            {"team": "Boston Celtics", "line": 110.5, "over_price": -105,
             "under_price": -115, "captured_at": "2026-10-20T10:26:00-05:00"},
        ],
        "player_props": {"points": [
            {"player": "Jayson Tatum", "line": 26.5, "over_price": -111,
             "under_price": -115, "captured_at": "2026-10-20T10:35:00-05:00"},
        ]},
    }
    game.update(overrides)
    return game


def _write_capture(tmp_path, games, name="cap.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"sport": "NBA", "games": games}))
    return path


def test_cohort_sample_shape_matches_instrument(tmp_path):
    cohort = assemble_cohort([_write_capture(tmp_path, [_game()])])
    # spread 2 + moneyline 2 + total 2 + team_totals 2 + one prop x2 = 10
    assert cohort["counts"]["samples"] == 10
    expected_keys = {"canonical_event_id", "market_id", "bookmaker", "side",
                     "line", "captured_at_utc", "american_price",
                     "source_sha256"}
    for sample in cohort["dk_samples"]:
        assert set(sample) == {"sample_id", "dk", "oddspapi"}
        assert sample["oddspapi"] is None
        assert set(sample["dk"]) == expected_keys
        assert sample["dk"]["bookmaker"] == "draftkings"
    markets = {s["dk"]["market_id"] for s in cohort["dk_samples"]}
    assert {"SPREAD", "MONEYLINE", "TOTAL", "TEAM_TOTAL:BOS",
            "PROP_POINTS:JAYSON_TATUM"} <= markets
    ml = [s["dk"] for s in cohort["dk_samples"]
          if s["dk"]["market_id"] == "MONEYLINE"]
    assert all(q["line"] is None for q in ml)


def test_cohort_malformed_row_refused(tmp_path):
    broken = _game()
    del broken["spread"]["away_price"]
    with pytest.raises(CohortAssemblyRefusal,
                       match="R1_QUOTE_FIELD_MISSING"):
        assemble_cohort([_write_capture(tmp_path, [broken])])
    naive = _game()
    naive["total"] = dict(naive["total"],
                          captured_at="2026-10-20T10:23:50")
    with pytest.raises(CohortAssemblyRefusal,
                       match="R1_CAPTURED_AT_OFFSET_REQUIRED"):
        assemble_cohort([_write_capture(tmp_path, [naive], name="cap2.json")])


def test_cohort_feeds_real_instrument_unpaired(tmp_path):
    cohort = assemble_cohort([_write_capture(tmp_path, [_game()])])
    anchor = to_instrument_anchor({
        "event_id": "NBA:2026-10-20:BOS_AT_DET",
        "actual_first_play_at": "2026-10-20T23:05:00Z",
        "source_name": "official box score",
        "source_url_or_id": "fixture-box-1",
        "retrieved_at": "2026-10-21T12:00:00Z",
    })
    close = build_close_candidate({
        "canonical_event_id": "NBA:2026-10-20:BOS_AT_DET",
        "market_id": "TOTAL",
        "provider_created_at_utc": "2026-10-20T23:04:59Z",
        "candidate_sha256": HASH,
    }, anchor)
    report = evaluate_numeric_admission_dryrun(
        build_numeric_dryrun_envelope(cohort, [close]))
    assert report["admission"] == "NOT_ADMITTED"
    a_rows = report["check_A"]["rows"]
    assert a_rows and all(r["reason"] == "A_UNPAIRED_SAMPLE" for r in a_rows)
    assert report["check_D"]["rows"][0]["status"] == "PASS_NUMERIC_ONLY"


# ---------------------------------------------------------------- anchors

ANCHOR = {
    "event_id": "NBA:2026-10-20:BOS_AT_DET",
    "actual_first_play_at": "2026-10-20T23:05:00Z",
    "source_name": "official box score",
    "source_url_or_id": "fixture-box-1",
    "retrieved_at": "2026-10-21T12:00:00Z",
}


def test_anchor_book_hit_and_explicit_miss():
    book = load_anchor_book([ANCHOR])
    assert get_anchor(book, ANCHOR["event_id"])["source_name"] == \
        "official box score"
    missing = get_anchor(book, "NBA:2026-10-20:XXX_AT_YYY")
    assert missing == {"event_id": "NBA:2026-10-20:XXX_AT_YYY",
                       "anchor_state": "NO_ANCHOR"}


def test_anchor_conflict_refused_and_instrument_shape():
    conflicting = dict(ANCHOR, actual_first_play_at="2026-10-20T23:06:00Z")
    with pytest.raises(AnchorRefusal, match="ANCHOR_DUPLICATE_CONFLICT"):
        load_anchor_book([ANCHOR, conflicting])
    book = load_anchor_book([ANCHOR, dict(ANCHOR)])  # identical dedupes
    converted = to_instrument_anchor(book[ANCHOR["event_id"]])
    assert set(converted) == {"canonical_event_id", "actual_first_play_utc",
                              "official_source_sha256"}
    assert converted["official_source_sha256"] == \
        anchor_provenance_sha256(ANCHOR)
    assert len(converted["official_source_sha256"]) == 64
    with pytest.raises(AnchorRefusal, match="ANCHOR_ABSENT_CANNOT_CONVERT"):
        to_instrument_anchor(get_anchor(book, "NBA:nope"))


def test_close_candidate_without_anchor_scores_missing_not_inferred():
    close = build_close_candidate({
        "canonical_event_id": "NBA:2026-10-20:BOS_AT_DET",
        "market_id": "TOTAL",
        "provider_created_at_utc": "2026-10-20T23:04:59Z",
        "candidate_sha256": HASH,
    }, None)
    assert close["actual_first_play"] is None
    envelope = {
        "version": "ODDSPAPI_NUMERIC_ADMISSION_AD_DRYRUN_V1",
        "dk_cohort_manifest_sha256": HASH,
        "dk_samples": [{
            "sample_id": "x1",
            "dk": {"canonical_event_id": "NBA:2026-10-20:BOS_AT_DET",
                   "market_id": "TOTAL", "bookmaker": "draftkings",
                   "side": "OVER", "line": "219.5",
                   "captured_at_utc": "2026-10-20T15:23:50Z",
                   "american_price": -108, "source_sha256": "a" * 64},
            "oddspapi": None,
        }],
        "close_candidates": [close],
    }
    report = evaluate_numeric_admission_dryrun(envelope)
    assert report["check_D"]["rows"][0]["reason"] == \
        "D_INDEPENDENT_ACTUAL_FIRST_PLAY_NOT_SUPPLIED"


# ------------------------------------------------------- real captures (local)

@pytest.mark.skipif(not all(p.is_file() for p in REAL_CAPTURES),
                    reason="real capture records not present on this machine")
def test_real_oct20_captures_assemble():
    cohort = assemble_cohort(REAL_CAPTURES)
    # 27 games across the two files; game-line samples alone are 6 per game.
    assert cohort["counts"]["games"] == 27
    assert cohort["counts"]["samples"] > 27 * 6
    events = {s["dk"]["canonical_event_id"] for s in cohort["dk_samples"]}
    assert "NBA:2026-10-20:BOS_AT_DET" in events
