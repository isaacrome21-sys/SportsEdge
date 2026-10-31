"""Manifest tests for the PGA DataGolf content-pin packet (G-PGA-2).

Guards research/pga_datagolf_content_admission_20261028/: the committed
DRAFT content manifest's internal consistency and corpus hash, the
canonical form's fixed point on the committed fixture event, and the
extractor's field mapping (consumed vs excluded) on synthetic input.
The workspace pull store is NOT required: store-backed verification is
verify_content_pins.py's full mode, exercised in the build record.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKT = os.path.join(REPO, "research", "pga_datagolf_content_admission_20261028")


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PKT, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest():
    with open(os.path.join(PKT, "content_manifest.json")) as f:
        return json.load(f)


def test_manifest_shape_and_counts():
    m = _manifest()
    assert m["status"] == "DRAFT — NOT ADMITTED"
    assert m["event_count"] == 157 == len(m["events"])
    assert m["row_count"] == 19630 == sum(e["rows"] for e in m["events"])
    assert m["raw_source"]["pages"] == 780
    assert m["raw_source"]["pages_reverified_against_raw_pins"] == 780
    seasons = {}
    for e in m["events"]:
        seasons[e["season"]] = seasons.get(e["season"], 0) + 1
    assert seasons == {2020: 20, 2021: 25, 2022: 26, 2023: 27, 2024: 30, 2025: 29}


def test_corpus_hash_recomputes_from_event_pins():
    ext = _load_module("pga_extract_for_hash", "extract_dg_content.py")
    m = _manifest()
    assert ext.corpus_hash(m["events"]) == m["corpus_sha256"]
    assert len(m["corpus_sha256"]) == 64


def test_fixture_event_is_canonical_fixed_point_and_matches_pin():
    ext = _load_module("pga_extract_for_fixture", "extract_dg_content.py")
    with open(os.path.join(PKT, "fixture_event_14_2025.json"), "rb") as f:
        raw = f.read()
    obj = json.loads(raw.decode("utf-8"))
    # Canonical form is a fixed point: re-serializing the parsed fixture
    # reproduces the committed bytes exactly.
    assert ext.canonical_bytes(obj) == raw
    digest = hashlib.sha256(raw).hexdigest()
    entry = next(
        e for e in _manifest()["events"]
        if e["event_id"] == "14" and e["date"] == "2025-04-13"
    )
    assert entry["content_sha256"] == digest
    assert entry["rows"] == len(obj["rows"]) == 95


def test_fixture_rows_carry_dg_pts_only_under_excluded():
    with open(os.path.join(PKT, "fixture_event_14_2025.json")) as f:
        obj = json.load(f)
    for row in obj["rows"]:
        assert "dg_pts" not in row and "dg_rank" not in row
        assert set(row["excluded"]) == {"dg_pts", "dg_rank"}


def test_extractor_field_mapping_on_synthetic_page():
    ext = _load_module("pga_extract_for_mapping", "extract_dg_content.py")
    lb_row = {
        "dg_id": 1, "player_name": "Test, A", "fin": "1", "total": -5,
        "R1": 68, "R1_par": 72, "R1_sg": 2.5,
        "R2": 70, "R2_par": 72, "R2_sg": 0.5,
        "R3": None, "R3_par": 72, "R3_sg": None,
        "R4": None, "R4_par": 72, "R4_sg": None,
        "open": 21.0, "close": 19.0, "owgr_rank": -9999,
        "dg_pts": 9.5, "dg_rank": 12,
    }
    row = ext.build_row(lb_row)
    assert [r["r"] for r in row["rounds"]] == [1, 2]  # unplayed rounds absent
    assert row["owgr_rank"] == -9999  # sentinel preserved; validity is a consumer rule
    assert row["excluded"] == {"dg_pts": 9.5, "dg_rank": 12}
    assert set(row) == set(ext.CONSUMED_ROW_KEYS)


def test_extractor_is_deterministic_on_synthetic_input():
    ext = _load_module("pga_extract_for_determinism", "extract_dg_content.py")
    info = {"event_id": "7", "calendar_year": 2024, "season": 2024,
            "date": "2024-05-05", "display_name": "Synthetic", "tour": "pga",
            "num_rounds": 4}
    lb = [{"dg_id": 2, "player_name": "Test, B", "fin": "T3", "total": -2,
           "R1": 70, "R1_par": 72, "R1_sg": 1.0, "open": 30.0, "close": 28.0,
           "owgr_rank": 44, "dg_pts": 3.25, "dg_rank": 40}]
    page = {"request_key": "pga-tour/7/2024", "file": "pga_7_2024.html",
            "page_sha256": "0" * 64}
    a = ext.build_event_content(info, lb, page)
    b = ext.build_event_content(info, lb, page)
    assert ext.canonical_bytes(a) == ext.canonical_bytes(b)
    assert ext.content_sha256(a) == ext.content_sha256(b)


def test_verify_script_manifest_only_mode():
    out = subprocess.run(
        [sys.executable, os.path.join(PKT, "verify_content_pins.py"), "--manifest-only"],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "manifest internally consistent" in out.stdout
