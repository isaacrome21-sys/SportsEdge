"""Integration check: v1 CLI provenance -> wrapper -> stored outcome.

This is the composition test for the integration branch: the Phase 7
v1 capture CLI (with the Elo-leg provenance stack) and the
receipt-first safeguard wrapper (rounds 1-5) were built on separate
lines that shared only the Phase 7 base, so no earlier suite ran the
CLI's ``elo_schedule_provenance`` emission and the wrapper's verbatim
persistence of it in the same flow. This test does:

  * the v1 CLI runs its real ``main()`` — real Elo leg, real
    provenance machinery (recording getter, manifest, content
    hashes, PIT gate, freshness policy), real record assembly and
    write-once archive write;
  * the wrapper runs its real ``capture_with_receipt`` — real
    receipt, real input snapshot, real archived-record verification,
    real ACK journal (no stub anywhere in the wrapper or journal);
  * the stored ARCHIVED outcome must carry the CLI's
    ``elo_schedule_provenance`` object byte-for-byte unchanged
    (deep equality, and equality of the canonical JSON form);
  * a REFUSED flow (real CLI market refusal) must store an outcome
    carrying NEITHER ``elo_schedule_provenance`` NOR
    ``provenance_note``.

What is fixtured, and why (the smallest honest offline fixture):

  * The schedule payload: the CLI's Elo leg fetches the MLB schedule
    over HTTP. The payload is supplied locally through the CLI's own
    test seam — ``cap._default_schedule_getter``, the exact seam the
    CLI's provenance tests patch — returning a StatsAPI-shaped
    payload dict. Everything downstream of the getter (the shared
    fetcher's cache, the recording getter's observation stamp, the
    provenance manifest, both content hashes) is the real code.
  * The production pricer: the frozen production path
    (``artifacts/run_it_full.py``) fail-closes OFFLINE by design —
    its prepricing gate refuses with BLOCKED_PREPRICING_FIXTURE_
    UNVERIFIED when it cannot verify the fixture from live sources,
    so the real CLI can never reach its CAPTURED verdict (the only
    path that emits ``elo_schedule_provenance``) without network.
    ``cap.production_probability`` — the same seam the CLI's own
    suite patches — is therefore replaced with a fixed candidate
    probability. The pricer is not what this check is about: Lane A
    pricing has its own suites; this check is about the provenance
    object crossing the CLI -> wrapper -> journal boundary intact.
  * The clock: ``cap._utcnow`` (the CLI's documented clock seam) is
    pinned just before the fixture's first pitch so the Elo leg's
    observation stamps are pre-kickoff and within the freshness
    bound. The CLI's as-of instant is the real clock, so the fixture
    kickoff is in the future, like the CLI suite's own fixtures.

No live capture is attempted; the fixture game is synthetic and the
archive lives in a tmp directory.
"""
import contextlib
import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.backtest import capture_receipt as rcpt

REPO_ROOT = Path(__file__).resolve().parents[1]
V1_SCRIPT = REPO_ROOT / "scripts" / "capture_strict_mlb_record.py"
V2_SCRIPT = REPO_ROOT / "scripts" / "capture_strict_mlb_record_v2.py"

KICKOFF_UTC = "2027-04-01T23:05:00Z"
PINNED_NOW = datetime(2027, 4, 1, 22, 40, tzinfo=timezone.utc)
QUOTE_AT = "2027-04-01T22:40:00Z"  # 1500s before first pitch, paired

CLE = "Cleveland Guardians"
TB = "Tampa Bay Rays"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _game(pk, date, away, home, away_score, home_score):
    return {"gamePk": pk, "gameDate": date, "gameType": "R",
            "status": {"detailedState": "Final"},
            "teams": {"away": {"team": {"name": away},
                               "score": away_score},
                      "home": {"team": {"name": home},
                               "score": home_score}}}


def _schedule_payload():
    """StatsAPI-shaped schedule: three Final regular-season games,
    two of them involving the fixture teams, all before kickoff."""
    return {"dates": [
        {"date": "2026-10-08", "games": [
            _game(1, "2026-10-08T23:05:00Z", CLE, TB, 2, 5)]},
        {"date": "2026-10-09", "games": [
            _game(2, "2026-10-09T23:05:00Z", TB, CLE, 3, 1)]},
        {"date": "2026-10-10", "games": [
            _game(3, "2026-10-10T23:05:00Z", "New York Yankees",
                  "Boston Red Sox", 4, 6)]},
    ]}


def _capture_input(**overrides):
    spec = {
        "schema": "SPORTSEDGE_STRICT_CAPTURE_INPUT_V1",
        "away": CLE, "home": TB,
        "kickoff_utc": KICKOFF_UTC, "series_id": "2027-TEST-CLE-TB",
        "market": "ML", "selection": "HOME", "line": "ML",
        "book": "draftkings",
        "selection_american": -163,
        "selection_captured_at_utc": QUOTE_AT,
        "opposite_american": 145,
        "opposite_captured_at_utc": QUOTE_AT,
        "quote_source": "offline integration fixture (no live capture)",
    }
    spec.update(overrides)
    return spec


