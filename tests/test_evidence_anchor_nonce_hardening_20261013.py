"""t130: nonce hardening + reviewer refusal matrix for anchored admission.

Reviewer requirements (ChatGPT, t129):
1. production admission requires a fresh >=64-bit request nonce recorded with
   the request, echoed by the TSA, single-use (persisted ledger, fail closed);
2. cross-authority masquerade refused (signer pin, CA, policy OID, TSA name);
   two tokens from one TSA count once;
3. imprint / hash-algorithm / genTime window / future / expired-cert refusals;
4. S3 Object Lock writer and admission switch fail closed.

Only throwaway openssl TEST CAs generated in tmp dirs are used. No network,
no real TSA material, no credentials. Admission stays OFF in the committed
config; activation here is simulated in-process only.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge import evidence_anchor as ea
from sportsedge import evidence_lock_store as ls

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI required")

APPROVED = frozenset({ea.ANCHOR_ID})
POL_A, POL_B = "1.2.3.4.1", "1.2.3.4.2"

CNF = """
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
default_policy = {policy}
digests = sha256, sha512
accuracy = secs:1
ordering = no
tsa_name = yes
ess_cert_id_chain = no
ess_cert_id_alg = sha256
"""


def _o(*a, cwd):
    return subprocess.run(["openssl", *a], cwd=cwd, check=True, capture_output=True).stdout


def make_tsa(d: Path, name: str, policy: str, *, ca_from: dict | None = None,
             not_before: str | None = None, not_after: str | None = None) -> dict:
    """Throwaway TEST TSA. ``ca_from`` reuses another TSA's TEST CA (same CA, other signer)."""
    d.mkdir(parents=True)
    cnf = d / "tsa.cnf"
    cnf.write_text(CNF.format(d=d, policy=policy))
    (d / "serial").write_text("01\n")
    if ca_from is None:
        _o("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
           "-days", "2", "-subj", f"/CN=SportsEdge TEST CA {name}", "-config", str(cnf),
           "-extensions", "v3_ca", cwd=d)
    else:
        shutil.copy(ca_from["dir"] / "ca.pem", d / "ca.pem")
        shutil.copy(ca_from["dir"] / "ca.key", d / "ca.key")
    _o("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "tsa.key", "-out", "tsa.csr",
       "-subj", f"/CN=SportsEdge TEST TSA {name}", "-config", str(cnf), cwd=d)
    if not_before:
        # `openssl x509 -req` accepts -not_before/-not_after only from
        # OpenSSL 3.2; issue the deliberately-dated cert via `openssl ca`
        # (-startdate/-enddate), which OpenSSL 3.0 supports.
        (d / "index.txt").write_text("")
        (d / "ca_serial").write_text("01\n")
        (d / "ca.cnf").write_text(
            "[ ca ]\ndefault_ca = CA_default\n[ CA_default ]\n"
            f"dir = {d}\ndatabase = {d}/index.txt\nnew_certs_dir = {d}\n"
            f"serial = {d}/ca_serial\nprivate_key = {d}/ca.key\n"
            f"certificate = {d}/ca.pem\ndefault_md = sha256\n"
            "policy = policy_any\n[ policy_any ]\ncommonName = supplied\n")
        _o("ca", "-batch", "-config", str(d / "ca.cnf"), "-in", "tsa.csr",
           "-out", "tsa.pem", "-notext", "-startdate", not_before,
           "-enddate", not_after, "-extfile", str(cnf), "-extensions",
           "v3_tsa", cwd=d)
    else:
        _o("x509", "-req", "-in", "tsa.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial",
           "-out", "tsa.pem", "-days", "2", "-extfile", str(cnf), "-extensions", "v3_tsa", cwd=d)
    der = _o("x509", "-in", "tsa.pem", "-outform", "DER", cwd=d)
    return {"dir": d, "ca": (d / "ca.pem").read_bytes(), "pin": hashlib.sha256(der).hexdigest(),
            "policy": policy}


def stamp(t: dict, req: bytes) -> bytes:
    (t["dir"] / "q.tsq").write_bytes(req)
    _o("ts", "-reply", "-config", str(t["dir"] / "tsa.cnf"), "-queryfile", "q.tsq", "-out", "r.tsr",
       cwd=t["dir"])
    return (t["dir"] / "r.tsr").read_bytes()


