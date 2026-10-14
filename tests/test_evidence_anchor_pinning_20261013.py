"""t127: offline checks of the pinned FreeTSA trust and the ONE recorded real
FreeTSA token over a fixed SYNTHETIC digest (fixture, not evidence).

DigiCert could not be recorded from the build host and stays unpinned, so the
configured dual-TSA quorum must still refuse. No network is used here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge import evidence_anchor as ea
from sportsedge import evidence_admission_gate as gate

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI required")

REPO = Path(__file__).resolve().parents[1]
FIX = json.loads((REPO / "tests/fixtures/anchor/tsa_fixture_t127.json").read_text())
FREETSA_SIGNER_SHA = "32e841a95cc1164101ffde41298ef2fc75c1c4372ef095e88a6bbd47dfb191fc"
FREETSA_CA_DER_SHA = "a6379e7cecc05faa3cbf076013d745e327bbbaa38c0b9af22469d4701d18aabc"
FREETSA_CA_FILE_SHA = "2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438"
# verify "now" fixed after the recorded genTime so the test is clock-independent
VERIFY_NOW = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)


def _der_sha(pem_path: Path) -> str:
    der = subprocess.run(["openssl", "x509", "-in", str(pem_path), "-outform", "DER"],
                         check=True, capture_output=True).stdout
    return hashlib.sha256(der).hexdigest()


def _tok():
    t = FIX["tokens"][0]
    assert t["provider"] == "freetsa"
    tok, req = base64.b64decode(t["token_der_b64"]), base64.b64decode(t["request_der_b64"])
    assert hashlib.sha256(tok).hexdigest() == t["token_sha256"]
    assert hashlib.sha256(req).hexdigest() == t["request_sha256"]
    return tok, req


def _freetsa():
    return {p.id: p for p in ea.load_config().providers}["freetsa"]


def test_config_pins_freetsa_only_and_flags_stay_off():
    cfg = ea.load_config()
    provs = {p.id: p for p in cfg.providers}
    assert provs["freetsa"].pinned and provs["freetsa"].signer_cert_sha256 == (FREETSA_SIGNER_SHA,)
    assert not provs["digicert"].pinned and provs["digicert"].status == "unpinned"
    assert cfg.capture_active is False and cfg.admission_active is False
    assert not ea.CAPTURE_ACTIVE and not ea.ADMISSION_ACTIVE


def test_committed_pems_match_recorded_hashes():
    ca = REPO / "config/anchors/freetsa_ca.pem"
    assert hashlib.sha256(ca.read_bytes()).hexdigest() == FREETSA_CA_FILE_SHA
    assert _der_sha(ca) == FREETSA_CA_DER_SHA
    assert _der_sha(REPO / "config/anchors/freetsa_tsa_signer.pem") == FREETSA_SIGNER_SHA
    raw = json.loads((REPO / "config/anchors/anchor_config_v1.json").read_text())
    assert raw["tsa_providers"][0]["ca_bundle_sha256"] == FREETSA_CA_FILE_SHA


def test_fixture_digest_is_the_synthetic_root():
    leaf = hashlib.sha256(FIX["synthetic_leaf_preimage"].encode()).hexdigest()
    assert leaf == FIX["leaf_sha256"]
    assert ea.batch_root([leaf]) == FIX["root_sha256"]


def test_real_freetsa_token_verifies_offline_against_pinned_trust():
    tok, req = _tok()
    ca, pins = ea.provider_trust(_freetsa())
    r = ea.tsa_verify(tok, FIX["root_sha256"], ca, None, list(pins), request_der=req, now=VERIFY_NOW)
    assert r.ok, r
    assert r.gen_time == datetime(2026, 10, 14, 2, 48, 22, tzinfo=timezone.utc)


def test_real_token_refused_for_other_digest_wrong_pin_and_wrong_ca():
    tok, req = _tok()
    ca, pins = ea.provider_trust(_freetsa())
    other = hashlib.sha256(b"different").hexdigest()
    assert ea.tsa_verify(tok, other, ca, None, list(pins), now=VERIFY_NOW).reason == "imprint_mismatch"
    assert ea.tsa_verify(tok, FIX["root_sha256"], ca, None, ["0" * 64], now=VERIFY_NOW).reason == "tsa_cert_not_pinned"
    g4 = subprocess.run(["openssl", "x509", "-in", str(REPO / "config/anchors/freetsa_tsa_signer.pem")],
                        check=True, capture_output=True).stdout  # a non-CA cert as trust anchor
    assert not ea.tsa_verify(tok, FIX["root_sha256"], g4, None, list(pins), now=VERIFY_NOW).ok
    other_req = ea.tsa_request(FIX["root_sha256"])  # fresh nonce
    assert ea.tsa_verify(tok, FIX["root_sha256"], ca, None, list(pins), request_der=other_req,
                         now=VERIFY_NOW).reason == "request_mismatch"


def test_real_token_cannot_reach_configured_quorum():
    tok, req = _tok()
    bundle = {"anchor_id": ea.ANCHOR_ID, "leaves": [FIX["leaf_sha256"]], "root": FIX["root_sha256"],
              "tsa_tokens": [{"provider": "freetsa", "token": tok, "request": req}]}
    cut = VERIFY_NOW + timedelta(days=1)
    assert ea.admit_configured_quorum(bundle, event_cutoff=cut).reason == "admission_not_activated"
    assert gate.anchored_admission(bundle, bound_sha256=FIX["leaf_sha256"],
                                   event_cutoff=cut).reason == "admission_not_activated"
    # even with only FreeTSA trusted, one provider is never a quorum
    ca, pins = ea.provider_trust(_freetsa())
    d = ea.admit_quorum(bundle, event_cutoff=cut, trust={"freetsa": (ca, pins)},
                        approved_ids=frozenset({ea.ANCHOR_ID}), now=VERIFY_NOW)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"
    assert d.details == ("freetsa:ok",)
