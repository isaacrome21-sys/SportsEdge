"""Offline guards for the NBA quarter-score feed admission packet.

These tests never touch the network. They pin the admission invariants:
outcomes-feed-only scope (no pricing input, no in-play role, no credit),
five hash-pinned samples spanning the frozen fit span (engine season
2014) through the current season (2026) with at least one postseason and
one overtime game, quarter/half derivation arithmetic on every sample,
each sample's observation constructing a valid NBAPeriodObservation
under the repo's own form, and the refused candidates (NBA CDN 403,
stats.nba.com timeout, Basketball-Reference forward-coverage failure)
recorded as NOT_ADMITTED with their evidence.
"""

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "nba_quarter_score_feed_admission_20261028"
MANIFEST = json.loads((PACKET / "sample_manifest.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLE_IDS = {"400579520", "400579521", "401267340", "401859964", "401909877"}


def test_manifest_scope_is_outcomes_only():
    assert MANIFEST["source_id"] == "ESPN_SUMMARY_API"
    assert MANIFEST["sport"] == "NBA"
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert "FORWARD_GRADING_OUTCOMES" in MANIFEST["admitted_scope"]
    assert "DESIGN_SCREEN" in MANIFEST["admitted_scope"]
    assert "PREGAME_PRICING_INPUT" in MANIFEST["not_admitted_scope"]
    assert "IN_PLAY_FEED" in MANIFEST["not_admitted_scope"]


def test_five_samples_with_full_pins():
    samples = MANIFEST["samples"]
    assert {s["espn_event_id"] for s in samples} == SAMPLE_IDS
    for s in samples:
        assert SHA256_RE.match(s["sha256"])
        assert s["bytes"] > 100_000
        assert s["http_status"] == 200
        assert s["evidence_state"] == "verified-by-pull"
        assert s["game_id_namespace"] == "ESPN_EVENT_ID"
        assert s["checks"] == {"identity_match": True, "status_final": True,
                               "linescore_sums_match_finals": True}


def test_sample_span_covers_fit_span_postseason_and_overtime():
    by_id = {s["espn_event_id"]: s for s in MANIFEST["samples"]}
    seasons = {s["engine_season"] for s in by_id.values()}
    assert 2014 in seasons and 2026 in seasons
    assert any(s["season_type"] == 3 for s in by_id.values())  # postseason
    ot = by_id["401909877"]
    assert ot["home_ot_periods"] == [8] and ot["away_ot_periods"] == [7]
    for s in by_id.values():
        assert s["engine_season"] == s["season_year_espn"] - 1


def test_quarter_and_half_derivations_are_arithmetic_exact():
    for s in MANIFEST["samples"]:
        for side in ("home", "away"):
            ls = s[f"{side}_linescores"]
            assert s[f"{side}_quarters_regulation"] == ls[:4]
            assert s[f"{side}_ot_periods"] == ls[4:]
            assert s[f"{side}_half_scores"] == [ls[0] + ls[1], ls[2] + ls[3]]
            assert sum(ls) == s[f"{side}_final"]


def test_observations_satisfy_the_repo_form():
    from sportsedge.sports.nba.period_history import (
        NBAPeriodObservation, period_history_digest)
    rows = []
    for s in MANIFEST["samples"]:
        o = s["observation"]
        row = NBAPeriodObservation(
            game_id=o["game_id"],
            tipoff=datetime.fromisoformat(o["tipoff"]),
            observed_at=datetime.fromisoformat(o["observed_at"]),
            home_quarters=tuple(o["home_quarters"]),
            away_quarters=tuple(o["away_quarters"]),
            source=o["source"], source_version=o["source_version"])
        row.validate()
        assert list(row.home_quarters) == s["home_quarters_regulation"]
        assert list(row.away_quarters) == s["away_quarters_regulation"]
        rows.append(row)
    assert len(period_history_digest(rows)) == 64


def test_refused_candidates_are_recorded_not_admitted():
    cands = MANIFEST["candidate_probes"]
    cdn = cands["nba_cdn"]
    assert cdn["verdict"] == "NOT_ADMITTED"
    assert all(p["http_status"] == 403 for p in cdn["probes"])
    assert cands["stats_nba_com"]["verdict"] == "NOT_ADMITTED"
    bref = cands["basketball_reference"]
    assert bref["verdict"] == "NOT_ADMITTED"
    statuses = {p["label"]: p["http_status"] for p in bref["probes"]}
    assert statuses["bref_box_bos"] == 404 and statuses["bref_box_lal"] == 404
    assert statuses["bref_box_gsw2015"] == 200
    assert statuses["bref_box_sas_finals"] == 200


def test_cross_checks_are_recorded():
    checks = {c["check"] for c in MANIFEST["cross_checks"]}
    assert "identity_namespace" in checks
    assert "independent_source_agreement_bref" in checks
    assert "two_pull_split_stability" in checks
    identity = next(c for c in MANIFEST["cross_checks"]
                    if c["check"] == "identity_namespace")
    assert "401909877" in identity["detail"]


def test_pin_rule_is_content_level():
    rule = MANIFEST["pin_rule"]
    assert "SOURCE_CHANGED_AFTER_SNAPSHOT" in rule
    assert "extracted content" in rule


def test_record_states_the_binding_rules():
    lowered = RECORD.lower()
    assert "nbaperiodobservation" in lowered
    assert "not_final" in lowered
    assert "score_mismatch" in lowered
    assert "identity_unverified" in lowered
    assert "http 403" in lowered
    assert "not admitted" in lowered
    assert "point-in-time" in lowered
    assert "observed_at" in lowered
    assert "does **not** satisfy data gate §4.2" in lowered
    assert "live" in lowered and "sgp" in lowered  # not-unblocked list
    assert "the freeze is the owner's separate" in lowered
    assert "no espn payload files" in lowered


def test_puller_compiles_and_carries_the_refusals():
    script = (PACKET / "pull_espn_period_scores.py").read_text(encoding="utf-8")
    for code in ("SOURCE_UNAVAILABLE", "SCHEMA_INVALID", "IDENTITY_UNVERIFIED",
                 "NOT_FINAL", "SCORE_MISMATCH", "SOURCE_CHANGED_AFTER_SNAPSHOT"):
        assert code in script
    assert "ESPN_SUMMARY_API" in script
    assert "espn-summary-v1:20261028" in script
    compile(script, "pull_espn_period_scores.py", "exec")
