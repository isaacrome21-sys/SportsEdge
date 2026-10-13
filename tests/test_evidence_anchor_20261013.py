"""Offline adversarial tests for sportsedge.evidence_anchor.

No network. TSA tokens are produced locally by a throwaway TEST CA/TSA generated
in tmp dirs with the openssl CLI; nothing imitates FreeTSA or DigiCert.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge import evidence_anchor as ea

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI required")

LEAVES = [hashlib.sha256(f"receipt-{i}".encode()).hexdigest() for i in range(5)]

TSA_CNF = """
[ req ]
distinguished_name = dn
[ dn ]
[ v3_ca ]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
[ v3_tsa ]
basicConstraints = CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,timeStamping
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
[ tsa ]
default_tsa = tsa_config1
[ tsa_config1 ]
dir = {d}
serial = {d}/serial
signer_cert = {d}/tsa.pem
certs = {d}/tsa.pem
signer_key = {d}/tsa.key
signer_digest = sha256
default_policy = 1.2.3.4.1
digests = sha256
accuracy = secs:1
ordering = no
tsa_name = no
ess_cert_id_chain = no
ess_cert_id_alg = sha256
"""


def _ossl(*a, cwd):
    subprocess.run(["openssl", *a], cwd=cwd, check=True, capture_output=True)


def _make_ca(d: Path, name: str) -> dict:
    d.mkdir(parents=True)
    cnf = d / "tsa.cnf"
    cnf.write_text(TSA_CNF.format(d=d))
    (d / "serial").write_text("01\n")
    _ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
          "-days", "2", "-subj", f"/CN=SportsEdge TEST CA {name}", "-config", str(cnf),
          "-extensions", "v3_ca", cwd=d)
    _ossl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "tsa.key", "-out", "tsa.csr",
          "-subj", f"/CN=SportsEdge TEST TSA {name}", "-config", str(cnf), cwd=d)
    _ossl("x509", "-req", "-in", "tsa.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
          "-out", "tsa.pem", "-days", "2", "-extfile", str(cnf), "-extensions", "v3_tsa", cwd=d)
    der = subprocess.run(["openssl", "x509", "-in", "tsa.pem", "-outform", "DER"], cwd=d,
                         check=True, capture_output=True).stdout
    return {"dir": d, "ca": (d / "ca.pem").read_bytes(), "tsa_der_sha": hashlib.sha256(der).hexdigest()}


def _stamp(ca: dict, root_hex: str) -> bytes:
    d = ca["dir"]
    (d / "req.tsq").write_bytes(ea.tsa_request(root_hex))
    _ossl("ts", "-reply", "-config", str(d / "tsa.cnf"), "-queryfile", "req.tsq",
          "-out", "resp.tsr", cwd=d)
    return (d / "resp.tsr").read_bytes()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = tmp_path_factory.mktemp("anchor")
    a, b = _make_ca(base / "a", "A"), _make_ca(base / "b", "B")
    root = ea.batch_root(LEAVES)
    return {"a": a, "b": b, "root": root, "tok": _stamp(a, root)}


def _bundle(env, **kw):
    b = {"anchor_id": ea.ANCHOR_ID, "leaves": list(LEAVES), "root": env["root"],
         "tsa_tokens": [env["tok"]]}
    b.update(kw)
    return b


FUTURE = datetime.now(timezone.utc) + timedelta(hours=3)
APPROVED = frozenset({ea.ANCHOR_ID})


# ------------------------------------------------------------- not activated
def test_approved_list_is_empty_and_anchor_unregistered():
    assert ea.APPROVED_ANCHOR_IDS == frozenset()
    assert ea.ANCHOR_ID == "anchor:rfc3161+ots:v1"
    assert ea.ANCHOR_ID not in ea.APPROVED_ANCHOR_IDS


def test_default_admission_refuses_even_valid_bundle(env):
    d = ea.admit(_bundle(env), event_cutoff=FUTURE, ca_bundle_pem=env["a"]["ca"])
    assert not d.admitted and d.reason == "anchor_id_not_approved"


def test_network_refused_without_explicit_flag(env):
    with pytest.raises(ea.AnchorError):
        ea.tsa_stamp(env["root"], ea.TSA_URLS[0])
    with pytest.raises(ea.AnchorError):
        ea.ots_stamp(env["root"])


def test_tsa_stamp_rejects_unpinned_url(env):
    with pytest.raises(ea.AnchorError):
        ea.tsa_stamp(env["root"], "https://evil.example/tsr", allow_network=True,
                     post=lambda u, b: b"x")


def test_no_repository_code_imports_module():
    repo = Path(__file__).resolve().parents[1]
    hits = [p for p in (repo / "sportsedge").rglob("*.py")
            if p.name != "evidence_anchor.py" and "evidence_anchor" in p.read_text(errors="ignore")]
    hits += [p for p in (repo / ".github" / "workflows").glob("*.y*ml")
             if "evidence_anchor" in p.read_text(errors="ignore")]
    assert hits == []


# ------------------------------------------------------------- Merkle
def test_root_is_order_independent_and_deterministic():
    assert ea.batch_root(LEAVES) == ea.batch_root(list(reversed(LEAVES)))
    assert ea.batch_root(LEAVES[:1]) != LEAVES[0]  # leaf domain separation


@pytest.mark.parametrize("bad", [[], "abc", [LEAVES[0], LEAVES[0]], ["XYZ"], [LEAVES[0].upper()],
                                 [1], [None], [LEAVES[0][:-1]]])
def test_root_rejects_malformed(bad):
    with pytest.raises(ea.AnchorError):
        ea.batch_root(bad)


# ------------------------------------------------------------- happy path
def test_valid_token_admitted_with_test_approval(env):
    d = ea.admit(_bundle(env), event_cutoff=FUTURE, ca_bundle_pem=env["a"]["ca"],
                 approved_ids=APPROVED, pinned_tsa_cert_sha256=[env["a"]["tsa_der_sha"]])
    assert d.admitted, d
    assert abs((datetime.now(timezone.utc) - d.gen_time).total_seconds()) < 300


def test_tsa_verify_reports_gentime_and_hash(env):
    r = ea.tsa_verify(env["tok"], env["root"], env["a"]["ca"])
    assert r.ok and r.token_sha256 == hashlib.sha256(env["tok"]).hexdigest()


# ------------------------------------------------------------- adversarial
def test_tampered_root_refused(env):
    tampered = list(LEAVES)
    tampered[2] = hashlib.sha256(b"forged").hexdigest()
    d = ea.admit(_bundle(env, leaves=tampered), event_cutoff=FUTURE,
                 ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED)
    assert not d.admitted and d.reason == "root_mismatch"
    # claimed root rewritten to match tampered leaves: token no longer covers it
    d = ea.admit(_bundle(env, leaves=tampered, root=ea.batch_root(tampered)), event_cutoff=FUTURE,
                 ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED)
    assert not d.admitted and d.reason == "insufficient_verified_tokens"
    assert not ea.tsa_verify(env["tok"], "0" * 64, env["a"]["ca"]).ok


def test_gentime_after_cutoff_refused(env):
    now = datetime.now(timezone.utc)
    for cutoff, margin in [(now - timedelta(hours=1), 0), (now + timedelta(minutes=5), 900)]:
        d = ea.admit(_bundle(env), event_cutoff=cutoff, margin_s=margin,
                     ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED)
        assert not d.admitted and d.reason == "gentime_after_cutoff_minus_margin"


def test_wrong_cert_refused(env):
    d = ea.admit(_bundle(env), event_cutoff=FUTURE, ca_bundle_pem=env["b"]["ca"],
                 approved_ids=APPROVED)
    assert not d.admitted and d.reason == "insufficient_verified_tokens"
    # right CA but signer not in pin list
    d = ea.admit(_bundle(env), event_cutoff=FUTURE, ca_bundle_pem=env["a"]["ca"],
                 approved_ids=APPROVED, pinned_tsa_cert_sha256=[env["b"]["tsa_der_sha"]])
    assert not d.admitted
    # token from a different TSA altogether
    other = _stamp(env["b"], env["root"])
    d = ea.admit(_bundle(env, tsa_tokens=[other]), event_cutoff=FUTURE,
                 ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED)
    assert not d.admitted


@pytest.mark.parametrize("tokens", [[], None, [b""], "x", [None]])
def test_missing_token_refused(env, tokens):
    d = ea.admit(_bundle(env, tsa_tokens=tokens), event_cutoff=FUTURE,
                 ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED)
    assert not d.admitted and d.reason in {"missing_token", "insufficient_verified_tokens"}


def test_corrupted_token_bytes_refused(env):
    tok = env["tok"]
    sig = bytearray(tok)
    sig[-1] ^= 0xFF  # RSA signature byte
    assert not ea.tsa_verify(bytes(sig), env["root"], env["a"]["ca"]).ok
    # backdate the signed genTime (GeneralizedTime YYYYMMDDHHMMSSZ) by a year
    m = re.search(rb"\x18\x0f(20\d{2})", tok)
    assert m
    back = tok[:m.start(1)] + str(int(m.group(1)) - 1).encode() + tok[m.end(1):]
    assert not ea.tsa_verify(back, env["root"], env["a"]["ca"]).ok
    assert not ea.tsa_verify(b"\x30\x00garbage", env["root"], env["a"]["ca"]).ok


def test_duplicate_token_does_not_satisfy_two_token_minimum(env):
    d = ea.admit(_bundle(env, tsa_tokens=[env["tok"], env["tok"]]), event_cutoff=FUTURE,
                 ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED, min_tokens=2)
    assert not d.admitted and d.reason == "insufficient_verified_tokens"


def test_two_independent_tsas_satisfy_two_token_minimum(env):
    tb = _stamp(env["b"], env["root"])
    d = ea.admit(_bundle(env, tsa_tokens=[env["tok"], tb]), event_cutoff=FUTURE,
                 ca_bundle_pem=env["a"]["ca"] + env["b"]["ca"], approved_ids=APPROVED,
                 min_tokens=2)
    assert d.admitted, d


@pytest.mark.parametrize("kw", [
    {"event_cutoff": datetime(2026, 10, 13, 23, 0)},  # naive
    {"event_cutoff": "2026-10-13T23:00:00Z"},
    {"margin_s": -1}, {"margin_s": True}, {"margin_s": "900"},
    {"min_tokens": 0},
])
def test_wrong_type_parameters_fail_closed(env, kw):
    args = dict(event_cutoff=FUTURE, ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED)
    args.update(kw)
    assert not ea.admit(_bundle(env), **args).admitted


@pytest.mark.parametrize("bundle", [None, [], "x", {"anchor_id": 5}, {"anchor_id": ea.ANCHOR_ID},
                                    {"anchor_id": ea.ANCHOR_ID, "leaves": "abc"},
                                    {"anchor_id": ea.ANCHOR_ID, "leaves": [{}]}])
def test_malformed_bundle_never_raises(env, bundle):
    d = ea.admit(bundle, event_cutoff=FUTURE, ca_bundle_pem=env["a"]["ca"], approved_ids=APPROVED)
    assert not d.admitted


def test_missing_ca_bundle_refused(env):
    assert ea.tsa_verify(env["tok"], env["root"], b"").reason == "missing_ca_bundle"


# ------------------------------------------------------------- OTS (secondary)
def _ots(root_hex: str) -> bytes:
    # Synthetic structural proof (header + sha256 op + digest); not a calendar response.
    return ea.OTS_MAGIC + b"\x01\x08" + bytes.fromhex(root_hex) + b"\x00"


def test_ots_structure_ok_but_never_attested(env):
    r = ea.ots_verify(_ots(env["root"]), env["root"])
    assert r.ok and not r.bitcoin_attested


@pytest.mark.parametrize("mut", ["digest", "magic", "version", "op", "empty"])
def test_ots_adversarial(env, mut):
    p = bytearray(_ots(env["root"]))
    n = len(ea.OTS_MAGIC)
    if mut == "digest":
        p[n + 5] ^= 1
    elif mut == "magic":
        p[1] ^= 1
    elif mut == "version":
        p[n] = 2
    elif mut == "op":
        p[n + 1] = 0x02
    else:
        p = bytearray()
    assert not ea.ots_verify(bytes(p), env["root"]).ok
