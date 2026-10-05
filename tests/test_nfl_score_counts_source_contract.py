from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sportsedge.sports.nfl.score_counts_source_manifest import (
    ScoreCountSourceError,
    build_score_count_source_manifest,
    contract_payload_sha256,
)

CONTRACT_PATH = Path("config/research/nfl_score_counts_g1_source_contract_v1.json")
PARSER = "e" * 64


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def receipts(cfg=None):
    cfg = cfg or contract()
    out = [{
        "name": "schedule",
        "fetch_uri": cfg["schedule"]["fetch_uri"],
        "origin_uri": cfg["schedule"]["fetch_uri"],
        "retrieved_at_utc": "2026-10-05T13:00:00Z",
        "season_scope": cfg["schedule"]["season_scope"],
        "byte_sha256": cfg["schedule"]["expected_sha256"],
        "parser_code_sha256": PARSER,
    }]
    for family in ("pbp", "depth"):
        for season, spec in sorted(cfg[family].items()):
            out.append({
                "name": f"{family}_{season}",
                "fetch_uri": spec["fetch_uri"],
                "origin_uri": spec["origin_uri"],
                "retrieved_at_utc": datetime(2026, 10, 5, 13, 1, tzinfo=timezone.utc),
                "season_scope": spec["season_scope"],
                "byte_sha256": spec["expected_sha256"],
                "parser_code_sha256": PARSER,
            })
    return out


def test_contract_is_exact_2018_2025_and_uses_frozen_store():
    cfg = contract()
    assert cfg["status"] == "FROZEN_BEFORE_ATTEMPT1_SOURCE_ACCESS"
    assert cfg["schedule"]["origin_commit_sha"] == "be9813d153e6694af4d98c7287a7db32225806ae"
    assert cfg["schedule"]["expected_sha256"] == "59c8bea7e185dde9e6053a06c24c34f6e5a91dcaea3187c0d9bab12759bb05fb"
    assert list(map(int, cfg["pbp"].keys())) == list(range(2018, 2026))
    assert list(map(int, cfg["depth"].keys())) == list(range(2018, 2026))
    assert all("nfl-source-freeze-v1" in spec["fetch_uri"] for spec in cfg["pbp"].values())
    assert all("nfl-source-freeze-v1" in spec["fetch_uri"] for spec in cfg["depth"].values())
    assert cfg["rules"]["direct_mutable_provider_refetch_for_attempt_execution"] is False


def test_manifest_is_deterministic_and_binds_every_expected_byte():
    cfg = contract()
    a = build_score_count_source_manifest(receipts(cfg), parser_code_sha256=PARSER, contract=cfg)
    b = build_score_count_source_manifest(list(reversed(receipts(cfg))), parser_code_sha256=PARSER, contract=cfg)
    assert a == b
    assert a["manifest_sha256"] == b["manifest_sha256"]
    assert a["contract_payload_sha256"] == contract_payload_sha256(cfg)
    assert len(a["receipts"]) == 17
    assert a["status"] == "EXACT_FROZEN_BYTES_VERIFIED_BEFORE_PARSE"
    assert a["authority"]["creates_model_p"] is False


def test_wrong_bytes_uri_parser_and_scope_fail_closed():
    cfg = contract()

    wrong = receipts(cfg)
    wrong[1]["byte_sha256"] = "f" * 64
    with pytest.raises(ScoreCountSourceError, match="EXPECTED_SHA256_MISMATCH"):
        build_score_count_source_manifest(wrong, parser_code_sha256=PARSER, contract=cfg)

    wrong = receipts(cfg)
    wrong[1]["fetch_uri"] += "?mutable=1"
    with pytest.raises(ScoreCountSourceError, match="FETCH_URI_MISMATCH"):
        build_score_count_source_manifest(wrong, parser_code_sha256=PARSER, contract=cfg)

    wrong = receipts(cfg)
    wrong[1]["parser_code_sha256"] = "d" * 64
    with pytest.raises(ScoreCountSourceError, match="PARSER_IDENTITY_MISMATCH"):
        build_score_count_source_manifest(wrong, parser_code_sha256=PARSER, contract=cfg)

    wrong = receipts(cfg)
    wrong[1]["season_scope"] = [2099]
    with pytest.raises(ScoreCountSourceError, match="SEASON_SCOPE_MISMATCH"):
        build_score_count_source_manifest(wrong, parser_code_sha256=PARSER, contract=cfg)


def test_missing_duplicate_extra_or_naive_time_fail_closed():
    cfg = contract()
    rows = receipts(cfg)

    with pytest.raises(ScoreCountSourceError, match="REQUIRED_SOURCE_MISSING"):
        build_score_count_source_manifest(rows[:-1], parser_code_sha256=PARSER, contract=cfg)

    dup = rows + [deepcopy(rows[1])]
    with pytest.raises(ScoreCountSourceError, match="SOURCE_NAME_DUPLICATE"):
        build_score_count_source_manifest(dup, parser_code_sha256=PARSER, contract=cfg)

    extra = rows + [{
        "name": "mystery",
        "fetch_uri": "x",
        "origin_uri": "x",
        "retrieved_at_utc": "2026-10-05T13:00:00Z",
        "season_scope": [2018],
        "byte_sha256": "a" * 64,
        "parser_code_sha256": PARSER,
    }]
    with pytest.raises(ScoreCountSourceError, match="UNEXPECTED_SOURCE"):
        build_score_count_source_manifest(extra, parser_code_sha256=PARSER, contract=cfg)

    naive = receipts(cfg)
    naive[1]["retrieved_at_utc"] = "2026-10-05T13:00:00"
    with pytest.raises(ScoreCountSourceError, match="TIMEZONE_REQUIRED"):
        build_score_count_source_manifest(naive, parser_code_sha256=PARSER, contract=cfg)