def tst_of(token: bytes, d: Path) -> ea.TstInfo:
    (d / "x.tsr").write_bytes(token)
    _o("ts", "-reply", "-in", "x.tsr", "-token_out", "-out", "x.tok", cwd=d)
    _o("cms", "-verify", "-inform", "DER", "-in", "x.tok", "-noverify", "-out", "x.tst", cwd=d)
    return ea.parse_tst_info((d / "x.tst").read_bytes())


def trust_of(t: dict, *, name: bool = True, d: Path | None = None, tok: bytes | None = None):
    nm = tst_of(tok, d).tsa_name_sha256 if (name and tok is not None) else None
    return ea.ProviderTrust(t["ca"], (t["pin"],), (t["policy"],), nm)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = tmp_path_factory.mktemp("t130")
    a = make_tsa(base / "a", "A", POL_A)
    b = make_tsa(base / "b", "B", POL_B)
    c_same_ca = make_tsa(base / "c", "C", POL_A, ca_from=a)       # same CA as A, other signer
    expired = make_tsa(base / "e", "E", POL_A, not_before="20200101000000Z",
                       not_after="20200102000000Z")
    leaves = [hashlib.sha256(f"t130 synthetic leaf {i}".encode()).hexdigest() for i in range(3)]
    root = ea.batch_root(leaves)
    probe_a = stamp(a, ea.build_tsa_request(root, ea.new_nonce()))
    probe_b = stamp(b, ea.build_tsa_request(root, ea.new_nonce()))
    trust = {"tsa_a": trust_of(a, d=base, tok=probe_a), "tsa_b": trust_of(b, d=base, tok=probe_b)}
    return {"base": base, "a": a, "b": b, "c": c_same_ca, "e": expired, "leaves": leaves,
            "root": root, "trust": trust}


def _cut(h=3):
    return datetime.now(timezone.utc) + timedelta(hours=h)


def _ledger(tmp_path) -> ea.NonceLedger:
    return ea.NonceLedger(tmp_path / "state" / "nonce_ledger.jsonl")


def _entry(env, ledger, pid, tsa=None, **issue_kw):
    req, n = ea.new_tsa_request(env["root"], pid, ledger) if not issue_kw else (None, None)
    if issue_kw:
        n = ea.new_nonce()
        req = ea.build_tsa_request(env["root"], n)
        ledger.issue(pid, n, req, **issue_kw)
    t = tsa or (env["a"] if pid == "tsa_a" else env["b"])
    return {"provider": pid, "token": stamp(t, req), "request": req}


def _bundle(env, entries):
    return {"anchor_id": ea.ANCHOR_ID, "leaves": env["leaves"], "root": env["root"], "tsa_tokens": entries}


def _admit(env, entries, ledger, **kw):
    kw.setdefault("trust", env["trust"])
    return ea.admit_quorum(_bundle(env, entries), event_cutoff=kw.pop("cutoff", _cut()),
                           approved_ids=APPROVED, require_nonce=True, nonce_ledger=ledger, **kw)


# ======================================================== 1. nonces
def test_new_nonce_is_random_and_at_least_64_bits():
    ns = {ea.new_nonce() for _ in range(64)}
    assert len(ns) == 64
    assert all(n.bit_length() == ea.NONCE_BITS >= 64 for n in ns)


def test_request_der_roundtrip_and_short_nonce_refused(env):
    n = ea.new_nonce()
    info = ea.parse_tsa_request(ea.build_tsa_request(env["root"], n))
    assert (info.nonce, info.digest_hex, info.imprint_alg) == (n, env["root"], ea.OID_SHA256)
    for bad in (0, 1 << 32, (1 << 63) - 1, True, "x"):
        with pytest.raises(ea.AnchorError):
            ea.build_tsa_request(env["root"], bad)
    # openssl itself parses our DER
    p = subprocess.run(["openssl", "ts", "-query", "-in", "/dev/stdin", "-text"],
                       input=ea.build_tsa_request(env["root"], n), capture_output=True)
    assert p.returncode == 0 and f"0x{n:X}".encode() in p.stdout


def test_nonce_recorded_with_request_in_ledger(env, tmp_path):
    led = _ledger(tmp_path)
    req, n = ea.new_tsa_request(env["root"], "tsa_a", led)
    rec = led.lookup("tsa_a", n)
    assert rec["request_sha256"] == hashlib.sha256(req).hexdigest() and rec["consumed"] is False
    line = json.loads((tmp_path / "state" / "nonce_ledger.jsonl").read_text().splitlines()[0])
    assert line["op"] == "issue" and line["nonce"] == format(n, "x")
    with pytest.raises(ea.NonceLedgerError):
        led.issue("tsa_a", n, req)          # a nonce is never issued twice


