"""External evidence anchor: batch Merkle roots, RFC 3161 TSA tokens, OpenTimestamps.

Implements module step 1 of the anchor/host proposal (2026-10-13) OFFLINE ONLY.

Status: DESIGN APPROVED (owner, 2026-10-13 20:23 CT), NOT ACTIVATED.
* ``APPROVED_ANCHOR_IDS`` is loaded ONLY from ``config/anchors/anchor_config_v1.json``,
  whose ``owner_decision`` block records the approval of
  ``anchor:rfc3161+ots:v1``. Approval of the design is not activation:
  ``CAPTURE_ACTIVE`` and ``ADMISSION_ACTIVE`` are read from the same file and
  are False; default-path :func:`admit` refuses with ``admission_not_activated``.
* TSA providers (FreeTSA, DigiCert) are configurable. A provider whose CA bundle
  / signer-cert pins are not yet populated is refused (fail closed).
* No caller in the repository imports this module. No scheduled job exists.
* Network is reachable only through ``tsa_stamp``/``ots_stamp`` and only when the
  caller passes ``allow_network=True``; tests never do.

Evidence time is the TSA ``genTime`` -- never a caller-supplied or host clock.
OpenTimestamps is a secondary, long-run proof; admission never depends on it.

Verification shells out to the ``openssl`` CLI (``openssl ts -verify``) so that
no new Python dependency is introduced.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping, Sequence

import json
from pathlib import Path

ANCHOR_ID = "anchor:rfc3161+ots:v1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "anchors" / "anchor_config_v1.json"

TSA_URLS: tuple[str, ...] = ("https://freetsa.org/tsr", "http://timestamp.digicert.com")
DEFAULT_PREGAME_MARGIN_S = 900
DEFAULT_MIN_TOKENS = 1
MAX_LEAVES = 1_000_000
MAX_TOKEN_BYTES = 64 * 1024

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AnchorError(ValueError):
    """Raised for malformed anchor input; admission converts it to a refusal."""


# ---------------------------------------------------------------- config
@dataclass(frozen=True)
class TsaProvider:
    """One RFC 3161 TSA. ``ca_bundle_path`` is relative to the repo root."""
    id: str
    url: str
    ca_bundle_path: str | None
    signer_cert_sha256: tuple[str, ...]
    status: str

    @property
    def pinned(self) -> bool:
        return bool(self.ca_bundle_path) and bool(self.signer_cert_sha256) and self.status == "pinned"


@dataclass(frozen=True)
class AnchorConfig:
    approved_anchor_ids: frozenset[str]
    capture_active: bool
    admission_active: bool
    providers: tuple[TsaProvider, ...]
    min_distinct_providers: int
    pregame_margin_s: int
    max_clock_skew_s: int
    ots_enabled: bool
    owner_decision: Mapping


def load_config(path: Path | str = CONFIG_PATH) -> AnchorConfig:
    """Strictly parse the anchor config. Any malformed field raises AnchorError."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AnchorError(f"anchor config unreadable: {e}") from e
    if not isinstance(raw, dict) or raw.get("schema") != "sportsedge.anchor_config.v1":
        raise AnchorError("bad anchor config schema")
    dec = raw.get("owner_decision")
    ids = raw.get("approved_anchor_ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise AnchorError("approved_anchor_ids must be a list of strings")
    if ids and not (isinstance(dec, dict) and dec.get("approved_by") and dec.get("approved_at")
                    and set(ids) <= set(dec.get("anchor_ids", []))):
        raise AnchorError("approved ids not backed by owner_decision")
    act = raw.get("activation")
    if not isinstance(act, dict):
        raise AnchorError("activation block missing")
    flags = {}
    for k in ("capture_active", "admission_active"):
        if not isinstance(act.get(k), bool):
            raise AnchorError(f"activation.{k} must be bool")
        flags[k] = act[k]
    provs = []
    for pv in raw.get("tsa_providers", []):
        if not isinstance(pv, dict) or not isinstance(pv.get("id"), str) or not isinstance(pv.get("url"), str):
            raise AnchorError("bad tsa provider")
        pins = pv.get("signer_cert_sha256", [])
        if not isinstance(pins, list) or not all(isinstance(x, str) and _HEX64.match(x) for x in pins):
            raise AnchorError("bad signer_cert_sha256 pins")
        provs.append(TsaProvider(pv["id"], pv["url"], pv.get("ca_bundle_path"), tuple(pins),
                                 str(pv.get("status", "unpinned"))))
    if len({p.id for p in provs}) != len(provs):
        raise AnchorError("duplicate provider id")
    q = raw.get("quorum", {})
    def _int(v, name, lo):
        if isinstance(v, bool) or not isinstance(v, int) or v < lo:
            raise AnchorError(f"{name} must be int >= {lo}")
        return v
    return AnchorConfig(
        frozenset(ids), flags["capture_active"], flags["admission_active"], tuple(provs),
        _int(q.get("min_distinct_providers"), "min_distinct_providers", 1),
        _int(raw.get("pregame_margin_s"), "pregame_margin_s", 0),
        _int(raw.get("max_clock_skew_s"), "max_clock_skew_s", 0),
        bool(raw.get("ots", {}).get("enabled", False)), dec or {})


def _safe_load() -> AnchorConfig | None:
    try:
        return load_config()
    except AnchorError:
        return None


_CFG = _safe_load()
# Fail closed if the config is missing or malformed: nothing approved, nothing active.
APPROVED_ANCHOR_IDS: frozenset[str] = _CFG.approved_anchor_ids if _CFG else frozenset()
CAPTURE_ACTIVE: bool = bool(_CFG and _CFG.capture_active)
ADMISSION_ACTIVE: bool = bool(_CFG and _CFG.admission_active)


# ---------------------------------------------------------------- Merkle root
def _h(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def batch_root(leaf_hashes: Iterable[str]) -> str:
    """Sorted SHA-256 Merkle root over hex leaf hashes (RFC 6962-style domain tags).

    Leaves are lowercase 64-hex SHA-256 digests. They are sorted, so ordering
    cannot change the root; duplicates and empty batches are refused.
    An odd node is promoted unchanged to the next level.
    """
    if isinstance(leaf_hashes, (str, bytes)):
        raise AnchorError("leaf_hashes must be an iterable of hex digests")
    leaves = list(leaf_hashes)
    if not leaves:
        raise AnchorError("empty batch")
    if len(leaves) > MAX_LEAVES:
        raise AnchorError("batch too large")
    for x in leaves:
        if not isinstance(x, str) or not _HEX64.match(x):
            raise AnchorError("leaf is not a lowercase 64-hex sha256 digest")
    if len(set(leaves)) != len(leaves):
        raise AnchorError("duplicate leaf in batch")
    level = [_h(b"\x00" + bytes.fromhex(x)) for x in sorted(leaves)]
    while len(level) > 1:
        nxt = [_h(b"\x01" + level[i] + level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    return level[0].hex()


# ---------------------------------------------------------------- openssl
def _openssl() -> str:
    exe = shutil.which("openssl")
    if not exe:
        raise AnchorError("openssl CLI not available")
    return exe


def _run(args: Sequence[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run([_openssl(), *args], capture_output=True, timeout=timeout,
                          env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"})


def _check_root(root_hex: str) -> str:
    if not isinstance(root_hex, str) or not _HEX64.match(root_hex):
        raise AnchorError("root must be a lowercase 64-hex sha256 digest")
    return root_hex


# ---------------------------------------------------------------- RFC 3161
def tsa_request(root_hex: str, *, nonce: bool = True) -> bytes:
    """Build a DER TimeStampReq over ``root_hex`` (SHA-256 imprint, cert requested)."""
    _check_root(root_hex)
    args = ["ts", "-query", "-digest", root_hex, "-sha256", "-cert"]
    if not nonce:
        args.append("-no_nonce")
    p = _run(args)
    if p.returncode != 0 or not p.stdout:
        raise AnchorError("openssl ts -query failed")
    return p.stdout


def tsa_stamp(root_hex: str, url: str, *, allow_network: bool = False,
              post: Callable[[str, bytes], bytes] | None = None) -> bytes:
    """Request a token from a TSA. Refuses unless ``allow_network`` is True.

    Never called by repository code (not activated). Returns raw ``.tsr`` bytes;
    the caller must still run :func:`tsa_verify` on them.
    """
    if not allow_network:
        raise AnchorError("network disabled: anchor module is not activated")
    if not CAPTURE_ACTIVE:
        raise AnchorError("capture not activated")
    if url not in TSA_URLS:
        raise AnchorError("TSA url not in pinned list")
    req = tsa_request(root_hex)
    if post is None:
        import requests  # local import: no network surface at module import

        def post(u: str, body: bytes) -> bytes:
            r = requests.post(u, data=body, timeout=20,
                              headers={"Content-Type": "application/timestamp-query"})
            r.raise_for_status()
            return r.content
    resp = post(url, req)
    if not isinstance(resp, (bytes, bytearray)) or not resp or len(resp) > MAX_TOKEN_BYTES:
        raise AnchorError("bad TSA response")
    return bytes(resp)


_GENTIME = re.compile(r"^Time stamp:\s*(.+?)\s*$", re.M)


def _parse_gentime(text: str) -> datetime:
    m = _GENTIME.search(text)
    if not m:
        raise AnchorError("genTime missing from token")
    raw = m.group(1).replace(" GMT", "").strip()
    raw = re.sub(r"\s+", " ", raw)
    raw = re.sub(r"\.\d+", "", raw)  # drop fractional seconds (floor)
    try:
        return datetime.strptime(raw, "%b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise AnchorError("unparseable genTime") from e


@dataclass(frozen=True)
class TsaResult:
    ok: bool
    reason: str
    gen_time: datetime | None = None
    token_sha256: str | None = None


def tsa_verify(token: bytes, root_hex: str, ca_bundle_pem: bytes,
               untrusted_pem: bytes | None = None,
               pinned_tsa_cert_sha256: Iterable[str] | None = None, *,
               request_der: bytes | None = None, now: datetime | None = None,
               max_clock_skew_s: int = 30) -> TsaResult:
    """Offline verification of a ``.tsr`` reply against ``root_hex``.

    Checks (via ``openssl ts -verify``): status granted, message imprint equals
    the root, signature chains to ``ca_bundle_pem`` with timeStamping EKU.
    Optionally pins the signer certificate's DER SHA-256. Also checks:
    genTime is not later than ``now + max_clock_skew_s``; every certificate
    embedded in the token is valid AT genTime; and, when ``request_der`` is
    given, the reply matches that request (imprint AND nonce). Never raises.
    """
    try:
        _check_root(root_hex)
        if not isinstance(token, (bytes, bytearray)) or not token:
            return TsaResult(False, "missing_token")
        if len(token) > MAX_TOKEN_BYTES:
            return TsaResult(False, "token_too_large")
        if not isinstance(ca_bundle_pem, (bytes, bytearray)) or not ca_bundle_pem:
            return TsaResult(False, "missing_ca_bundle")
        tok_sha = hashlib.sha256(token).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            tsr, ca = os.path.join(d, "t.tsr"), os.path.join(d, "ca.pem")
            open(tsr, "wb").write(token)
            open(ca, "wb").write(ca_bundle_pem)
            # Parse the signed token's generation time before chain checking.
            # Validation at the verifier's *current* clock incorrectly rejects
            # genuine older timestamps once their signer certificates expire.
            # -attime checks the complete X.509 chain at RFC 3161 genTime.
            t = _run(["ts", "-reply", "-in", tsr, "-text"])
            if t.returncode != 0:
                return TsaResult(False, "token_unreadable", token_sha256=tok_sha)
            text = t.stdout.decode("utf-8", "replace")
            if "Status: Granted." not in text:
                return TsaResult(False, "status_not_granted", token_sha256=tok_sha)
            if not re.search(r"Hash Algorithm:\s*sha256", text):
                return TsaResult(False, "imprint_not_sha256", token_sha256=tok_sha)
            gen = _parse_gentime(text)
            ref = now or datetime.now(timezone.utc)
            if not isinstance(ref, datetime) or ref.tzinfo is None or ref.utcoffset() is None:
                return TsaResult(False, "invalid_verifier_clock", token_sha256=tok_sha)
            if gen > ref + timedelta(seconds=max_clock_skew_s):
                return TsaResult(False, "gentime_in_future", gen, tok_sha)
            at_time = str(int(gen.timestamp()))
            args = ["ts", "-verify", "-attime", at_time, "-digest", root_hex,
                    "-in", tsr, "-CAfile", ca]
            extra: list[str] = []
            if untrusted_pem:
                un = os.path.join(d, "u.pem")
                open(un, "wb").write(untrusted_pem)
                extra = ["-untrusted", un]
            v = _run(args + extra)
            if v.returncode != 0 or b"Verification: OK" not in v.stdout:
                return TsaResult(False, "tsa_verify_failed", token_sha256=tok_sha)
            if request_der is not None:
                if not isinstance(request_der, (bytes, bytearray)) or not request_der:
                    return TsaResult(False, "malformed_request", token_sha256=tok_sha)
                q = os.path.join(d, "q.tsq")
                open(q, "wb").write(request_der)
                # -queryfile enforces reply imprint == request imprint AND nonce equality
                v2 = _run(["ts", "-verify", "-attime", at_time, "-queryfile", q,
                           "-in", tsr, "-CAfile", ca] + extra)
                if v2.returncode != 0 or b"Verification: OK" not in v2.stdout:
                    return TsaResult(False, "request_mismatch", token_sha256=tok_sha)
            # certificate validity at genTime (openssl -verify checks at "now")
            tokv = os.path.join(d, "tokv.der")
            xv = _run(["ts", "-reply", "-in", tsr, "-token_out", "-out", tokv])
            cv = _run(["pkcs7", "-inform", "DER", "-in", tokv, "-print_certs"]) if xv.returncode == 0 else xv
            emb = re.findall(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----",
                             cv.stdout or b"", re.S)
            if not emb:
                return TsaResult(False, "signer_cert_not_embedded", gen, tok_sha)
            for pem in emb:
                pf = os.path.join(d, "v.pem")
                open(pf, "wb").write(pem)
                r = _run(["x509", "-in", pf, "-noout", "-startdate", "-enddate"])
                dates = dict(l.split("=", 1) for l in r.stdout.decode().splitlines() if "=" in l)
                try:
                    nb = datetime.strptime(re.sub(r"\s+", " ", dates["notBefore"].replace(" GMT", "")),
                                           "%b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
                    na = datetime.strptime(re.sub(r"\s+", " ", dates["notAfter"].replace(" GMT", "")),
                                           "%b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
                except (KeyError, ValueError):
                    return TsaResult(False, "cert_dates_unreadable", gen, tok_sha)
                if not (nb <= gen <= na):
                    return TsaResult(False, "cert_not_valid_at_gentime", gen, tok_sha)
            if pinned_tsa_cert_sha256 is not None:
                # Pin ONLY the certificate that actually signed this RFC 3161
                # CMS token, never any arbitrary embedded chain certificate.
                pins = {p.lower() for p in pinned_tsa_cert_sha256}
                if not pins:
                    return TsaResult(False, "tsa_cert_not_pinned", token_sha256=tok_sha)
                tok = os.path.join(d, "tok.der")
                signed = os.path.join(d, "signer.pem")
                payload = os.path.join(d, "tstinfo.der")
                x = _run(["ts", "-reply", "-in", tsr, "-token_out", "-out", tok])
                if x.returncode != 0:
                    return TsaResult(False, "tsa_signer_unreadable", token_sha256=tok_sha)
                # OpenSSL cms -verify validates CMS signatures and writes the
                # actual signer(s) to -signer. Chain/EKU verification remains
                # the separate openssl ts -verify step above.
                c = _run(["cms", "-verify", "-inform", "DER", "-in", tok,
                          "-noverify", "-signer", signed, "-out", payload])
                if c.returncode != 0:
                    return TsaResult(False, "tsa_signer_unreadable", token_sha256=tok_sha)
                try:
                    signer_pem = Path(signed).read_bytes()
                except OSError:
                    return TsaResult(False, "tsa_signer_unreadable", token_sha256=tok_sha)
                signer_certs = re.findall(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----",
                                          signer_pem, re.S)
                if len(signer_certs) != 1:
                    # No signer / multi-signer tokens require a separate,
                    # reviewed policy rather than 'any pin intersects'.
                    return TsaResult(False, "tsa_signer_count_invalid", token_sha256=tok_sha)
                pf = os.path.join(d, "signer_one.pem")
                Path(pf).write_bytes(signer_certs[0])
                der = _run(["x509", "-in", pf, "-outform", "DER"])
                if der.returncode != 0 or not der.stdout:
                    return TsaResult(False, "tsa_signer_unreadable", token_sha256=tok_sha)
                if hashlib.sha256(der.stdout).hexdigest() not in pins:
                    return TsaResult(False, "tsa_cert_not_pinned", token_sha256=tok_sha)
        return TsaResult(True, "ok", gen, tok_sha)
    except AnchorError as e:
        return TsaResult(False, f"malformed:{e}")
    except (OSError, subprocess.SubprocessError):
        return TsaResult(False, "verifier_error")


# ---------------------------------------------------------------- OpenTimestamps
OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
_OTS_SHA256 = b"\x08"


def ots_stamp(root_hex: str, *, allow_network: bool = False) -> bytes:
    """Submit to OTS calendars via the ``ots`` CLI. Refuses unless allowed."""
    _check_root(root_hex)
    if not allow_network:
        raise AnchorError("network disabled: anchor module is not activated")
    raise AnchorError("ots stamping not wired: requires opentimestamps-client (owner ruling)")


@dataclass(frozen=True)
class OtsResult:
    ok: bool
    reason: str
    bitcoin_attested: bool = False
    attested_heights: tuple[int, ...] = ()
    pending_calendars: tuple[str, ...] = ()
    attested_time: datetime | None = None


_TAG_BITCOIN = bytes.fromhex("0588960d73d71901")
_TAG_PENDING = bytes.fromhex("83dfe30d2ef90c8e")
_OTS_MAX_DEPTH = 256
_OTS_MAX_OPS = 10_000


class _Rd:
    def __init__(self, b: bytes, i: int):
        self.b, self.i, self.ops = b, i, 0

    def byte(self) -> int:
        if self.i >= len(self.b):
            raise AnchorError("truncated proof")
        v = self.b[self.i]
        self.i += 1
        return v

    def take(self, n: int) -> bytes:
        if n < 0 or self.i + n > len(self.b):
            raise AnchorError("truncated proof")
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def varuint(self) -> int:
        v, sh = 0, 0
        while True:
            c = self.byte()
            v |= (c & 0x7F) << sh
            if not c & 0x80:
                return v
            sh += 7
            if sh > 63:
                raise AnchorError("varuint overflow")

    def varbytes(self, maxlen: int = 8192) -> bytes:
        n = self.varuint()
        if n > maxlen:
            raise AnchorError("varbytes too long")
        return self.take(n)


def _ots_apply(tag: int, rd: _Rd, msg: bytes) -> bytes:
    if tag == 0x08:
        return hashlib.sha256(msg).digest()
    if tag == 0x02:
        return hashlib.sha1(msg).digest()
    if tag == 0x03:
        return hashlib.new("ripemd160", msg).digest()
    if tag == 0xF0:
        return msg + rd.varbytes()
    if tag == 0xF1:
        return rd.varbytes() + msg
    if tag == 0xF2:
        return msg[::-1]
    if tag == 0xF3:
        return msg.hex().encode()
    raise AnchorError(f"unsupported ots op 0x{tag:02x}")


def _ots_walk(rd: _Rd, msg: bytes, depth: int, out: list) -> None:
    """Deserialize one timestamp node (python-opentimestamps format)."""
    if depth > _OTS_MAX_DEPTH:
        raise AnchorError("proof too deep")
    while True:
        rd.ops += 1
        if rd.ops > _OTS_MAX_OPS:
            raise AnchorError("proof too large")
        tag = rd.byte()
        fork = tag == 0xFF
        if fork:
            tag = rd.byte()
        if tag == 0x00:
            atag = rd.take(8)
            payload = rd.varbytes()
            out.append((atag, payload, msg))
        else:
            _ots_walk(rd, _ots_apply(tag, rd, msg), depth + 1, out)
        if not fork:
            return


def ots_verify(proof: bytes, root_hex: str,
               block_headers: Mapping[int, bytes] | None = None) -> OtsResult:
    """Offline verification of a detached ``.ots`` proof over ``root_hex``.

    Parses the full proof tree (append/prepend/sha256/... ops, forks) and
    collects attestations. A Bitcoin attestation is CONFIRMED only when the
    caller supplies the raw 80-byte block header for that height (fetched and
    checked by an independent node/explorer, never by this function) and the
    computed commitment equals the header's merkle root. Pending calendar
    attestations are reported but never count as attested.
    Secondary evidence only; never used by :func:`admit`. Never raises.
    """
    try:
        _check_root(root_hex)
        if not isinstance(proof, (bytes, bytearray)) or not proof:
            return OtsResult(False, "missing_proof")
        p = bytes(proof)
        if len(p) > MAX_TOKEN_BYTES:
            return OtsResult(False, "proof_too_large")
        if not p.startswith(OTS_MAGIC):
            return OtsResult(False, "bad_magic")
        i = len(OTS_MAGIC)
        if p[i:i + 1] != b"\x01":
            return OtsResult(False, "bad_version")
        if p[i + 1:i + 2] != _OTS_SHA256:
            return OtsResult(False, "not_sha256")
        digest = p[i + 2:i + 34]
        if len(digest) != 32 or digest.hex() != root_hex:
            return OtsResult(False, "digest_mismatch")
        rd = _Rd(p, i + 34)
        atts: list = []
        _ots_walk(rd, digest, 0, atts)
        if rd.i != len(p):
            return OtsResult(False, "trailing_bytes")
        heights, pending, times, bad = [], [], [], False
        for atag, payload, msg in atts:
            if atag == _TAG_PENDING:
                pr = _Rd(payload, 0)
                pending.append(pr.varbytes(1000).decode("ascii", "replace"))
            elif atag == _TAG_BITCOIN:
                h = _Rd(payload, 0).varuint()
                hdr = (block_headers or {}).get(h)
                if hdr is None:
                    continue
                if not isinstance(hdr, (bytes, bytearray)) or len(hdr) != 80:
                    return OtsResult(False, "bad_block_header")
                if bytes(hdr[36:68]) != msg:
                    bad = True
                    continue
                heights.append(h)
                times.append(datetime.fromtimestamp(int.from_bytes(hdr[68:72], "little"), timezone.utc))
        if heights:
            return OtsResult(True, "bitcoin_attested", True, tuple(heights), tuple(pending), min(times))
        if bad:
            return OtsResult(False, "merkle_root_mismatch", pending_calendars=tuple(pending))
        if pending or atts:
            return OtsResult(True, "structure_ok_unattested", pending_calendars=tuple(pending))
        return OtsResult(False, "no_attestations")
    except AnchorError as e:
        return OtsResult(False, f"malformed:{e}")


# ---------------------------------------------------------------- admission
@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    reason: str
    gen_time: datetime | None = None
    details: tuple[str, ...] = field(default_factory=tuple)


def admit(bundle: Mapping, *, event_cutoff: datetime, ca_bundle_pem: bytes,
          margin_s: int = DEFAULT_PREGAME_MARGIN_S, min_tokens: int = DEFAULT_MIN_TOKENS,
          approved_ids: frozenset[str] | None = None,
          pinned_tsa_cert_sha256: Iterable[str] | None = None) -> AdmissionDecision:
    """Fail-closed admission of an anchored evidence batch.

    ``bundle`` = {"anchor_id", "leaves": [hex...], "root": hex,
                  "tsa_tokens": [bytes...], optional "untrusted_pem": bytes}.
    Admitted only if: anchor_id is approved; recomputed root equals the claimed
    root; at least ``min_tokens`` tokens verify; and the EARLIEST verified
    genTime is <= event_cutoff - margin. Never raises.
    """
    if approved_ids is None:
        if not ADMISSION_ACTIVE:
            return AdmissionDecision(False, "admission_not_activated")
        # Legacy single-TSA admission must never become a production route.
        return AdmissionDecision(False, "single_tsa_admission_forbidden")
    approved = approved_ids
    try:
        if not isinstance(bundle, Mapping):
            return AdmissionDecision(False, "malformed_bundle")
        if not isinstance(event_cutoff, datetime) or event_cutoff.tzinfo is None:
            return AdmissionDecision(False, "cutoff_not_tz_aware")
        if isinstance(margin_s, bool) or not isinstance(margin_s, int) or margin_s < 0:
            return AdmissionDecision(False, "bad_margin")
        if isinstance(min_tokens, bool) or not isinstance(min_tokens, int) or min_tokens < 1:
            return AdmissionDecision(False, "bad_min_tokens")
        aid = bundle.get("anchor_id")
        if not isinstance(aid, str) or aid not in approved:
            return AdmissionDecision(False, "anchor_id_not_approved")
        leaves = bundle.get("leaves")
        if not isinstance(leaves, (list, tuple)):
            return AdmissionDecision(False, "malformed_leaves")
        try:
            root = batch_root(leaves)
        except AnchorError as e:
            return AdmissionDecision(False, f"malformed_leaves:{e}")
        if bundle.get("root") != root:
            return AdmissionDecision(False, "root_mismatch")
        tokens = bundle.get("tsa_tokens")
        if not isinstance(tokens, (list, tuple)) or not tokens:
            return AdmissionDecision(False, "missing_token")
        untrusted = bundle.get("untrusted_pem")
        if untrusted is not None and not isinstance(untrusted, (bytes, bytearray)):
            return AdmissionDecision(False, "malformed_untrusted_pem")
        results = [tsa_verify(t, root, ca_bundle_pem, untrusted, pinned_tsa_cert_sha256)
                   for t in tokens]
        good = [r for r in results if r.ok and r.gen_time is not None]
        if len({r.token_sha256 for r in good}) < min_tokens:
            return AdmissionDecision(False, "insufficient_verified_tokens", None,
                                     tuple(r.reason for r in results))
        gen = min(r.gen_time for r in good)
        if gen > event_cutoff - timedelta(seconds=margin_s):
            return AdmissionDecision(False, "gentime_after_cutoff_minus_margin", gen)
        return AdmissionDecision(True, "admitted", gen)
    except Exception as e:  # fail closed on anything unexpected
        return AdmissionDecision(False, f"internal_error:{type(e).__name__}")


# ---------------------------------------------------------------- dual-TSA quorum
def provider_trust(provider: TsaProvider, repo_root: Path | None = None) -> tuple[bytes, tuple[str, ...]]:
    """Return (ca_bundle_pem, signer pins) for a PINNED provider; refuse otherwise."""
    if not provider.pinned:
        raise AnchorError(f"provider {provider.id} not pinned")
    root = repo_root or CONFIG_PATH.parents[2]
    path = (root / provider.ca_bundle_path).resolve()
    if root.resolve() not in path.parents:
        raise AnchorError("ca bundle path escapes repo")
    return path.read_bytes(), provider.signer_cert_sha256


def admit_quorum(bundle: Mapping, *, event_cutoff: datetime,
                 trust: Mapping[str, tuple[bytes, Sequence[str]]],
                 min_distinct_providers: int = 2,
                 margin_s: int = DEFAULT_PREGAME_MARGIN_S,
                 approved_ids: frozenset[str] | None = None,
                 now: datetime | None = None, max_clock_skew_s: int = 30) -> AdmissionDecision:
    """Dual-TSA quorum admission.

    ``bundle["tsa_tokens"]`` is a list of ``{"provider": id, "token": bytes,
    optional "request": bytes}``. Each token is verified ONLY against its own
    provider's CA bundle and signer-cert pins from ``trust``. Admission needs
    ``min_distinct_providers`` distinct providers to verify (two tokens from
    one TSA count once), and the LATEST verified genTime among the quorum must
    be <= cutoff - margin (every quorum member must be pregame). Default path
    (``approved_ids is None``) refuses while ADMISSION_ACTIVE is False.
    """
    if approved_ids is None and not ADMISSION_ACTIVE:
        return AdmissionDecision(False, "admission_not_activated")
    approved = APPROVED_ANCHOR_IDS if approved_ids is None else approved_ids
    try:
        if not isinstance(bundle, Mapping):
            return AdmissionDecision(False, "malformed_bundle")
        if not isinstance(event_cutoff, datetime) or event_cutoff.tzinfo is None:
            return AdmissionDecision(False, "cutoff_not_tz_aware")
        for v in (margin_s, min_distinct_providers, max_clock_skew_s):
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                return AdmissionDecision(False, "bad_parameter")
        if min_distinct_providers < 2:
            return AdmissionDecision(False, "quorum_below_two")
        aid = bundle.get("anchor_id")
        if not isinstance(aid, str) or aid not in approved:
            return AdmissionDecision(False, "anchor_id_not_approved")
        leaves = bundle.get("leaves")
        if not isinstance(leaves, (list, tuple)):
            return AdmissionDecision(False, "malformed_leaves")
        try:
            root = batch_root(leaves)
        except AnchorError as e:
            return AdmissionDecision(False, f"malformed_leaves:{e}")
        if bundle.get("root") != root:
            return AdmissionDecision(False, "root_mismatch")
        entries = bundle.get("tsa_tokens")
        if not isinstance(entries, (list, tuple)) or not entries:
            return AdmissionDecision(False, "missing_token")
        verified: dict[str, datetime] = {}
        details = []
        for e in entries:
            if not isinstance(e, Mapping) or not isinstance(e.get("provider"), str):
                details.append("malformed_entry")
                continue
            pid = e["provider"]
            if pid not in trust:
                details.append(f"{pid}:unknown_provider")
                continue
            ca, pins = trust[pid]
            r = tsa_verify(e.get("token"), root, ca, None, list(pins),
                           request_der=e.get("request"), now=now, max_clock_skew_s=max_clock_skew_s)
            details.append(f"{pid}:{r.reason}")
            if r.ok and r.gen_time is not None:
                verified[pid] = max(verified.get(pid, r.gen_time), r.gen_time)
        if len(verified) < min_distinct_providers:
            return AdmissionDecision(False, "tsa_quorum_not_met", None, tuple(details))
        gen = max(verified.values())
        if gen > event_cutoff - timedelta(seconds=margin_s):
            return AdmissionDecision(False, "gentime_after_cutoff_minus_margin", gen, tuple(details))
        return AdmissionDecision(True, "admitted", gen, tuple(details))
    except Exception as e:  # fail closed
        return AdmissionDecision(False, f"internal_error:{type(e).__name__}")

def admit_configured_quorum(bundle: Mapping, *, event_cutoff: datetime) -> AdmissionDecision:
    """Production path: use only configured, separately approved pinned authorities.

    The injectable admit_quorum primitive is used by offline tests; production
    evidence consumers must use this wrapper, without caller-supplied trust.
    """
    if not ADMISSION_ACTIVE:
        return AdmissionDecision(False, "admission_not_activated")
    try:
        cfg = load_config()
        if not cfg.admission_active or ANCHOR_ID not in cfg.approved_anchor_ids:
            return AdmissionDecision(False, "admission_not_activated")
        if cfg.min_distinct_providers < 2:
            return AdmissionDecision(False, "quorum_below_two")
        if not isinstance(bundle, Mapping):
            return AdmissionDecision(False, "malformed_bundle")
        entries = bundle.get("tsa_tokens")
        if not isinstance(entries, (list, tuple)) or not entries:
            return AdmissionDecision(False, "missing_token")
        # Preserve the exact request DER for every token so nonce binding is
        # obligatory for newly captured evidence, not an optional test knob.
        for e in entries:
            if (not isinstance(e, Mapping) or not isinstance(e.get("request"), (bytes, bytearray))
                    or not e["request"]):
                return AdmissionDecision(False, "request_binding_required")
        if len(cfg.providers) < cfg.min_distinct_providers or any(not p.pinned for p in cfg.providers):
            return AdmissionDecision(False, "tsa_trust_not_pinned")
        trust = {p.id: provider_trust(p) for p in cfg.providers}
        return admit_quorum(bundle, event_cutoff=event_cutoff, trust=trust,
                            min_distinct_providers=cfg.min_distinct_providers,
                            margin_s=cfg.pregame_margin_s,
                            approved_ids=cfg.approved_anchor_ids,
                            max_clock_skew_s=cfg.max_clock_skew_s)
    except (AnchorError, OSError, ValueError, TypeError):
        return AdmissionDecision(False, "configured_trust_unavailable")
