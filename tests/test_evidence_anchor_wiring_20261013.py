"""Offline tests for the approved-anchor wiring (t124): config, dual-TSA quorum,
request/nonce binding, genTime checks, full OTS proof parsing, Object Lock writer.

Synthetic fixtures only. TSA tokens come from throwaway TEST CAs generated with
the openssl CLI in tmp dirs; OTS proofs and Bitcoin headers are synthetic bytes.
No network, no real FreeTSA/DigiCert material, no credentials.
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
from sportsedge import evidence_lock_store as ls

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI required")

LEAVES = [hashlib.sha256(f"t124-receipt-{i}".encode()).hexdigest() for i in range(7)]
REPO = Path(__file__).resolve().parents[1]

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



def _stamp_req(ca: dict, req: bytes) -> bytes:
    d = ca["dir"]
    (d / "req2.tsq").write_bytes(req)
    _ossl("ts", "-reply", "-config", str(d / "tsa.cnf"), "-queryfile", "req2.tsq",
          "-out", "resp2.tsr", cwd=d)
    return (d / "resp2.tsr").read_bytes()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = tmp_path_factory.mktemp("t124")
    a, b = _make_ca(base / "a", "A"), _make_ca(base / "b", "B")
    root = ea.batch_root(LEAVES)
    trust = {"tsa_a": (a["ca"], [a["tsa_der_sha"]]), "tsa_b": (b["ca"], [b["tsa_der_sha"]])}
    return {"a": a, "b": b, "root": root, "ta": _stamp(a, root), "tb": _stamp(b, root),
            "trust": trust, "base": base}


APPROVED = frozenset({ea.ANCHOR_ID})


def _cut(h=3):
    return datetime.now(timezone.utc) + timedelta(hours=h)


def _qb(env, entries, **kw):
    b = {"anchor_id": ea.ANCHOR_ID, "leaves": list(LEAVES), "root": env["root"], "tsa_tokens": entries}
    b.update(kw)
    return b


# ------------------------------------------------------------- config
def test_repo_config_records_owner_decision_and_keeps_flags_off():
    cfg = ea.load_config()
    assert cfg.approved_anchor_ids == frozenset({"anchor:rfc3161+ots:v1"})
    assert cfg.capture_active is False and cfg.admission_active is False
    assert cfg.owner_decision["approved_at"].startswith("2026-10-13T20:23")
    assert "DESIGN APPROVAL ONLY" in cfg.owner_decision["scope"]
    assert cfg.min_distinct_providers == 2
    assert {p.id for p in cfg.providers} == {"freetsa", "digicert"}
    assert {p.url for p in cfg.providers} == set(ea.TSA_URLS)
    assert ea.APPROVED_ANCHOR_IDS == cfg.approved_anchor_ids
    assert not ea.CAPTURE_ACTIVE and not ea.ADMISSION_ACTIVE


def test_real_providers_are_unpinned_and_refused():
    for p in ea.load_config().providers:
        assert not p.pinned
        with pytest.raises(ea.AnchorError):
            ea.provider_trust(p)


def _write(tmp_path, mut):
    raw = json.loads((REPO / "config/anchors/anchor_config_v1.json").read_text())
    mut(raw)
    f = tmp_path / "c.json"
    f.write_text(json.dumps(raw))
    return f


@pytest.mark.parametrize("mut", [
    lambda r: r.__setitem__("schema", "x"),
    lambda r: r["owner_decision"].__setitem__("anchor_ids", []),
    lambda r: r.pop("owner_decision"),
    lambda r: r["activation"].__setitem__("capture_active", "false"),
    lambda r: r.pop("activation"),
    lambda r: r["tsa_providers"][0].__setitem__("signer_cert_sha256", ["zz"]),
    lambda r: r["tsa_providers"].append(dict(r["tsa_providers"][0])),
    lambda r: r["quorum"].__setitem__("min_distinct_providers", 0),
    lambda r: r.__setitem__("approved_anchor_ids", "anchor:rfc3161+ots:v1"),
])
def test_malformed_config_rejected(tmp_path, mut):
    with pytest.raises(ea.AnchorError):
        ea.load_config(_write(tmp_path, mut))


def test_missing_config_rejected(tmp_path):
    with pytest.raises(ea.AnchorError):
        ea.load_config(tmp_path / "nope.json")


def test_provider_trust_reads_pinned_bundle_inside_repo(tmp_path, env):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ca.pem").write_bytes(env["a"]["ca"])
    p = ea.TsaProvider("x", ea.TSA_URLS[0], "config/ca.pem", (env["a"]["tsa_der_sha"],), "pinned")
    assert ea.provider_trust(p, tmp_path)[0] == env["a"]["ca"]
    bad = ea.TsaProvider("x", ea.TSA_URLS[0], "../escape.pem", (env["a"]["tsa_der_sha"],), "pinned")
    with pytest.raises(ea.AnchorError):
        ea.provider_trust(bad, tmp_path)


def test_stamping_refused_even_with_network_flag(env):
    with pytest.raises(ea.AnchorError, match="capture not activated"):
        ea.tsa_stamp(env["root"], ea.TSA_URLS[0], allow_network=True, post=lambda u, b: b"x")


# ------------------------------------------------------------- dual-TSA quorum
def test_quorum_default_path_not_activated(env):
    d = ea.admit_quorum(_qb(env, [{"provider": "tsa_a", "token": env["ta"]},
                                  {"provider": "tsa_b", "token": env["tb"]}]),
                        event_cutoff=_cut(), trust=env["trust"])
    assert not d.admitted and d.reason == "admission_not_activated"


def test_two_distinct_tsas_admitted(env):
    d = ea.admit_quorum(_qb(env, [{"provider": "tsa_a", "token": env["ta"]},
                                  {"provider": "tsa_b", "token": env["tb"]}]),
                        event_cutoff=_cut(), trust=env["trust"], approved_ids=APPROVED)
    assert d.admitted, d


def test_single_tsa_twice_does_not_meet_quorum(env):
    t2 = _stamp(env["a"], env["root"])
    d = ea.admit_quorum(_qb(env, [{"provider": "tsa_a", "token": env["ta"]},
                                  {"provider": "tsa_a", "token": t2}]),
                        event_cutoff=_cut(), trust=env["trust"], approved_ids=APPROVED)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"


def test_token_mislabelled_as_other_provider_refused(env):
    # tsa_a's token claimed to be from tsa_b: verified against B's CA/pins -> fails
    d = ea.admit_quorum(_qb(env, [{"provider": "tsa_a", "token": env["ta"]},
                                  {"provider": "tsa_b", "token": env["ta"]}]),
                        event_cutoff=_cut(), trust=env["trust"], approved_ids=APPROVED)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"
    assert any(x.startswith("tsa_b:") and not x.endswith(":ok") for x in d.details)


def test_signer_pin_enforced_per_provider(env):
    trust = dict(env["trust"])
    trust["tsa_b"] = (env["b"]["ca"], ["0" * 64])
    d = ea.admit_quorum(_qb(env, [{"provider": "tsa_a", "token": env["ta"]},
                                  {"provider": "tsa_b", "token": env["tb"]}]),
                        event_cutoff=_cut(), trust=trust, approved_ids=APPROVED)
    assert not d.admitted and "tsa_b:tsa_cert_not_pinned" in d.details


def test_pinned_extra_embedded_ca_must_not_impersonate_actual_signer(tmp_path):
    # A valid token may contain CA/intermediate certs in addition to its signer.
    # Pinning one of those extra certs must NEVER establish signer identity.
    ca = _make_ca(tmp_path / "extra", "EXTRA")
    d = ca["dir"]
    (d / "both.pem").write_bytes((d / "tsa.pem").read_bytes() + (d / "ca.pem").read_bytes())
    cnf = d / "tsa.cnf"
    old_config = cnf.read_text()
    cnf.write_text(old_config.replace(f"certs = {d}/tsa.pem", f"certs = {d}/both.pem"))
    root = ea.batch_root(LEAVES)
    tok = _stamp(ca, root)
    ca_der = subprocess.run(["openssl", "x509", "-in", "ca.pem", "-outform", "DER"],
                            cwd=d, check=True, capture_output=True).stdout
    wrong_pin = hashlib.sha256(ca_der).hexdigest()
    assert ea.tsa_verify(tok, root, ca["ca"], pinned_tsa_cert_sha256=[ca["tsa_der_sha"]]).ok
    bad = ea.tsa_verify(tok, root, ca["ca"], pinned_tsa_cert_sha256=[wrong_pin])
    assert not bad.ok and bad.reason == "tsa_cert_not_pinned"


def test_unknown_provider_and_malformed_entries(env):
    d = ea.admit_quorum(_qb(env, [{"provider": "evil", "token": env["ta"]}, "x", {"token": env["tb"]}]),
                        event_cutoff=_cut(), trust=env["trust"], approved_ids=APPROVED)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"


def test_quorum_below_two_refused(env):
    d = ea.admit_quorum(_qb(env, [{"provider": "tsa_a", "token": env["ta"]}]), event_cutoff=_cut(),
                        trust=env["trust"], approved_ids=APPROVED, min_distinct_providers=1)
    assert not d.admitted and d.reason == "quorum_below_two"


def test_quorum_every_member_must_be_pregame(env):
    now = datetime.now(timezone.utc)
    d = ea.admit_quorum(_qb(env, [{"provider": "tsa_a", "token": env["ta"]},
                                  {"provider": "tsa_b", "token": env["tb"]}]),
                        event_cutoff=now + timedelta(minutes=5), margin_s=900,
                        trust=env["trust"], approved_ids=APPROVED)
    assert not d.admitted and d.reason == "gentime_after_cutoff_minus_margin"


def test_quorum_root_tamper_refused(env):
    t = list(LEAVES)
    t[0] = hashlib.sha256(b"forged").hexdigest()
    entries = [{"provider": "tsa_a", "token": env["ta"]}, {"provider": "tsa_b", "token": env["tb"]}]
    d = ea.admit_quorum(_qb(env, entries, leaves=t), event_cutoff=_cut(), trust=env["trust"],
                        approved_ids=APPROVED)
    assert d.reason == "root_mismatch"
    d = ea.admit_quorum(_qb(env, entries, leaves=t, root=ea.batch_root(t)), event_cutoff=_cut(),
                        trust=env["trust"], approved_ids=APPROVED)
    assert d.reason == "tsa_quorum_not_met"


def test_quorum_unapproved_anchor_id(env):
    d = ea.admit_quorum(_qb(env, [], anchor_id="anchor:other"), event_cutoff=_cut(),
                        trust=env["trust"], approved_ids=APPROVED)
    assert d.reason == "anchor_id_not_approved"


# ------------------------------------------------------------- request / genTime / cert
def test_request_binding_checks_nonce(env):
    req = ea.tsa_request(env["root"])
    tok = _stamp_req(env["a"], req)
    ok = ea.tsa_verify(tok, env["root"], env["a"]["ca"], request_der=req)
    assert ok.ok, ok
    other = ea.tsa_request(env["root"])  # same imprint, different nonce
    r = ea.tsa_verify(tok, env["root"], env["a"]["ca"], request_der=other)
    assert not r.ok and r.reason == "request_mismatch"
    r = ea.tsa_verify(tok, env["root"], env["a"]["ca"], request_der=ea.tsa_request("1" * 64))
    assert not r.ok


def test_gentime_in_future_refused(env):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    r = ea.tsa_verify(env["ta"], env["root"], env["a"]["ca"], now=past)
    assert not r.ok and r.reason == "gentime_in_future"


def test_message_imprint_mismatch_refused(env):
    assert not ea.tsa_verify(env["ta"], ea.batch_root(LEAVES[:3]), env["a"]["ca"]).ok


def test_signer_cert_not_yet_valid_refused(env):
    d = env["base"] / "late"
    d.mkdir()
    ca = _make_ca(d / "c", "LATE")
    cd = ca["dir"]
    nb = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y%m%d%H%M%SZ")
    na = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y%m%d%H%M%SZ")
    # openssl x509 -req does NOT support -not_before on GitHub's OpenSSL 3.x.
    # Use openssl ca -startdate / -enddate to mint a truly future-valid TSA.
    (cd / "index.txt").write_text("")
    (cd / "serial-ca").write_text("1000\n")
    (cd / "newcerts").mkdir()
    cfg = cd / "future-ca.cnf"
    cfg.write_text((cd / "tsa.cnf").read_text() + f"""
