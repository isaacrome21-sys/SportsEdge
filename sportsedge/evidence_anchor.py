"""External evidence anchor: batch Merkle roots, RFC 3161 TSA tokens, OpenTimestamps.

Implements module step 1 of the anchor/host proposal (2026-10-13) OFFLINE ONLY.

Status: NOT ACTIVATED.
* ``APPROVED_ANCHOR_IDS`` is EMPTY. ``ANCHOR_ID`` is defined but NOT registered;
  registering it requires the owner's ruling (proposal §7 decision 6).
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

ANCHOR_ID = "anchor:rfc3161+ots:v1"  # defined, NOT registered
APPROVED_ANCHOR_IDS: frozenset[str] = frozenset()  # owner ruling required

TSA_URLS: tuple[str, ...] = ("https://freetsa.org/tsr", "http://timestamp.digicert.com")
DEFAULT_PREGAME_MARGIN_S = 900
DEFAULT_MIN_TOKENS = 1
MAX_LEAVES = 1_000_000
MAX_TOKEN_BYTES = 64 * 1024

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AnchorError(ValueError):
    """Raised for malformed anchor input; admission converts it to a refusal."""


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
               pinned_tsa_cert_sha256: Iterable[str] | None = None) -> TsaResult:
    """Offline verification of a ``.tsr`` reply against ``root_hex``.

    Checks (via ``openssl ts -verify``): status granted, message imprint equals
    the root, signature chains to ``ca_bundle_pem`` with timeStamping EKU.
    Optionally pins the signer certificate's DER SHA-256. Never raises.
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
            args = ["ts", "-verify", "-digest", root_hex, "-in", tsr, "-CAfile", ca]
            if untrusted_pem:
                un = os.path.join(d, "u.pem")
                open(un, "wb").write(untrusted_pem)
                args += ["-untrusted", un]
            v = _run(args)
            if v.returncode != 0 or b"Verification: OK" not in v.stdout:
                return TsaResult(False, "tsa_verify_failed", token_sha256=tok_sha)
            t = _run(["ts", "-reply", "-in", tsr, "-text"])
            if t.returncode != 0:
                return TsaResult(False, "token_unreadable", token_sha256=tok_sha)
            text = t.stdout.decode("utf-8", "replace")
            if "Status: Granted." not in text:
                return TsaResult(False, "status_not_granted", token_sha256=tok_sha)
            if not re.search(r"Hash Algorithm:\s*sha256", text):
                return TsaResult(False, "imprint_not_sha256", token_sha256=tok_sha)
            gen = _parse_gentime(text)
            if pinned_tsa_cert_sha256 is not None:
                pins = {p.lower() for p in pinned_tsa_cert_sha256}
                tok = os.path.join(d, "tok.der")
                x = _run(["ts", "-reply", "-in", tsr, "-token_out", "-out", tok])
                c = _run(["pkcs7", "-inform", "DER", "-in", tok, "-print_certs"]) if x.returncode == 0 else x
                certs = re.findall(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----",
                                   c.stdout or b"", re.S)
                ders = []
                for pem in certs:
                    pf = os.path.join(d, "c.pem")
                    open(pf, "wb").write(pem)
                    r = _run(["x509", "-in", pf, "-outform", "DER"])
                    if r.returncode == 0:
                        ders.append(hashlib.sha256(r.stdout).hexdigest())
                if not ders or not (set(ders) & pins):
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


def ots_verify(proof: bytes, root_hex: str) -> OtsResult:
    """Offline structural check of a detached ``.ots`` proof.

    Confirms the header magic, version 1, SHA-256 file-hash op, and that the
    committed digest equals ``root_hex``. Full Bitcoin attestation needs block
    headers and is out of scope offline, so ``bitcoin_attested`` is always
    False here. Secondary evidence only; never used by :func:`admit`.
    """
    try:
        _check_root(root_hex)
        if not isinstance(proof, (bytes, bytearray)) or not proof:
            return OtsResult(False, "missing_proof")
        p = bytes(proof)
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
        return OtsResult(True, "structure_ok_unattested")
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
    approved = APPROVED_ANCHOR_IDS if approved_ids is None else approved_ids
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
