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

import fcntl
import hashlib
import os
import secrets
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
    policy_oids: tuple[str, ...] = ()
    tsa_name_sha256: str | None = None

    @property
    def pinned(self) -> bool:
        # t130: a provider is only pinned when its signer cert, CA bundle AND
        # TSA policy OID(s) are pinned, so a token from another authority
        # cannot satisfy it (cross-authority masquerade).
        return (bool(self.ca_bundle_path) and bool(self.signer_cert_sha256)
                and bool(self.policy_oids) and self.status == "pinned")


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
    nonce_ledger_path: str | None = None
    max_response_window_s: int = 300


_OID_RE = re.compile(r"^[0-2](\.(0|[1-9][0-9]*))+$")


def load_config(path: Path | str | None = None) -> AnchorConfig:
    """Strictly parse the anchor config. Any malformed field raises AnchorError."""
    try:
        raw = json.loads(Path(CONFIG_PATH if path is None else path).read_text(encoding="utf-8"))
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
        pol = pv.get("policy_oids", [])
        if not isinstance(pol, list) or not all(isinstance(x, str) and _OID_RE.match(x) for x in pol):
            raise AnchorError("bad policy_oids")
        nm = pv.get("tsa_name_sha256")
        if nm is not None and not (isinstance(nm, str) and _HEX64.match(nm)):
            raise AnchorError("bad tsa_name_sha256")
        provs.append(TsaProvider(pv["id"], pv["url"], pv.get("ca_bundle_path"), tuple(pins),
                                 str(pv.get("status", "unpinned")), tuple(pol), nm))
    if len({p.id for p in provs}) != len(provs):
        raise AnchorError("duplicate provider id")
    all_pins = [x for p in provs for x in p.signer_cert_sha256]
    if len(set(all_pins)) != len(all_pins):
        # one signer certificate may never stand in for two authorities
        raise AnchorError("signer pin shared by two providers")
    led = raw.get("nonce_ledger")
    led_path = None
    if led is not None:
        if not isinstance(led, dict) or not isinstance(led.get("path"), str) or not led["path"]:
            raise AnchorError("bad nonce_ledger")
        led_path = led["path"]
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
        bool(raw.get("ots", {}).get("enabled", False)), dec or {}, led_path,
        _int(raw.get("max_response_window_s", 300), "max_response_window_s", 1))


def _safe_load() -> AnchorConfig | None:
    try:
        return load_config()
    except AnchorError:
        return None


def activation_flags(path: Path | str | None = None) -> tuple[frozenset[str], bool, bool]:
    """(approved ids, capture_active, admission_active); ANY config defect -> all off."""
    try:
        c = load_config(path)
    except Exception:
        return frozenset(), False, False
    return c.approved_anchor_ids, c.capture_active is True, c.admission_active is True


# Fail closed if the config is missing or malformed: nothing approved, nothing active.
APPROVED_ANCHOR_IDS, CAPTURE_ACTIVE, ADMISSION_ACTIVE = activation_flags()


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
    """Build a DER TimeStampReq over ``root_hex`` (SHA-256 imprint, cert requested).

    ``nonce=False`` exists ONLY for the documented one-off offline fixture
    recording; the production path (:func:`admit_configured_quorum`) refuses
    nonce-less tokens and requests whose nonce is not in the ledger. Production
    requests are built with :func:`new_tsa_request`.
    """
    _check_root(root_hex)
    args = ["ts", "-query", "-digest", root_hex, "-sha256", "-cert"]
    if not nonce:
        args.append("-no_nonce")
    p = _run(args)
    if p.returncode != 0 or not p.stdout:
        raise AnchorError("openssl ts -query failed")
    return p.stdout


# ---------------------------------------------------------------- t130: DER, nonces, ledger
OID_SHA256 = "2.16.840.1.101.3.4.2.1"
NONCE_BITS = 128
MIN_NONCE_BITS = 64


def _der_hdr(b: bytes, i: int) -> tuple[int, int, int]:
    """Return (tag, content_start, content_end) of the TLV at ``i``. Strict DER lengths."""
    if i + 2 > len(b):
        raise AnchorError("der truncated")
    tag, ln = b[i], b[i + 1]
    j = i + 2
    if tag & 0x1F == 0x1F:
        raise AnchorError("der high tag unsupported")
    if ln & 0x80:
        n = ln & 0x7F
        if n == 0 or n > 4 or j + n > len(b):
            raise AnchorError("der bad length")
        ln = int.from_bytes(b[j:j + n], "big")
        j += n
    if j + ln > len(b):
        raise AnchorError("der truncated")
    return tag, j, j + ln


