"""Precondition-record tests for the PGA H2H Leg-1 screen attempt (2026-10-28).

These tests guard the NOT_EXECUTABLE record in
research/pga_h2h_screen_20261028/: the DataGolf page parser, the pull
manifest's integrity, the coverage claims the report makes, and the
verifier's derived verdict.
"""
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(REPO, "research", "pga_h2h_screen_20261028")


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REC, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(name):
    with open(os.path.join(REC, name)) as f:
        return json.load(f)


def test_parser_extracts_embedded_reload_data():
    parse = _load_module("pga_parse_dg_pages", "parse_dg_pages.py")
    fixture = _load_json("fixture_masters_2025.json")
    payload = {"info": fixture["info"], "lb": fixture["lb_sample"]}
    html = "var reload_data = JSON.parse('" + json.dumps(payload) + "')"
    data = parse.extract_reload(html)
    assert data["info"]["event_id"] == "14"
    assert data["info"]["calendar_year"] == 2025
    rows = data["lb"]
    assert len(rows) == 3
    for r in rows:
        assert r["close"] not in (-9999.0, None)
        assert r["open"] not in (-9999.0, None)
        assert all(r.get(f"R{k}_sg") is not None for k in range(1, 5))


def test_parser_returns_none_without_marker():
    parse = _load_module("pga_parse_dg_pages_b", "parse_dg_pages.py")
    assert parse.extract_reload("<html>no data here</html>") is None


def test_manifest_is_complete_and_well_formed():
    manifest = _load_json("dg_pages_manifest.json")
    assert len(manifest) == 780
    for key, rec in manifest.items():
        assert rec["http"] == 200, key
        assert len(rec["sha256"]) == 64, key
        int(rec["sha256"], 16)
        assert rec["bytes"] > 10000, key
        assert rec["url"].endswith(key), key


def test_coverage_supports_report_claims():
    coverage = _load_json("dg_pages_coverage.json")
    seen = {}
    for r in coverage:
        if r.get("parse") == "OK":
            seen.setdefault((r["info_event_id"], r["date"]), r)
    for season, min_events in ((2023, 30), (2024, 30), (2025, 29)):
        ev = [r for r in seen.values() if r.get("season") == season]
        assert len(ev) == min_events, (season, len(ev))
        rows = sum(r["rows"] for r in ev)
        wc = sum(r.get("rows_with_close", 0) for r in ev)
        assert rows >= 3400, (season, rows)
        assert wc / rows >= 0.90, (season, wc, rows)


def test_owgr_probe_record_states_the_gap():
    probe = _load_json("owgr_probe.json")
    assert "No lawful, hash-pinnable copy" in probe["conclusion"]
    assert len(probe["probes"]) >= 3
    result = _load_json("screen_result.json")
    assert result["verdict"] == "NOT_EXECUTABLE"
    gap_ids = {g["id"] for g in result["gaps"]}
    assert "G-PGA-1" in gap_ids
    assert all(c["result"].startswith("NOT RUN") for c in result["criteria"])


def test_verifier_derives_not_executable(tmp_path):
    out = subprocess.run(
        [sys.executable, os.path.join(REC, "verify_preconditions.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert '"screen_verdict": "NOT_EXECUTABLE"' in out.stdout
    assert "G-PGA-1" in out.stdout