def _production_fixture(payload_row, now):
    """Stand-in for the frozen production pricer at its own seam.

    The real pricer fail-closes offline by design (see the module
    docstring); this returns a fixed, clearly-labeled candidate so
    the CLI can reach its CAPTURED verdict and the provenance flow —
    the actual subject of this check — can be exercised end to end.
    """
    return 0.60, {
        "candidate": {"lane": "LANE_A_INDEPENDENT",
                      "label": "MARKET_BLIND", "win_p": 0.60,
                      "push_p": 0.0, "loss_p": 0.40},
        "market_anchored": None,
    }, {"status": "PRICED_OFFLINE_FIXTURE"}


def _run_flow(tmp_path, monkeypatch, spec):
    """Drive the real wrapper with a runner that executes the real
    v1 CLI's main() in-process (the subprocess boundary is the one
    thing replaced — it is what makes the CLI's offline seams
    reachable; the wrapper and the journal run unstubbed)."""
    cap = _load_module("capture_strict_mlb_record_integration",
                       V1_SCRIPT)
    v2 = _load_module("capture_strict_mlb_record_v2_integration",
                      V2_SCRIPT)
    monkeypatch.setattr(cap, "SCHEDULE_CACHE_DIR",
                        tmp_path / "schedule_cache")
    monkeypatch.setattr(cap, "_default_schedule_getter",
                        lambda url: _schedule_payload())
    monkeypatch.setattr(cap, "_utcnow", lambda: PINNED_NOW)
    monkeypatch.setattr(cap, "production_probability",
                        _production_fixture)
    captured = {}

    def runner(input_path, archive_dir):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            rc = cap.main(["--input", str(input_path),
                           "--archive-dir", str(archive_dir)])
        captured["stdout"] = out.getvalue()
        return {"exit_code": rc, "stdout": out.getvalue(),
                "stderr": err.getvalue()}

    input_path = tmp_path / "capture_input.json"
    input_path.write_text(json.dumps(spec, indent=2),
                          encoding="utf-8")
    archive = tmp_path / "archive"
    report = v2.capture_with_receipt(input_path, archive,
                                     runner=runner)
    return report, archive, captured


def test_cli_provenance_reaches_stored_outcome_unchanged(
        tmp_path, monkeypatch):
    report, archive, captured = _run_flow(
        tmp_path, monkeypatch, _capture_input())
    assert report["status"] == "ARCHIVED"
    assert report["record_path"] and \
        Path(report["record_path"]).exists()

    verdict = json.loads(captured["stdout"])
    assert verdict["status"] == "CAPTURED"
    provenance = verdict["elo_schedule_provenance"]
    # The CLI really produced the full provenance object: fresh HTTP
    # observation at the pinned instant, PIT established, fresh.
    assert provenance["source_origin"] == "HTTP"
    assert provenance["source_observed_at_utc"] == \
        PINNED_NOW.isoformat()
    assert provenance["pit_provenance_status"] == \
        "PIT_PROVENANCE_ESTABLISHED"
    assert provenance["schedule_freshness"] == "WITHIN_BOUND"
    assert len(provenance["schedule_content_sha256"]) == 64
    assert len(provenance["schedule_manifest_lookup_sha256"]) == 64

    entries = rcpt.read_outcomes(archive)
    archived = [e for e in entries
                if e.get("receipt_id") == report["receipt_id"]
                and e.get("outcome") == "ARCHIVED"]
    assert len(archived) == 1
    stored = archived[0]
    assert stored["record_verified"] is True
    # Byte-for-byte: deep equality, and equality of the canonical
    # JSON serialization of the object as stored vs as emitted.
    assert stored["elo_schedule_provenance"] == provenance
    assert json.dumps(stored["elo_schedule_provenance"],
                      sort_keys=True) == \
        json.dumps(provenance, sort_keys=True)
    # A provenance-carrying outcome has no null-provenance note.
    assert "provenance_note" not in stored


def test_refused_flow_outcome_carries_no_provenance_fields(
        tmp_path, monkeypatch):
    spec = _capture_input(market="SPREAD", line=-1.5)
    report, archive, captured = _run_flow(tmp_path, monkeypatch, spec)
    assert report["status"] == "REFUSED"
    assert "EXISTING_MODEL_PROBABILITY_UNAVAILABLE_FOR_MARKET" in \
        report["refusal_reason"]
    verdict = json.loads(captured["stdout"])
    assert verdict["status"] == "CAPTURE_REFUSED"
    assert "elo_schedule_provenance" not in verdict

    entries = rcpt.read_outcomes(archive)
    refused = [e for e in entries
               if e.get("receipt_id") == report["receipt_id"]
               and e.get("outcome") == "REFUSED"]
    assert len(refused) == 1
    assert "elo_schedule_provenance" not in refused[0]
    assert "provenance_note" not in refused[0]
    # The refusal archived no evaluator record.
    assert not (archive / "captures").exists()