def _der_children(b: bytes, start: int, end: int) -> list[tuple[int, int, int, int]]:
    out, i = [], start
    while i < end:
        tag, cs, ce = _der_hdr(b, i)
        if ce > end:
            raise AnchorError("der child overruns parent")
        out.append((tag, cs, ce, i))
        i = ce
    return out


def _oid(b: bytes) -> str:
    if not b:
        raise AnchorError("empty oid")
    first = b[0]
    parts = [min(first // 40, 2), first - 40 * min(first // 40, 2)]
    v = 0
    for c in b[1:]:
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            parts.append(v)
            v = 0
    return ".".join(map(str, parts))


def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    nb = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(nb)]) + nb


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _len(len(content)) + content


def _der_int(n: int) -> bytes:
    nb = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=False)
    return _tlv(0x02, nb)


_SHA256_ALGID = _tlv(0x30, _tlv(0x06, bytes.fromhex("608648016503040201")) + b"\x05\x00")


def new_nonce() -> int:
    """Cryptographically random 128-bit nonce (top bit set so it is never < 64 bits)."""
    return secrets.randbits(NONCE_BITS) | (1 << (NONCE_BITS - 1))


def build_tsa_request(root_hex: str, nonce: int) -> bytes:
    """DER TimeStampReq (v1, SHA-256 imprint, nonce, certReq=TRUE)."""
    _check_root(root_hex)
    if isinstance(nonce, bool) or not isinstance(nonce, int) or nonce.bit_length() < MIN_NONCE_BITS:
        raise AnchorError("nonce must be an int of >= 64 bits")
    imprint = _tlv(0x30, _SHA256_ALGID + _tlv(0x04, bytes.fromhex(root_hex)))
    return _tlv(0x30, _der_int(1) + imprint + _der_int(nonce) + b"\x01\x01\xff")


@dataclass(frozen=True)
class TsaRequestInfo:
    imprint_alg: str
    digest_hex: str
    nonce: int | None
    policy_oid: str | None


def parse_tsa_request(der: bytes) -> TsaRequestInfo:
    b = bytes(der)
    tag, cs, ce = _der_hdr(b, 0)
    if tag != 0x30 or ce != len(b):
        raise AnchorError("request not a single SEQUENCE")
    kids = _der_children(b, cs, ce)
    if len(kids) < 2 or kids[0][0] != 0x02 or kids[1][0] != 0x30:
        raise AnchorError("bad request structure")
    mi = _der_children(b, kids[1][1], kids[1][2])
    alg = _der_children(b, mi[0][1], mi[0][2])
    policy = nonce = None
    for t, s, e, _ in kids[2:]:
        if t == 0x06:
            policy = _oid(b[s:e])
        elif t == 0x02:
            nonce = int.from_bytes(b[s:e], "big", signed=True)
    return TsaRequestInfo(_oid(b[alg[0][1]:alg[0][2]]), b[mi[1][1]:mi[1][2]].hex(), nonce, policy)


@dataclass(frozen=True)
class TstInfo:
    policy_oid: str
    imprint_alg: str
    digest_hex: str
    gen_time: datetime
    nonce: int | None
    tsa_name_sha256: str | None


def _gentime(raw: bytes) -> datetime:
    t = raw.decode("ascii")
    m = re.fullmatch(r"(\d{14})(?:\.(\d{1,6}))?Z", t)
    if not m:
        raise AnchorError("bad GeneralizedTime")
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if m.group(2):
        dt = dt.replace(microsecond=int(m.group(2).ljust(6, "0")))
    return dt