def test_production_admits_fresh_nonce_quorum_then_refuses_replay(env, tmp_path):
    led = _ledger(tmp_path)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    d = _admit(env, entries, led)
    assert d.admitted, d
    again = _admit(env, entries, led)
    assert not again.admitted and again.reason == "tsa_quorum_not_met"
    assert "tsa_a:nonce_replayed" in again.details and "tsa_b:nonce_replayed" in again.details


def test_replay_of_one_response_with_fresh_partner_refused(env, tmp_path):
    led = _ledger(tmp_path)
    old_a = _entry(env, led, "tsa_a")
    assert _admit(env, [old_a, _entry(env, led, "tsa_b")], led).admitted
    d = _admit(env, [old_a, _entry(env, led, "tsa_b")], led)
    assert not d.admitted and "tsa_a:nonce_replayed" in d.details


def test_same_nonce_twice_in_one_bundle_consumed_once(env, tmp_path):
    led = _ledger(tmp_path)
    a = _entry(env, led, "tsa_a")
    d = _admit(env, [a, dict(a), _entry(env, led, "tsa_b")], led)
    assert not d.admitted and d.reason == "nonce_reused_in_bundle"


def test_nonce_less_request_refused_in_production(env, tmp_path):
    """The one-off fixture path (tsa_request(nonce=False)) can never admit."""
    led = _ledger(tmp_path)
    req = ea.tsa_request(env["root"], nonce=False)
    a = {"provider": "tsa_a", "token": stamp(env["a"], req), "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert not d.admitted and "tsa_a:request_nonce_missing" in d.details
    # and the token itself is refused when a nonce is required
    r = ea.tsa_verify(a["token"], env["root"], env["a"]["ca"], None, [env["a"]["pin"]], require_nonce=True)
    assert r.reason == "nonce_missing"


def test_missing_request_refused_in_production(env, tmp_path):
    led = _ledger(tmp_path)
    a = _entry(env, led, "tsa_a")
    del a["request"]
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert not d.admitted and "tsa_a:request_binding_required" in d.details


def test_openssl_default_short_nonce_refused(env, tmp_path):
    led = _ledger(tmp_path)
    n = (1 << 40) + 12345
    imprint = ea._tlv(0x30, ea._SHA256_ALGID + ea._tlv(0x04, bytes.fromhex(env["root"])))
    req = ea._tlv(0x30, ea._der_int(1) + imprint + ea._der_int(n) + b"\x01\x01\xff")
    led.issue("tsa_a", n, req)
    a = {"provider": "tsa_a", "token": stamp(env["a"], req), "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert "tsa_a:nonce_too_short" in d.details and not d.admitted


def test_unissued_nonce_refused(env, tmp_path):
    led = _ledger(tmp_path)
    req = ea.build_tsa_request(env["root"], ea.new_nonce())        # never recorded
    a = {"provider": "tsa_a", "token": stamp(env["a"], req), "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert "tsa_a:nonce_not_issued" in d.details and not d.admitted


def test_nonce_issued_for_other_provider_refused(env, tmp_path):
    led = _ledger(tmp_path)
    req, _ = ea.new_tsa_request(env["root"], "tsa_b", led)          # recorded for B
    a = {"provider": "tsa_a", "token": stamp(env["a"], req), "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert "tsa_a:nonce_not_issued" in d.details and not d.admitted


def test_request_not_matching_recorded_digest_refused(env, tmp_path):
    led = _ledger(tmp_path)
    n = ea.new_nonce()
    led.issue("tsa_a", n, b"some other request bytes")
    req = ea.build_tsa_request(env["root"], n)
    a = {"provider": "tsa_a", "token": stamp(env["a"], req), "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert "tsa_a:request_not_recorded" in d.details and not d.admitted


def test_response_not_echoing_recorded_nonce_refused(env, tmp_path):
    led = _ledger(tmp_path)
    req1, n1 = ea.new_tsa_request(env["root"], "tsa_a", led)
    req2, n2 = ea.new_tsa_request(env["root"], "tsa_a", led)
    a = {"provider": "tsa_a", "token": stamp(env["a"], req1), "request": req2}   # reply to other nonce
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert "tsa_a:nonce_mismatch" in d.details and not d.admitted
    tok = stamp(env["a"], req1)
    assert ea.tsa_verify(tok, env["root"], env["a"]["ca"], None, [env["a"]["pin"]],
                         expected_nonce=n2).reason == "nonce_mismatch"
    assert ea.tsa_verify(tok, env["root"], env["a"]["ca"], None, [env["a"]["pin"]],
                         request_der=req2).reason == "request_mismatch"


def test_no_ledger_refused_in_production(env, tmp_path):
    led = _ledger(tmp_path)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    d = ea.admit_quorum(_bundle(env, entries), event_cutoff=_cut(), trust=env["trust"],
                        approved_ids=APPROVED, require_nonce=True, nonce_ledger=None)
    assert d.reason == "nonce_ledger_unconfigured"


@pytest.mark.parametrize("damage", ["corrupt_line", "torn_tail", "consume_without_issue", "not_utf8"])
def test_ledger_corruption_fails_closed(env, tmp_path, damage):
    led = _ledger(tmp_path)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    p = tmp_path / "state" / "nonce_ledger.jsonl"
    extra = {"corrupt_line": b"{not json\n", "torn_tail": b'{"op": "issue"',
             "consume_without_issue": b'{"op": "consume", "provider": "x", "nonce": "1"}\n',
             "not_utf8": b"\xff\xfe\n"}[damage]
    p.write_bytes(p.read_bytes() + extra)
    d = _admit(env, entries, led)
    assert not d.admitted and d.reason == "nonce_ledger_error"


def test_ledger_unwritable_or_unopenable_fails_closed(env, tmp_path, monkeypatch):
    led = _ledger(tmp_path)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    real = ea.NonceLedger._append

    def boom(self, fd, recs):
        raise ea.NonceLedgerError("disk full")
    monkeypatch.setattr(ea.NonceLedger, "_append", boom)
    d = _admit(env, entries, led)
    assert not d.admitted and d.reason == "nonce_ledger_error"
    monkeypatch.setattr(ea.NonceLedger, "_append", real)
    dir_led = ea.NonceLedger(tmp_path)          # a directory, cannot be opened as a ledger
    d2 = _admit(env, entries, dir_led)
    assert not d2.admitted and d2.reason == "nonce_ledger_error"
    with pytest.raises(ea.NonceLedgerError):
        ea.NonceLedger("")


def _prod_repo(env, tmp_path, *, admission=True, ledger=True, extra=None):
    repo = tmp_path / "repo"
    (repo / "config" / "anchors").mkdir(parents=True)
    provs = []
    for pid, t in (("tsa_a", env["a"]), ("tsa_b", env["b"])):
        (repo / "config" / "anchors" / f"{pid}.pem").write_bytes(t["ca"])
        provs.append({"id": pid, "url": ea.TSA_URLS[0], "ca_bundle_path": f"config/anchors/{pid}.pem",
                      "signer_cert_sha256": [t["pin"]], "policy_oids": [t["policy"]],
                      "tsa_name_sha256": env["trust"][pid].tsa_name_sha256, "status": "pinned"})
    raw = {"schema": "sportsedge.anchor_config.v1",
           "owner_decision": {"anchor_ids": [ea.ANCHOR_ID], "approved_by": "TEST", "approved_at": "TEST"},
           "approved_anchor_ids": [ea.ANCHOR_ID],
           "activation": {"capture_active": False, "admission_active": admission},
           "tsa_providers": provs, "quorum": {"min_distinct_providers": 2},
           "pregame_margin_s": 900, "max_clock_skew_s": 30, "max_response_window_s": 300}
    if ledger:
        raw["nonce_ledger"] = {"path": "state/ledger.jsonl"}
    raw.update(extra or {})
    cp = repo / "config" / "anchors" / "anchor_config_v1.json"
    cp.write_text(json.dumps(raw))
    return cp, ea.NonceLedger(repo / "state" / "ledger.jsonl")


def test_configured_production_path_end_to_end_then_replay(env, tmp_path, monkeypatch):
    cp, led = _prod_repo(env, tmp_path)
    monkeypatch.setattr(ea, "ADMISSION_ACTIVE", True)        # simulated, in-process only
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    d = ea.admit_configured_quorum(_bundle(env, entries), event_cutoff=_cut(), config_path=cp)
    assert d.admitted, d
    d2 = ea.admit_configured_quorum(_bundle(env, entries), event_cutoff=_cut(), config_path=cp)
    assert not d2.admitted and "tsa_a:nonce_replayed" in d2.details


def test_configured_path_refuses_without_ledger_config(env, tmp_path, monkeypatch):
    cp, led = _prod_repo(env, tmp_path, ledger=False)
    monkeypatch.setattr(ea, "ADMISSION_ACTIVE", True)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    assert ea.admit_configured_quorum(_bundle(env, entries), event_cutoff=_cut(),
                                      config_path=cp).reason == "nonce_ledger_unconfigured"


def test_committed_config_production_path_refuses(env, tmp_path, monkeypatch):
    """Committed config: admission off; even simulated-on, DigiCert unpinned -> refuse."""
    led = _ledger(tmp_path)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    assert ea.admit_configured_quorum(_bundle(env, entries), event_cutoff=_cut()).reason == "admission_not_activated"
    monkeypatch.setattr(ea, "ADMISSION_ACTIVE", True)
    assert ea.admit_configured_quorum(_bundle(env, entries), event_cutoff=_cut()).reason == "admission_not_activated"


# ======================================================== 2. cross-authority masquerade
def test_token_from_a_cannot_satisfy_b(env, tmp_path):
    led = _ledger(tmp_path)
    a = _entry(env, led, "tsa_a")
    fake_b = _entry(env, led, "tsa_b", tsa=env["a"])            # A's token labelled as B
    d = _admit(env, [a, fake_b], led)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"
    assert "tsa_b:tsa_policy_mismatch" in d.details


def test_signer_pin_and_ca_per_provider(env):
    root = env["root"]
    tok_a = stamp(env["a"], ea.build_tsa_request(root, ea.new_nonce()))
    # B's CA cannot verify A's token
    assert ea.tsa_verify(tok_a, root, env["b"]["ca"], None, [env["b"]["pin"]]).reason == "tsa_verify_failed"
    # same CA, different signer (C under A's CA, same policy) -> signer pin refuses
    tok_c = stamp(env["c"], ea.build_tsa_request(root, ea.new_nonce()))
    r = ea.tsa_verify(tok_c, root, env["a"]["ca"], None, [env["a"]["pin"]], expected_policy_oids=[POL_A])
    assert r.reason == "tsa_cert_not_pinned"


def test_policy_oid_pin(env):
    tok_a = stamp(env["a"], ea.build_tsa_request(env["root"], ea.new_nonce()))
    kw = dict(token=tok_a, root_hex=env["root"], ca_bundle_pem=env["a"]["ca"],
              pinned_tsa_cert_sha256=[env["a"]["pin"]])
    assert ea.tsa_verify(**kw, expected_policy_oids=[POL_B]).reason == "tsa_policy_mismatch"
    assert ea.tsa_verify(**kw, expected_policy_oids=[]).reason == "tsa_policy_not_pinned"
    r = ea.tsa_verify(**kw, expected_policy_oids=[POL_A])
    assert r.ok and r.policy_oid == POL_A


def test_tsa_name_pin(env):
    tok_c = stamp(env["c"], ea.build_tsa_request(env["root"], ea.new_nonce()))
    r = ea.tsa_verify(tok_c, env["root"], env["a"]["ca"], None, None,
                      expected_tsa_name_sha256=env["trust"]["tsa_a"].tsa_name_sha256)
    assert r.reason == "tsa_name_mismatch"


def test_two_tokens_same_tsa_count_once(env, tmp_path):
    led = _ledger(tmp_path)
    d = _admit(env, [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_a")], led)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"


def test_one_signer_under_two_provider_ids_counts_once(env, tmp_path):
    led = _ledger(tmp_path)
    trust = {"tsa_a": env["trust"]["tsa_a"], "tsa_a_alias": env["trust"]["tsa_a"]}
    e1 = _entry(env, led, "tsa_a")
    e2 = _entry(env, led, "tsa_a_alias", tsa=env["a"])
    d = _admit(env, [e1, e2], led, trust=trust)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"


def test_unknown_provider_refused(env, tmp_path):
    led = _ledger(tmp_path)
    d = _admit(env, [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_z", tsa=env["b"])], led)
    assert not d.admitted and "tsa_z:unknown_provider" in d.details


def test_config_refuses_shared_signer_pin_and_unpinned_policy(env, tmp_path):
    cp, _ = _prod_repo(env, tmp_path)
    raw = json.loads(cp.read_text())
    raw["tsa_providers"][1]["signer_cert_sha256"] = raw["tsa_providers"][0]["signer_cert_sha256"]
    cp.write_text(json.dumps(raw))
    with pytest.raises(ea.AnchorError, match="shared"):
        ea.load_config(cp)
    p = ea.TsaProvider("x", ea.TSA_URLS[0], "c.pem", (env["a"]["pin"],), "pinned", ())
    assert not p.pinned                      # no policy OID pin -> not pinned
    raw["tsa_providers"][1]["signer_cert_sha256"] = [env["b"]["pin"]]
    raw["tsa_providers"][1]["policy_oids"] = ["not-an-oid"]
    cp.write_text(json.dumps(raw))
    with pytest.raises(ea.AnchorError, match="policy"):
        ea.load_config(cp)


def test_committed_freetsa_pins_policy_and_name_from_real_fixture():
    prov = {p.id: p for p in ea.load_config().providers}
    assert prov["freetsa"].policy_oids == ("1.2.3.4.1",) and prov["freetsa"].pinned
    assert prov["freetsa"].tsa_name_sha256 == "80a15f31cd8cc1a0d55822bdfbc11bb5ef33a5fffa7249c67f727932ec9c9199"
    assert not prov["digicert"].pinned and prov["digicert"].policy_oids == ()


# ======================================================== 3. imprint / alg / time / certs
def test_imprint_mismatch_refused(env):
    tok = stamp(env["a"], ea.build_tsa_request(env["root"], ea.new_nonce()))
    other = hashlib.sha256(b"other").hexdigest()
    assert ea.tsa_verify(tok, other, env["a"]["ca"]).reason == "imprint_mismatch"


def test_hash_algorithm_mismatch_refused(env, tmp_path):
    p = subprocess.run(["openssl", "ts", "-query", "-digest", hashlib.sha512(b"x").hexdigest(),
                        "-sha512", "-cert"], capture_output=True, check=True)
    tok = stamp(env["a"], p.stdout)
    assert ea.tsa_verify(tok, env["root"], env["a"]["ca"]).reason == "imprint_not_sha256"
    # production request with a non-SHA-256 imprint is refused before any token check
    led = _ledger(tmp_path)
    n = ea.new_nonce()
    alg512 = ea._tlv(0x30, ea._tlv(0x06, bytes.fromhex("608648016503040203")) + b"\x05\x00")
    imprint = ea._tlv(0x30, alg512 + ea._tlv(0x04, bytes.fromhex(env["root"]) * 2))
    req = ea._tlv(0x30, ea._der_int(1) + imprint + ea._der_int(n) + b"\x01\x01\xff")
    led.issue("tsa_a", n, req)
    a = {"provider": "tsa_a", "token": stamp(env["a"], req), "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert "tsa_a:request_hash_alg_mismatch" in d.details and not d.admitted


def test_request_imprint_not_root_refused(env, tmp_path):
    led = _ledger(tmp_path)
    other = hashlib.sha256(b"other root").hexdigest()
    req, _ = ea.new_tsa_request(other, "tsa_a", led)
    a = {"provider": "tsa_a", "token": stamp(env["a"], req), "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert "tsa_a:request_imprint_mismatch" in d.details and not d.admitted


def test_future_gentime_refused(env):
    tok = stamp(env["a"], ea.build_tsa_request(env["root"], ea.new_nonce()))
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert ea.tsa_verify(tok, env["root"], env["a"]["ca"], now=past).reason == "gentime_in_future"


@pytest.mark.parametrize("offset", [timedelta(hours=-2), timedelta(hours=1), timedelta(seconds=-301)])
def test_gentime_outside_request_window_refused(env, tmp_path, offset):
    led = _ledger(tmp_path)
    a = _entry(env, led, "tsa_a", issued_at=datetime.now(timezone.utc) + offset)
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert not d.admitted and "tsa_a:gentime_outside_request_window" in d.details


def test_gentime_after_cutoff_refused(env, tmp_path):
    led = _ledger(tmp_path)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    d = _admit(env, entries, led, cutoff=datetime.now(timezone.utc) + timedelta(seconds=60))
    assert not d.admitted and d.reason == "gentime_after_cutoff_minus_margin"
    # refusal before consumption: nonces were not burnt by the refused attempt
    assert led.lookup("tsa_a", ea.parse_tsa_request(entries[0]["request"]).nonce)["consumed"] is False


def test_cert_expired_at_gentime_refused(env, tmp_path):
    led = _ledger(tmp_path)
    tok = stamp(env["e"], ea.build_tsa_request(env["root"], ea.new_nonce()))
    assert ea.tsa_verify(tok, env["root"], env["e"]["ca"], None,
                         [env["e"]["pin"]]).reason == "cert_not_valid_at_gentime"
    trust = {"tsa_e": ea.ProviderTrust(env["e"]["ca"], (env["e"]["pin"],), (POL_A,)),
             "tsa_b": env["trust"]["tsa_b"]}
    d = _admit(env, [_entry(env, led, "tsa_e", tsa=env["e"]), _entry(env, led, "tsa_b")], led, trust=trust)
    assert not d.admitted and "tsa_e:cert_not_valid_at_gentime" in d.details


def test_tstinfo_parser_rejects_garbage():
    for bad in (b"", b"\x30", b"\x30\x05\x02\x01\x01", b"\x04\x00", b"\x30\x84\xff\xff\xff\xff"):
        with pytest.raises(ea.AnchorError):
            ea.parse_tst_info(bad)
    with pytest.raises(ea.AnchorError):
        ea.parse_tsa_request(b"\x30\x00trailing")


# ======================================================== 4. Object Lock + admission switch
GOOD_LOCK = {"bucket": "s3://sportsedge-evidence-locked", "mode": "COMPLIANCE", "retention_days": 3650}


def test_committed_object_lock_config_validates():
    raw = json.loads(ea.CONFIG_PATH.read_text())
    st = ls.object_lock_settings(raw["object_lock"])
    assert st == ls.ObjectLockSettings("sportsedge-evidence-locked", "COMPLIANCE", 3650)


@pytest.mark.parametrize("block", [
    None, {}, "COMPLIANCE", {**GOOD_LOCK, "bucket": None}, {**GOOD_LOCK, "bucket": "s3://Bad_Bucket"},
    {k: v for k, v in GOOD_LOCK.items() if k != "mode"}, {**GOOD_LOCK, "mode": "GOVERNANCE"},
    {**GOOD_LOCK, "mode": "compliance"}, {**GOOD_LOCK, "retention_days": 3649},
    {**GOOD_LOCK, "retention_days": "3650"}, {**GOOD_LOCK, "retention_days": True},
    {**GOOD_LOCK, "retention_days": 3650.0}, {k: v for k, v in GOOD_LOCK.items() if k != "retention_days"},
])
def test_object_lock_config_fails_closed(block):
    with pytest.raises(ls.LockStoreError):
        ls.object_lock_settings(block)


class _S3:
    def __init__(self, lock="Enabled", ver="Enabled", rule=("COMPLIANCE", 3650), raise_on=None):
        self.lock, self.ver, self.rule, self.raise_on = lock, ver, rule, raise_on
        self.objs: dict = {}

    def get_object_lock_configuration(self, Bucket):
        if self.raise_on == "lock":
            raise RuntimeError("AccessDenied")
        cfg = {"ObjectLockEnabled": self.lock}
        if self.rule:
            cfg["Rule"] = {"DefaultRetention": {"Mode": self.rule[0], "Days": self.rule[1]}}
        return {"ObjectLockConfiguration": cfg}

    def get_bucket_versioning(self, Bucket):
        return {"Status": self.ver} if self.ver else {}

    def put_object(self, **kw):
        if kw.get("IfNoneMatch") == "*" and kw["Key"] in self.objs:
            raise RuntimeError("PreconditionFailed")
        self.objs[kw["Key"]] = kw["Body"]
        return {"VersionId": f"v{len(self.objs)}"}


def test_writer_from_config_writes_once_then_refuses_overwrite():
    c = _S3()
    w = ls.S3ObjectLockWriter.from_config(GOOD_LOCK, c, enabled=True)
    assert w.put_locked("batch/1.json", b"x").mode == "COMPLIANCE"
    with pytest.raises(ls.LockStoreError, match="overwrite"):
        w.put_locked("batch/1.json", b"y")
    assert c.objs["batch/1.json"] == b"x"
    mem = ls.InMemoryLockWriter()
    mem.put_locked("k", b"x")
    with pytest.raises(ls.LockStoreError):
        mem.put_locked("k", b"y")


@pytest.mark.parametrize("client,match", [
    (_S3(lock="Disabled"), "Object Lock"), (_S3(ver="Suspended"), "versioning"), (_S3(ver=None), "versioning"),
    (_S3(rule=None), "COMPLIANCE"), (_S3(rule=("GOVERNANCE", 3650)), "COMPLIANCE"),
    (_S3(rule=("COMPLIANCE", 30)), "minimum"), (_S3(raise_on="lock"), "preflight"),
])
def test_writer_bucket_preflight_fails_closed(client, match):
    w = ls.S3ObjectLockWriter.from_config(GOOD_LOCK, client, enabled=True)
    with pytest.raises(ls.LockStoreError, match=match):
        w.put_locked("batch/1.json", b"x")
    assert getattr(client, "objs", {}) == {}


@pytest.mark.parametrize("kw", [{"mode": "GOVERNANCE"}, {"retention_days": 3649}, {"retention_days": True}])
def test_writer_constructor_fails_closed(kw):
    with pytest.raises(ls.LockStoreError):
        ls.S3ObjectLockWriter("sportsedge-evidence-locked", _S3(), enabled=True, **kw)
    with pytest.raises(ls.LockStoreError):
        ls.InMemoryLockWriter(**kw)


def test_writer_disabled_or_clientless_refused():
    with pytest.raises(ls.LockStoreError, match="not activated"):
        ls.S3ObjectLockWriter.from_config(GOOD_LOCK, _S3())
    with pytest.raises(ls.LockStoreError):
        ls.S3ObjectLockWriter.from_config(GOOD_LOCK, None, enabled=True)


def _cfg_with(tmp_path, mutate):
    raw = json.loads(ea.CONFIG_PATH.read_text())
    mutate(raw)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw) if not isinstance(raw, str) else raw)
    return p


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("activation"),
    lambda r: r["activation"].pop("admission_active"),
    lambda r: r["activation"].update(admission_active="true"),
    lambda r: r["activation"].update(admission_active=1),
    lambda r: r["activation"].update(admission_active=None),
    lambda r: r.update(activation=["admission_active"]),
    lambda r: r.update(schema="other"),
])
def test_admission_flag_absent_or_garbled_refuses(tmp_path, mutate):
    p = _cfg_with(tmp_path, mutate)
    with pytest.raises(ea.AnchorError):
        ea.load_config(p)
    assert ea.activation_flags(p) == (frozenset(), False, False)


def test_admission_flag_unreadable_file_refuses(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{garbled")
    assert ea.activation_flags(bad) == (frozenset(), False, False)
    assert ea.activation_flags(tmp_path / "missing.json") == (frozenset(), False, False)


def test_garbled_config_refuses_even_if_module_flag_forced(env, tmp_path, monkeypatch):
    cp, led = _prod_repo(env, tmp_path, admission="yes")
    monkeypatch.setattr(ea, "ADMISSION_ACTIVE", True)
    entries = [_entry(env, led, "tsa_a"), _entry(env, led, "tsa_b")]
    d = ea.admit_configured_quorum(_bundle(env, entries), event_cutoff=_cut(), config_path=cp)
    assert not d.admitted and d.reason == "configured_trust_unavailable"
    cp2, led2 = _prod_repo(env, tmp_path / "off", admission=False)
    d2 = ea.admit_configured_quorum(_bundle(env, entries), event_cutoff=_cut(), config_path=cp2)
    assert not d2.admitted and d2.reason == "admission_not_activated"


def test_committed_flags_stay_off():
    cfg = ea.load_config()
    assert cfg.capture_active is False and cfg.admission_active is False
    assert ea.ADMISSION_ACTIVE is False and ea.CAPTURE_ACTIVE is False
    assert ea.activation_flags()[1:] == (False, False)


def test_request_policy_must_match_response_policy(env, tmp_path):
    """#2219: response must match the request's messageImprint + nonce + reqPolicy."""
    led = _ledger(tmp_path)
    n = ea.new_nonce()
    imprint = ea._tlv(0x30, ea._SHA256_ALGID + ea._tlv(0x04, bytes.fromhex(env["root"])))
    pol = ea._tlv(0x06, bytes.fromhex("2a030463"))          # 1.2.3.4.99, not A's policy
    req = ea._tlv(0x30, ea._der_int(1) + imprint + pol + ea._der_int(n) + b"\x01\x01\xff")
    assert ea.parse_tsa_request(req).policy_oid == "1.2.3.4.99"
    led.issue("tsa_a", n, req)
    try:
        tok = stamp(env["a"], req)      # test TSA may refuse an unknown policy outright
    except subprocess.CalledProcessError:
        return
    a = {"provider": "tsa_a", "token": tok, "request": req}
    d = _admit(env, [a, _entry(env, led, "tsa_b")], led)
    assert not d.admitted


def test_alias_quorum_would_have_passed_on_provider_ids_alone(env, tmp_path):
    """#2219 regression: on 73c9dcde quorum counted provider ids, so one signer under two ids passed."""
    led = _ledger(tmp_path)
    trust = {"x": env["trust"]["tsa_b"], "y": env["trust"]["tsa_b"]}
    d = _admit(env, [_entry(env, led, "x", tsa=env["b"]), _entry(env, led, "y", tsa=env["b"])], led, trust=trust)
    assert not d.admitted and d.reason == "tsa_quorum_not_met"
