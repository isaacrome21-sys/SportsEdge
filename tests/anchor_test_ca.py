"""Throwaway TEST-CA helpers for anchored-admission consumer tests (t127).

Imported by consumer tests; generates self-signed test TSAs with the openssl
CLI in tmp dirs. No network, no real TSA material, no credentials.
"""
from __future__ import annotations

import functools
import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sportsedge import evidence_admission_gate as gate
from sportsedge import evidence_anchor as ea

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


def make_ca(d: Path, name: str) -> dict:
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


def stamp(ca: dict, req: bytes) -> bytes:
    d = ca["dir"]
    (d / "q.tsq").write_bytes(req)
    _ossl("ts", "-reply", "-config", str(d / "tsa.cnf"), "-queryfile", "q.tsq", "-out", "r.tsr", cwd=d)
    return (d / "r.tsr").read_bytes()


class TsaPairForTests:
    """Two independent test TSAs ("tsa_a", "tsa_b") and their trust map."""

    def __init__(self, base: Path):
        self.a, self.b = make_ca(base / "a", "A"), make_ca(base / "b", "B")
        self.trust = {"tsa_a": (self.a["ca"], [self.a["tsa_der_sha"]]),
                      "tsa_b": (self.b["ca"], [self.b["tsa_der_sha"]])}

    def bundle(self, leaves, providers=("tsa_a", "tsa_b")) -> dict:
        root = ea.batch_root(leaves)
        toks = []
        for pid in providers:
            req = ea.tsa_request(root)
            toks.append({"provider": pid, "token": stamp(self.a if pid == "tsa_a" else self.b, req),
                         "request": req})
        return {"anchor_id": ea.ANCHOR_ID, "leaves": list(leaves), "root": root, "tsa_tokens": toks}

    def activate(self, monkeypatch) -> None:
        """Simulate a FUTURE owner activation in-process only, with TEST trust."""
        monkeypatch.setattr(ea, "ADMISSION_ACTIVE", True)
        monkeypatch.setattr(gate, "_admit", functools.partial(
            _admit_with, self.trust))


def _admit_with(trust, bundle, *, event_cutoff):
    return ea.admit_quorum(bundle, event_cutoff=event_cutoff, trust=trust,
                           approved_ids=frozenset({ea.ANCHOR_ID}))


def cutoff(hours: float = 3) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
