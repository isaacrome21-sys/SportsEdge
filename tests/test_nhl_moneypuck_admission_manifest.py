"""Offline guards + behavior tests for the MoneyPuck NHL admission packet.

Two layers, both fully offline (no network):
1. Packet guards, in the shape of the BartTorvik live-route guards: the
   committed sample manifest and admission record must state the binding
   disciplines (strictly-prior filtering, vintage pinning, snapshot
   refusals, attempt-2-only pricing path, NHL API role unchanged).
2. Collector behavior: the collector module is exercised with fake
   fetchers to prove the refusal paths (SOURCE_CHANGED_AFTER_SNAPSHOT,
   SCHEMA_INVALID, STALE_SNAPSHOT, LOOKAHEAD_RISK), manifest
   verification, and the strictly-prior filter itself.
"""

import csv
import hashlib
import importlib.util
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "nhl_moneypuck_admission_20261028"
MANIFEST = json.loads((PACKET / "sample_manifest.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

spec = importlib.util.spec_from_file_location(
    "collect_moneypuck", PACKET / "collect_moneypuck.py")
COLLECTOR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(COLLECTOR)


# ---------------------------------------------------------------- packet

def test_manifest_role_is_attempt2_input_only():
    assert MANIFEST["source_id"] == "MONEYPUCK"
    assert MANIFEST["sport"] == "NHL"
    assert MANIFEST["admission_role"] == "DESIGN_AND_FORWARD_PRICING_INPUT"
    assert MANIFEST["pricing_path"] == "NHL_ATTEMPT_2_PREREG_ONLY"
    assert MANIFEST["promotes_model"] is False
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["play_eligible"] is False


def test_samples_are_hash_pinned_with_vintages():
    by_key = {(s["surface"], s["season"]) for s in MANIFEST["samples"]}
    assert ("season_skaters", 2026) in by_key
    assert ("season_goalies", 2026) in by_key
    assert ("season_skaters", 2025) in by_key
    assert ("season_goalies", 2025) in by_key
    assert ("all_teams", None) in by_key
    for sample in MANIFEST["samples"]:
        assert SHA256_RE.match(sample["sha256"])
        assert sample["bytes"] > 0
        assert sample["evidence_state"] == "verified-by-pull"
        if sample["surface"] == "season_skaters":
            assert sample["xg_model_vintage"] == (
                "rebuilt_2026_27" if sample["season"] >= 2026
                else "undisclosed_legacy")
            assert sample["data_rows"] > 0
            assert sample["game_date_min"] < sample["game_date_max"]


def test_record_states_the_binding_rules():
    lowered = RECORD.lower()
    assert "strictly-prior" in lowered or "strictly prior" in lowered
    assert "rewritten in place" in lowered
    assert "source_changed_after_snapshot" in lowered
    assert "stale_snapshot" in lowered
    assert "schema_invalid" in lowered
    assert "lookahead_risk" in lowered
    assert "rebuilt" in lowered and "2026-27" in RECORD
    assert "pricing_input: false" in RECORD  # NHL API role unchanged
    assert "no moneypuck data files are committed" in lowered
    assert "attempt 2" in lowered


def test_strictly_prior_demonstration_is_recorded():
    demo = MANIFEST["strictly_prior_demonstration"]
    assert demo["max_gameDate_used"] < demo["cutoff_gameDate_exclusive"]
    assert demo["games_used"] > 0
    assert demo["rows_excluded_same_or_later"] > 0
    assert demo["evidence_state"] == "verified-by-pull"


# ------------------------------------------------------------- collector

SKATER_HEADER = ["playerId", "gameId", "season", "playerTeam",
                 "opposingTeam", "gameDate", "situation", "OnIce_F_xGoals",
                 "OnIce_A_xGoals", "onIce_xGoalsPercentage"]


def _zip_bytes(rows, header, member="2099.csv"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        zf.writestr(member, text.getvalue())
    return buf.getvalue()


def _skater_row(game_date, game_id=100):
    return {"playerId": 1, "gameId": game_id, "season": 2099,
            "playerTeam": "ANA", "opposingTeam": "NYI",
            "gameDate": game_date, "situation": "all",
            "OnIce_F_xGoals": 3.1, "OnIce_A_xGoals": 2.2,
            "onIce_xGoalsPercentage": 0.58}


def _fetcher(payload, headers=None):
    def fetch(url, part_path):
        Path(part_path).write_bytes(payload)
        return (headers or {"Last-Modified": "Wed, 28 Oct 2026 00:00:00 GMT"},
                len(payload), hashlib.sha256(payload).hexdigest())
    return fetch


def test_pull_happy_path_writes_manifest_entry(tmp_path):
    payload = _zip_bytes([_skater_row("20991001"), _skater_row("20991003", 101)],
                         SKATER_HEADER)
    entry = COLLECTOR.pull_one("season_skaters", 2099, tmp_path, None, None,
                               _fetcher(payload))
    assert entry["data_rows"] == 2
    assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
    assert (tmp_path / "season_skaters_2099.zip").exists()
    assert entry["xg_model_vintage"] == "rebuilt_2026_27"


def test_changed_vintage_is_refused_and_pin_preserved(tmp_path):
    payload = _zip_bytes([_skater_row("20991001")], SKATER_HEADER)
    COLLECTOR.pull_one("season_skaters", 2099, tmp_path, None, None,
                       _fetcher(payload))
    other = _zip_bytes([_skater_row("20991002")], SKATER_HEADER)
    try:
        COLLECTOR.pull_one("season_skaters", 2099, tmp_path, "f" * 64, None,
                           _fetcher(other))
        raise AssertionError("expected Refusal")
    except COLLECTOR.Refusal as refusal:
        assert refusal.code == "SOURCE_CHANGED_AFTER_SNAPSHOT"
    assert (tmp_path / "season_skaters_2099.zip").read_bytes() == payload


def test_schema_drift_is_refused(tmp_path):
    header = [h for h in SKATER_HEADER if h != "situation"]
    row = {k: v for k, v in _skater_row("20991001").items() if k != "situation"}
    payload = _zip_bytes([row], header)
    try:
        COLLECTOR.pull_one("season_skaters", 2099, tmp_path, None, None,
                           _fetcher(payload))
        raise AssertionError("expected Refusal")
    except COLLECTOR.Refusal as refusal:
        assert refusal.code == "SCHEMA_INVALID"
    assert not (tmp_path / "season_skaters_2099.zip").exists()


def test_stale_current_season_snapshot_is_refused(tmp_path):
    payload = _zip_bytes([_skater_row("20991001")], SKATER_HEADER)
    stale = _fetcher(payload, {"Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"})
    try:
        COLLECTOR.pull_one("season_skaters", 2099, tmp_path, None, 2099, stale)
        raise AssertionError("expected Refusal")
    except COLLECTOR.Refusal as refusal:
        assert refusal.code == "STALE_SNAPSHOT"


def test_manifest_verification_detects_tampering(tmp_path):
    payload = _zip_bytes([_skater_row("20991001")], SKATER_HEADER)
    entry = COLLECTOR.pull_one("season_skaters", 2099, tmp_path, None, None,
                               _fetcher(payload))
    manifest = {"samples": [entry]}
    ok, _ = COLLECTOR.verify_manifest(tmp_path, manifest)
    assert ok
    (tmp_path / entry["stored_as"]).write_bytes(b"tampered")
    ok, results = COLLECTOR.verify_manifest(tmp_path, manifest)
    assert not ok
    assert results[0]["status"] == "PIN_MISMATCH"


def _team_row(game_date, season=2026, xgf="3.0", xga="2.0"):
    return {"season": str(season), "playerTeam": "ANA", "situation": "all",
            "gameDate": str(game_date), "xGoalsFor": xgf,
            "xGoalsAgainst": xga, "goalsFor": "2", "goalsAgainst": "1"}


def test_strictly_prior_filter_excludes_same_day_and_later():
    rows = [_team_row(20261010), _team_row(20261020, xgf="9.9", xga="9.9"),
            _team_row(20261021, xgf="9.9", xga="9.9"),
            _team_row(20251010, season=2025, xgf="7.7", xga="7.7")]
    agg = COLLECTOR.strictly_prior_team_aggregate(rows, "ANA", 20261020, 2026)
    assert agg["games_used"] == 1
    assert agg["max_gameDate_used"] == 20261010
    assert agg["rows_excluded_same_or_later"] == 2
    assert agg["xGoalsFor_sum"] == 3.0


def test_strictly_prior_filter_refuses_an_empty_past():
    rows = [_team_row(20261020)]
    try:
        COLLECTOR.strictly_prior_team_aggregate(rows, "ANA", 20261020, 2026)
        raise AssertionError("expected Refusal")
    except COLLECTOR.Refusal as refusal:
        assert refusal.code == "LOOKAHEAD_RISK"