def parse_tst_info(der: bytes) -> TstInfo:
    """Structural parse of the signed TSTInfo (RFC 3161 section 2.4.2)."""
    b = bytes(der)
    tag, cs, ce = _der_hdr(b, 0)
    if tag != 0x30:
        raise AnchorError("TSTInfo not a SEQUENCE")
    k = _der_children(b, cs, ce)
    if len(k) < 5 or [x[0] for x in k[:5]] != [0x02, 0x06, 0x30, 0x02, 0x18]:
        raise AnchorError("bad TSTInfo structure")
    mi = _der_children(b, k[2][1], k[2][2])
    alg = _der_children(b, mi[0][1], mi[0][2])
    nonce = name = None
    for t, s, e, h in k[5:]:
        if t == 0x02:
            nonce = int.from_bytes(b[s:e], "big", signed=True)
        elif t == 0xA0:
            name = hashlib.sha256(b[h:e]).hexdigest()
    return TstInfo(_oid(b[k[1][1]:k[1][2]]), _oid(b[alg[0][1]:alg[0][2]]),
                   b[mi[1][1]:mi[1][2]].hex(), _gentime(b[k[4][1]:k[4][2]]), nonce, name)


class NonceLedgerError(AnchorError):
    """Ledger unreadable/corrupt/unwritable. Admission must refuse (fail closed)."""


