from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.score_counts_source_manifest import (
    DEPTH_URI,
    PBP_URI,
    SCHEDULE_SHA256,
    SCHEDULE_URI,
    ScoreCountSourceError,
    build_score_count_source_manifest,
)


PARSER = "b" * 64


def receipts(seasons=(2018, 2019)):
    out = [{
        "name": "schedule",
        "source_identifier": SCHEDULE_URI,
        "retrieved_at_utc": "2026-10-05T12:00:00Z",
        "season_scope": list(seasons),
        "byte_sha256": SCHEDULE_SHA256,
        "parser_code_sha256": PARSER,
    }]
    for season in seasons:
        out.extend([
            {
                "name": f"pbp_{season}",
                "source_identifier": PBP_URI.format(season=season),
                "retrieved_at_utc": "2026-10-05T12:01:00Z",
                "season_scope": [season],
                "byte_sha256": f"{season:064x}"[-64:],
                "parser_code_sha256": PARSER,
            },
            {
                "name": f"depth_{season}",
                "source_identifier": DEPTH_URI.format(season=season),
                "retrieved_at_utc": datetime(2026, 10, 5, 12, 2, tzinfo=timezone.utc),
                "season_scope": [season],
                "byte_sha256": f"{season + 100:064x}"[-64:],
                "parser_code_sha256": PARSER,
            },
        ])
    return out


def test_manifest_is_deterministic_and_wraps_canonical_nfl_manifest():
    a = build_score_count_source_manifest(receipts(), seasons=(2018, 2019))
    b = build_score_count_source_manifest(list(reversed(receipts())), seasons=(2018, 2019))
    assert a["manifest_sha256"] == b["manifest_sha256"]
    assert a["canonical_nfl_manifest_sha256"] == b["canonical_nfl_manifest_sha256"]
    assert a["canonical_nfl_manifest"]["schedule_anchor_sha256"] == SCHEDULE_SHA256
    assert a["authority"]["creates_model_p"] is False


def test_every_receipt_keeps_parser_and_retrieval_provenance():
    out = build_score_count_source_manifest(receipts(), seasons=(2018, 2019))
    for row in out["receipts"]:
        assert len(row["parser_code_sha256"]) == 64
        assert row["retrieved_at_utc"].endswith("+00:00")
        assert row["season_scope"]


def test_schedule_bytes_are_pinned_to_preregistered_anchor():
    bad = receipts()
    bad[0]["byte_sha256"] = "c" * 64
    with pytest.raises(ScoreCountSourceError, match="FIXED_SOURCE_SHA256_MISMATCH"):
        build_score_count_source_manifest(bad, seasons=(2018, 2019))


def test_source_identifier_and_scope_are_exact():
    bad_uri = receipts()
    bad_uri[1]["source_identifier"] += "?moving=true"
    with pytest.raises(ScoreCountSourceError, match="SOURCE_IDENTIFIER_MISMATCH"):
        build_score_count_source_manifest(bad_uri, seasons=(2018, 2019))

    bad_scope = receipts()
    bad_scope[1]["season_scope"] = [2019]
    with pytest.raises(ScoreCountSourceError, match="SEASON_SCOPE_MISMATCH"):
        build_score_count_source_manifest(bad_scope, seasons=(2018, 2019))


def test_missing_extra_duplicate_and_naive_timestamp_fail_closed():
    missing = receipts()[:-1]
    with pytest.raises(ScoreCountSourceError, match="REQUIRED_SOURCE_MISSING"):
        build_score_count_source_manifest(missing, seasons=(2018, 2019))

    extra = receipts()
    extra.append({
        "name": "mystery",
        "source_identifier": "x",
        "retrieved_at_utc": "2026-10-05T12:00:00Z",
        "season_scope": [2018],
        "byte_sha256": "c" * 64,
        "parser_code_sha256": PARSER,
    })
    with pytest.raises(ScoreCountSourceError, match="UNEXPECTED_SOURCE"):
        build_score_count_source_manifest(extra, seasons=(2018, 2019))

    dup = receipts()
    dup.append(dict(dup[1]))
    with pytest.raises(ScoreCountSourceError, match="SOURCE_NAME_DUPLICATE"):
        build_score_count_source_manifest(dup, seasons=(2018, 2019))

    naive = receipts()
    naive[1]["retrieved_at_utc"] = "2026-10-05T12:00:00"
    with pytest.raises(ScoreCountSourceError, match="TIMEZONE_REQUIRED"):
        build_score_count_source_manifest(naive, seasons=(2018, 2019))


def test_parser_hash_is_mandatory():
    bad = receipts()
    bad[1]["parser_code_sha256"] = "short"
    with pytest.raises(ScoreCountSourceError, match="SHA256_REQUIRED"):
        build_score_count_source_manifest(bad, seasons=(2018, 2019))