[ ca ]
default_ca = CA_default
[ CA_default ]
database = {cd}/index.txt
new_certs_dir = {cd}/newcerts
certificate = {cd}/ca.pem
private_key = {cd}/ca.key
serial = {cd}/serial-ca
default_md = sha256
policy = policy_anything
unique_subject = no
[ policy_anything ]
commonName = optional
""")
    _ossl("ca", "-batch", "-notext", "-config", str(cfg), "-extensions", "v3_tsa",
          "-startdate", nb, "-enddate", na, "-in", "tsa.csr", "-out", "tsa.pem", cwd=cd)
    tok = _stamp(ca, env["root"])
    assert not ea.tsa_verify(tok, env["root"], ca["ca"]).ok


# ------------------------------------------------------------- OTS full proof
def _ots_bitcoin(root_hex, height=850000, nonce=b"\x11" * 16):
    """Synthetic proof: append(nonce) -> sha256 -> bitcoin attestation(height)."""
    commit = hashlib.sha256(bytes.fromhex(root_hex) + nonce).digest()
    body = (b"\xf0" + bytes([len(nonce)]) + nonce + b"\x08" + b"\x00"
            + bytes.fromhex("0588960d73d71901") + b"\x03" + _varuint(height))
    return ea.OTS_MAGIC + b"\x01\x08" + bytes.fromhex(root_hex) + body, commit


def _varuint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _header(merkle: bytes, ts: int) -> bytes:
    return b"\x00" * 36 + merkle + ts.to_bytes(4, "little") + b"\x00" * 8


def test_ots_bitcoin_attestation_confirmed_with_supplied_header(env):
    proof, commit = _ots_bitcoin(env["root"])
    ts = 1_760_000_000
    r = ea.ots_verify(proof, env["root"], {850000: _header(commit, ts)})
    assert r.ok and r.bitcoin_attested and r.attested_heights == (850000,)
    assert r.attested_time == datetime.fromtimestamp(ts, timezone.utc)


def test_ots_without_header_is_unattested(env):
    proof, _ = _ots_bitcoin(env["root"])
    r = ea.ots_verify(proof, env["root"])
    assert r.ok and not r.bitcoin_attested


def test_ots_header_mismatch_refused(env):
    proof, _ = _ots_bitcoin(env["root"])
    r = ea.ots_verify(proof, env["root"], {850000: _header(b"\x22" * 32, 1)})
    assert not r.ok and r.reason == "merkle_root_mismatch"
    assert not ea.ots_verify(proof, env["root"], {850000: b"short"}).ok


def test_ots_fork_pending_and_bitcoin(env):
    proof, commit = _ots_bitcoin(env["root"])
    head = ea.OTS_MAGIC + b"\x01\x08" + bytes.fromhex(env["root"])
    pend = b"\x00" + bytes.fromhex("83dfe30d2ef90c8e") + b"\x0a\x09cal.test/"
    forked = head + b"\xff" + pend + proof[len(head):]
    r = ea.ots_verify(forked, env["root"], {850000: _header(commit, 5)})
    assert r.ok and r.bitcoin_attested and r.pending_calendars == ("cal.test/",)


@pytest.mark.parametrize("cut", ["trailing", "truncated", "badop", "noatt"])
def test_ots_malformed(env, cut):
    proof, _ = _ots_bitcoin(env["root"])
    head = ea.OTS_MAGIC + b"\x01\x08" + bytes.fromhex(env["root"])
    p = {"trailing": proof + b"\x00", "truncated": proof[:-2],
         "badop": head + b"\x99", "noatt": head}[cut]
    assert not ea.ots_verify(p, env["root"]).ok


def test_ots_digest_must_match_root(env):
    proof, _ = _ots_bitcoin(env["root"])
    assert ea.ots_verify(proof, "2" * 64).reason == "digest_mismatch"


# ------------------------------------------------------------- Object Lock store
def test_in_memory_lock_semantics():
    w = ls.InMemoryLockWriter()
    r = w.put_locked("mlb/2026-10-13/batch-1.tsr", b"abc")
    assert r.sha256 == hashlib.sha256(b"abc").hexdigest() and r.mode == "COMPLIANCE"
    assert (r.retain_until - datetime.now(timezone.utc)).days >= 3649
    with pytest.raises(ls.LockStoreError):
        w.put_locked("mlb/2026-10-13/batch-1.tsr", b"other")
    with pytest.raises(ls.LockStoreError):
        w.delete("mlb/2026-10-13/batch-1.tsr")
    assert w.get("mlb/2026-10-13/batch-1.tsr") == b"abc"


@pytest.mark.parametrize("kw,key,body", [
    ({"retention_days": 30}, "k", b"x"), ({"mode": "GOVERNANCE"}, "k", b"x"),
    ({}, "../etc", b"x"), ({}, "Upper", b"x"), ({}, "k", b""),
])
def test_lock_writer_rejects(kw, key, body):
    with pytest.raises(ls.LockStoreError):
        ls.InMemoryLockWriter(**kw).put_locked(key, body)


class _FakeS3:
    def __init__(self, lock="Enabled", ver="Enabled", vid="v-1"):
        self.lock, self.ver, self.vid, self.calls = lock, ver, vid, []

    def get_object_lock_configuration(self, Bucket):
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": self.lock}}

    def get_bucket_versioning(self, Bucket):
        return {"Status": self.ver}

    def put_object(self, **kw):
        self.calls.append(kw)
        return {"VersionId": self.vid} if self.vid else {}


def test_s3_writer_disabled_by_default():
    with pytest.raises(ls.LockStoreError, match="not activated"):
        ls.S3ObjectLockWriter("sportsedge-evidence-locked", _FakeS3())
    with pytest.raises(ls.LockStoreError):
        ls.S3ObjectLockWriter("sportsedge-evidence-locked", None, enabled=True)


def test_s3_writer_sends_compliance_lock_and_checksum():
    c = _FakeS3()
    w = ls.S3ObjectLockWriter("sportsedge-evidence-locked", c, enabled=True)
    w.verify_bucket()
    r = w.put_locked("nba/x.json", b"payload")
    kw = c.calls[0]
    assert kw["ObjectLockMode"] == "COMPLIANCE" and kw["IfNoneMatch"] == "*"
    assert kw["ChecksumSHA256"] == base64.b64encode(hashlib.sha256(b"payload").digest()).decode()
    assert r.version_id == "v-1"


@pytest.mark.parametrize("fake", [_FakeS3(lock="Disabled"), _FakeS3(ver="Suspended")])
def test_s3_bucket_verification_fails_closed(fake):
    with pytest.raises(ls.LockStoreError):
        ls.S3ObjectLockWriter("sportsedge-evidence-locked", fake, enabled=True).verify_bucket()


def test_s3_put_revalidates_bucket_even_if_caller_skips_preflight():
    c = _FakeS3(lock="Disabled")
    w = ls.S3ObjectLockWriter("sportsedge-evidence-locked", c, enabled=True)
    with pytest.raises(ls.LockStoreError, match="Object Lock"):
        w.put_locked("mlb/receipt.json", b"critical")
    assert c.calls == []


def test_s3_put_rejects_stale_or_naive_retention_clock():
    c = _FakeS3()
    w = ls.S3ObjectLockWriter("sportsedge-evidence-locked", c, enabled=True)
    with pytest.raises(ls.LockStoreError, match="stale"):
        w.put_locked("mlb/receipt.json", b"critical", now=datetime(2000, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ls.LockStoreError, match="timezone-aware"):
        w.put_locked("mlb/receipt.json", b"critical", now=datetime(2026, 10, 13))
    assert c.calls == []


def test_s3_missing_version_id_refused():
    w = ls.S3ObjectLockWriter("sportsedge-evidence-locked", _FakeS3(vid=None), enabled=True)
    with pytest.raises(ls.LockStoreError):
        w.put_locked("k", b"x")


def test_no_repository_code_imports_lock_store():
    hits = [p for p in (REPO / "sportsedge").rglob("*.py")
            if p.name != "evidence_lock_store.py" and "evidence_lock_store" in p.read_text(errors="ignore")]
    assert hits == []