class NonceLedger:
    """Persisted, append-only, flock-serialised nonce ledger (JSON lines).

    ``issue`` records every production request nonce WITH its request digest at
    request time; ``consume`` marks quorum nonces used exactly once. Any read,
    parse or write problem raises :class:`NonceLedgerError`.
    """

    def __init__(self, path: Path | str):
        if not isinstance(path, (str, Path)) or not str(path):
            raise NonceLedgerError("nonce ledger path missing")
        self.path = Path(path)

    def _open(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            return fd
        except OSError as e:
            raise NonceLedgerError(f"nonce ledger unavailable: {e}") from e

    def _state(self, fd) -> dict:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            chunks = []
            while True:
                c = os.read(fd, 1 << 16)
                if not c:
                    break
                chunks.append(c)
            text = b"".join(chunks).decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise NonceLedgerError("nonce ledger unreadable") from e
        st: dict = {}
        if text and not text.endswith("\n"):
            raise NonceLedgerError("nonce ledger torn tail")
        for line in text.splitlines():
            try:
                r = json.loads(line)
                key = (r["provider"], r["nonce"])
                op = r["op"]
            except (ValueError, KeyError, TypeError) as e:
                raise NonceLedgerError("nonce ledger corrupt line") from e
            if not isinstance(key[0], str) or not isinstance(key[1], str) or op not in ("issue", "consume"):
                raise NonceLedgerError("nonce ledger corrupt line")
            cur = st.get(key)
            if op == "issue":
                if cur is not None:
                    raise NonceLedgerError("nonce issued twice")
                st[key] = {"request_sha256": r.get("request_sha256"), "issued_at": r.get("issued_at"),
                           "consumed": False}
            else:
                if cur is None or cur["consumed"]:
                    raise NonceLedgerError("nonce ledger consume without issue / double consume")
                cur["consumed"] = True
        return st

    def _append(self, fd, recs: list[dict]) -> None:
        data = "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs).encode()
        try:
            if os.write(fd, data) != len(data):
                raise NonceLedgerError("short ledger write")
            os.fsync(fd)
        except OSError as e:
            raise NonceLedgerError(f"nonce ledger write failed: {e}") from e

    def issue(self, provider: str, nonce: int, request_der: bytes, *, issued_at: datetime | None = None) -> None:
        at = issued_at or datetime.now(timezone.utc)
        if at.tzinfo is None:
            raise NonceLedgerError("issued_at must be tz-aware")
        fd = self._open()
        try:
            key = (provider, format(nonce, "x"))
            if key in self._state(fd):
                raise NonceLedgerError("nonce already issued")
            self._append(fd, [{"op": "issue", "provider": provider, "nonce": key[1],
                               "request_sha256": hashlib.sha256(request_der).hexdigest(),
                               "issued_at": at.astimezone(timezone.utc).isoformat()}])
        finally:
            os.close(fd)

    def lookup(self, provider: str, nonce: int) -> dict | None:
        fd = self._open()
        try:
            return self._state(fd).get((provider, format(nonce, "x")))
        finally:
            os.close(fd)

    def consume(self, items: Sequence[tuple[str, int]]) -> str | None:
        """Atomically consume all (provider, nonce); return a refusal reason or None."""
        fd = self._open()
        try:
            st = self._state(fd)
            keys = [(p, format(n, "x")) for p, n in items]
            if len(set(keys)) != len(keys):
                return "nonce_reused_in_bundle"
            for k in keys:
                if k not in st:
                    return "nonce_not_issued"
                if st[k]["consumed"]:
                    return "nonce_replayed"
            self._append(fd, [{"op": "consume", "provider": p, "nonce": n} for p, n in keys])
            return None
        finally:
            os.close(fd)


def new_tsa_request(root_hex: str, provider: str, ledger: NonceLedger) -> tuple[bytes, int]:
    """PRODUCTION request builder: fresh nonce, recorded in the ledger before use."""
    n = new_nonce()
    der = build_tsa_request(root_hex, n)
    ledger.issue(provider, n, der)
    return der, n


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
    # Preserve sub-second precision: flooring could wrongly pass a token just
    # after the pregame admission cutoff.
    fmt = "%b %d %H:%M:%S.%f %Y" if re.search(r"\.\d+\s+\d{4}$", raw) else "%b %d %H:%M:%S %Y"
    try:
        return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise AnchorError("unparseable genTime") from e


@dataclass(frozen=True)
class TsaResult:
    ok: bool
    reason: str
    gen_time: datetime | None = None
    token_sha256: str | None = None
    signer_sha256: str | None = None
    nonce: int | None = None
    policy_oid: str | None = None


_PEM = re.compile(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.S)


def _cert_dates(pf: str) -> tuple[datetime, datetime]:
    r = _run(["x509", "-in", pf, "-noout", "-startdate", "-enddate"])
    dates = dict(l.split("=", 1) for l in r.stdout.decode().splitlines() if "=" in l)
    f = lambda v: datetime.strptime(re.sub(r"\s+", " ", v.replace(" GMT", "")),
                                    "%b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
    return f(dates["notBefore"]), f(dates["notAfter"])


def tsa_verify(token: bytes, root_hex: str, ca_bundle_pem: bytes,
               untrusted_pem: bytes | None = None,
               pinned_tsa_cert_sha256: Iterable[str] | None = None, *,
               request_der: bytes | None = None, now: datetime | None = None,
               max_clock_skew_s: int = 30,
               expected_policy_oids: Iterable[str] | None = None,
               expected_tsa_name_sha256: str | None = None,
               expected_nonce: int | None = None,
               require_nonce: bool = False) -> TsaResult:
    """Offline verification of a ``.tsr`` reply against ``root_hex``. Never raises.

    Checks: status granted; the signed TSTInfo (parsed structurally) has a
    SHA-256 imprint equal to the root; signature chains to ``ca_bundle_pem``
    with timeStamping EKU at genTime; genTime not later than ``now + skew``;
    every embedded certificate valid AT genTime; optional signer-cert pin,
    TSA policy OID pin and TSA name pin (per provider, anti-masquerade); and
    nonce: ``require_nonce`` refuses a nonce-less token, ``expected_nonce``
    must equal the echoed nonce, ``request_der`` must match (imprint+nonce).
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
            t = _run(["ts", "-reply", "-in", tsr, "-text"])
            if t.returncode != 0:
                return TsaResult(False, "token_unreadable", token_sha256=tok_sha)
            text = t.stdout.decode("utf-8", "replace")
            if "Status: Granted." not in text:
                return TsaResult(False, "status_not_granted", token_sha256=tok_sha)
            # signed TSTInfo payload + actual CMS signer (signature checked, chain not yet)
            tok = os.path.join(d, "tok.der")
            signed = os.path.join(d, "signer.pem")
            payload = os.path.join(d, "tstinfo.der")
            x = _run(["ts", "-reply", "-in", tsr, "-token_out", "-out", tok])
            if x.returncode != 0:
                return TsaResult(False, "token_unreadable", token_sha256=tok_sha)
            c = _run(["cms", "-verify", "-inform", "DER", "-in", tok,
                      "-noverify", "-signer", signed, "-out", payload])
            if c.returncode != 0:
                return TsaResult(False, "tsa_signer_unreadable", token_sha256=tok_sha)
            try:
                info = parse_tst_info(Path(payload).read_bytes())
            except (AnchorError, OSError, UnicodeDecodeError, ValueError):
                return TsaResult(False, "tstinfo_unparseable", token_sha256=tok_sha)
            gen = info.gen_time
            if info.imprint_alg != OID_SHA256 or not re.search(r"Hash Algorithm:\s*sha256", text):
                return TsaResult(False, "imprint_not_sha256", gen, tok_sha)
            if info.digest_hex != root_hex:
                return TsaResult(False, "imprint_mismatch", gen, tok_sha)
            ref = now or datetime.now(timezone.utc)
            if not isinstance(ref, datetime) or ref.tzinfo is None or ref.utcoffset() is None:
                return TsaResult(False, "invalid_verifier_clock", token_sha256=tok_sha)
            if gen > ref + timedelta(seconds=max_clock_skew_s):
                return TsaResult(False, "gentime_in_future", gen, tok_sha)
            if require_nonce and info.nonce is None:
                return TsaResult(False, "nonce_missing", gen, tok_sha)
            if expected_nonce is not None and info.nonce != expected_nonce:
                return TsaResult(False, "nonce_mismatch", gen, tok_sha)
            if expected_policy_oids is not None:
                pol = set(expected_policy_oids)
                if not pol:
                    return TsaResult(False, "tsa_policy_not_pinned", gen, tok_sha)
                if info.policy_oid not in pol:
                    return TsaResult(False, "tsa_policy_mismatch", gen, tok_sha)
            if expected_tsa_name_sha256 is not None and info.tsa_name_sha256 != expected_tsa_name_sha256:
                return TsaResult(False, "tsa_name_mismatch", gen, tok_sha)
            at_time = str(int(gen.timestamp()))
            args = ["ts", "-verify", "-attime", at_time, "-digest", root_hex,
                    "-in", tsr, "-CAfile", ca]
            extra: list[str] = []
            if untrusted_pem:
                un = os.path.join(d, "u.pem")
                open(un, "wb").write(untrusted_pem)
                extra = ["-untrusted", un]
            # certificate validity at genTime, checked before the chain so the
            # refusal reason is specific
            cv = _run(["pkcs7", "-inform", "DER", "-in", tok, "-print_certs"])
            emb = _PEM.findall(cv.stdout or b"")
            if not emb:
                return TsaResult(False, "signer_cert_not_embedded", gen, tok_sha)
            for pem in emb:
                pf = os.path.join(d, "v.pem")
                open(pf, "wb").write(pem)
                try:
                    nb, na = _cert_dates(pf)
                except (KeyError, ValueError):
                    return TsaResult(False, "cert_dates_unreadable", gen, tok_sha)
                if not (nb <= gen <= na):
                    return TsaResult(False, "cert_not_valid_at_gentime", gen, tok_sha)
            v = _run(args + extra)
            if v.returncode != 0 or b"Verification: OK" not in v.stdout:
                return TsaResult(False, "tsa_verify_failed", gen, tok_sha)
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
            try:
                signer_pem = Path(signed).read_bytes()
            except OSError:
                return TsaResult(False, "tsa_signer_unreadable", token_sha256=tok_sha)
            signer_certs = _PEM.findall(signer_pem)
            if len(signer_certs) != 1:
                return TsaResult(False, "tsa_signer_count_invalid", token_sha256=tok_sha)
            pf = os.path.join(d, "signer_one.pem")
            Path(pf).write_bytes(signer_certs[0])
            der = _run(["x509", "-in", pf, "-outform", "DER"])
            if der.returncode != 0 or not der.stdout:
                return TsaResult(False, "tsa_signer_unreadable", token_sha256=tok_sha)
            signer_sha = hashlib.sha256(der.stdout).hexdigest()
            if pinned_tsa_cert_sha256 is not None:
                # Pin ONLY the certificate that actually signed this CMS token.
                pins = {p.lower() for p in pinned_tsa_cert_sha256}
                if not pins or signer_sha not in pins:
                    return TsaResult(False, "tsa_cert_not_pinned", token_sha256=tok_sha)
        return TsaResult(True, "ok", gen, tok_sha, signer_sha, info.nonce, info.policy_oid)
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


@dataclass(frozen=True)
class ProviderTrust:
    """Per-authority trust: CA bundle, signer pins, TSA policy OID pins, optional TSA name pin."""
    ca_bundle_pem: bytes
    signer_pins: tuple[str, ...]
    policy_oids: tuple[str, ...] | None = None
    tsa_name_sha256: str | None = None


def _as_trust(v) -> ProviderTrust:
    if isinstance(v, ProviderTrust):
        return v
    ca, pins = v
    return ProviderTrust(ca, tuple(pins))


def admit_quorum(bundle: Mapping, *, event_cutoff: datetime,
                 trust: Mapping[str, object],
                 min_distinct_providers: int = 2,
                 margin_s: int = DEFAULT_PREGAME_MARGIN_S,
                 approved_ids: frozenset[str] | None = None,
                 now: datetime | None = None, max_clock_skew_s: int = 30,
                 require_nonce: bool = False, nonce_ledger: NonceLedger | None = None,
                 max_response_window_s: int = 300) -> AdmissionDecision:
    """Dual-TSA quorum admission.

    ``bundle["tsa_tokens"]`` is a list of ``{"provider": id, "token": bytes,
    "request": bytes}``. Each token is verified ONLY against its own provider's
    trust (CA, signer pin, policy OID, TSA name). Quorum = distinct providers
    AND distinct signer certificates (two tokens from one TSA count once).
    The LATEST quorum genTime must be <= cutoff - margin.

    ``require_nonce`` (production): every entry must carry its request DER with
    a >= 64-bit nonce that was ISSUED in ``nonce_ledger`` (same request digest);
    the reply must echo that nonce; genTime must fall within
    [issued_at - skew, issued_at + max_response_window_s]; on admission every
    quorum nonce is consumed exactly once (replays refused). Ledger errors refuse.
    """
    if approved_ids is None and not ADMISSION_ACTIVE:
        return AdmissionDecision(False, "admission_not_activated")
    approved = APPROVED_ANCHOR_IDS if approved_ids is None else approved_ids
    try:
        if not isinstance(bundle, Mapping):
            return AdmissionDecision(False, "malformed_bundle")
        if not isinstance(event_cutoff, datetime) or event_cutoff.tzinfo is None:
            return AdmissionDecision(False, "cutoff_not_tz_aware")
        for v in (margin_s, min_distinct_providers, max_clock_skew_s, max_response_window_s):
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                return AdmissionDecision(False, "bad_parameter")
        if min_distinct_providers < 2:
            return AdmissionDecision(False, "quorum_below_two")
        if require_nonce and not isinstance(nonce_ledger, NonceLedger):
            return AdmissionDecision(False, "nonce_ledger_unconfigured")
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
        signer_of: dict[str, str] = {}
        used: list[tuple[str, int]] = []
        details = []
        for e in entries:
            if not isinstance(e, Mapping) or not isinstance(e.get("provider"), str):
                details.append("malformed_entry")
                continue
            pid = e["provider"]
            if pid not in trust:
                details.append(f"{pid}:unknown_provider")
                continue
            tr = _as_trust(trust[pid])
            req = e.get("request")
            exp_nonce = None
            issued_at = None
            if require_nonce:
                if not isinstance(req, (bytes, bytearray)) or not req:
                    details.append(f"{pid}:request_binding_required")
                    continue
                try:
                    ri = parse_tsa_request(bytes(req))
                except AnchorError:
                    details.append(f"{pid}:malformed_request")
                    continue
                if ri.nonce is None:
                    details.append(f"{pid}:request_nonce_missing")
                    continue
                if ri.nonce < 0 or ri.nonce.bit_length() < MIN_NONCE_BITS:
                    details.append(f"{pid}:nonce_too_short")
                    continue
                if ri.imprint_alg != OID_SHA256:
                    details.append(f"{pid}:request_hash_alg_mismatch")
                    continue
                if ri.digest_hex != root:
                    details.append(f"{pid}:request_imprint_mismatch")
                    continue
                try:
                    rec = nonce_ledger.lookup(pid, ri.nonce)
                except NonceLedgerError:
                    return AdmissionDecision(False, "nonce_ledger_error", None, tuple(details))
                if rec is None:
                    details.append(f"{pid}:nonce_not_issued")
                    continue
                if rec["request_sha256"] != hashlib.sha256(bytes(req)).hexdigest():
                    details.append(f"{pid}:request_not_recorded")
                    continue
                if rec["consumed"]:
                    details.append(f"{pid}:nonce_replayed")
                    continue
                try:
                    issued_at = datetime.fromisoformat(rec["issued_at"])
                    if issued_at.tzinfo is None:
                        raise ValueError
                except (TypeError, ValueError):
                    return AdmissionDecision(False, "nonce_ledger_error", None, tuple(details))
                exp_nonce = ri.nonce
            r = tsa_verify(e.get("token"), root, tr.ca_bundle_pem, None, list(tr.signer_pins),
                           request_der=req, now=now, max_clock_skew_s=max_clock_skew_s,
                           expected_policy_oids=tr.policy_oids,
                           expected_tsa_name_sha256=tr.tsa_name_sha256,
                           expected_nonce=exp_nonce, require_nonce=require_nonce)
            reason = r.reason
            if r.ok and require_nonce and ri.policy_oid is not None and r.policy_oid != ri.policy_oid:
                reason = "request_policy_mismatch"
            if r.ok and issued_at is not None and not (
                    issued_at - timedelta(seconds=max_clock_skew_s) <= r.gen_time
                    <= issued_at + timedelta(seconds=max_response_window_s)):
                reason = "gentime_outside_request_window"
            details.append(f"{pid}:{reason}")
            if reason == "ok" and r.gen_time is not None:
                verified[pid] = max(verified.get(pid, r.gen_time), r.gen_time)
                signer_of.setdefault(pid, r.signer_sha256 or "")
                if exp_nonce is not None:
                    used.append((pid, exp_nonce))
        distinct_signers = {signer_of[p] for p in verified}
        if len(verified) < min_distinct_providers or len(distinct_signers) < min_distinct_providers:
            return AdmissionDecision(False, "tsa_quorum_not_met", None, tuple(details))
        gen = max(verified.values())
        if gen > event_cutoff - timedelta(seconds=margin_s):
            return AdmissionDecision(False, "gentime_after_cutoff_minus_margin", gen, tuple(details))
        if require_nonce:
            try:
                why = nonce_ledger.consume(used)
            except NonceLedgerError:
                return AdmissionDecision(False, "nonce_ledger_error", None, tuple(details))
            if why is not None:
                return AdmissionDecision(False, why, None, tuple(details))
        return AdmissionDecision(True, "admitted", gen, tuple(details))
    except Exception as e:  # fail closed
        return AdmissionDecision(False, f"internal_error:{type(e).__name__}")


def admit_configured_quorum(bundle: Mapping, *, event_cutoff: datetime,
                            config_path: Path | str | None = None) -> AdmissionDecision:
    """Production path: configured, pinned authorities; nonce ledger REQUIRED.

    The injectable admit_quorum primitive is used by offline tests; production
    evidence consumers must use this wrapper, without caller-supplied trust.
    """
    if not ADMISSION_ACTIVE:
        return AdmissionDecision(False, "admission_not_activated")
    try:
        cfg = load_config(config_path)
        if cfg.admission_active is not True or ANCHOR_ID not in cfg.approved_anchor_ids:
            return AdmissionDecision(False, "admission_not_activated")
        if cfg.min_distinct_providers < 2:
            return AdmissionDecision(False, "quorum_below_two")
        if not isinstance(bundle, Mapping):
            return AdmissionDecision(False, "malformed_bundle")
        entries = bundle.get("tsa_tokens")
        if not isinstance(entries, (list, tuple)) or not entries:
            return AdmissionDecision(False, "missing_token")
        for e in entries:
            if (not isinstance(e, Mapping) or not isinstance(e.get("request"), (bytes, bytearray))
                    or not e["request"]):
                return AdmissionDecision(False, "request_binding_required")
        if len(cfg.providers) < cfg.min_distinct_providers or any(not p.pinned for p in cfg.providers):
            return AdmissionDecision(False, "tsa_trust_not_pinned")
        if not cfg.nonce_ledger_path:
            return AdmissionDecision(False, "nonce_ledger_unconfigured")
        repo = Path(CONFIG_PATH if config_path is None else config_path).resolve().parents[2]
        lp = Path(cfg.nonce_ledger_path)
        ledger = NonceLedger(lp if lp.is_absolute() else repo / lp)
        trust = {}
        for p in cfg.providers:
            ca, pins = provider_trust(p, repo)
            trust[p.id] = ProviderTrust(ca, pins, p.policy_oids, p.tsa_name_sha256)
        return admit_quorum(bundle, event_cutoff=event_cutoff, trust=trust,
                            min_distinct_providers=cfg.min_distinct_providers,
                            margin_s=cfg.pregame_margin_s,
                            approved_ids=cfg.approved_anchor_ids,
                            max_clock_skew_s=cfg.max_clock_skew_s,
                            require_nonce=True, nonce_ledger=ledger,
                            max_response_window_s=cfg.max_response_window_s)
    except (AnchorError, OSError, ValueError, TypeError):
        return AdmissionDecision(False, "configured_trust_unavailable")
