# Anchor TSA pinning provenance (t127, 2026-10-13)

Scope: pins trust material for the owner-approved anchor design
(`anchor:rfc3161+ots:v1`, #2090). **No activation.** `capture_active` and
`admission_active` remain `false`. One provider pinned is not a quorum: the
configured path still refuses everything (`admission_not_activated`, and
`tsa_trust_not_pinned` behind it).

All fetches were made from the Grok build box on 2026-10-14 between 02:48:09Z
and 02:48:22Z (2026-10-13 21:48 CT). Cross-check path 2 is the Internet Archive
raw (`id_`) snapshot of the same URL.

## FreeTSA — PINNED

| file | path 1: direct (fetched 02:48:09Z–02:48:14Z) | path 2: web.archive.org snapshot | match |
|---|---|---|---|
| `https://freetsa.org/files/cacert.pem` → `config/anchors/freetsa_ca.pem` | file sha256 `2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438` | snapshot `20260905062344`, identical bytes | yes |
| `https://freetsa.org/files/tsa.crt` → `config/anchors/freetsa_tsa_signer.pem` | file sha256 `8bfb0305bb64e2571ca507552ef3245cb1c2fee8728e0ff8689225081ea13467` | snapshot `20260905062344`, identical bytes | yes |

- Root CA (`CN=www.freetsa.org, OU=Root CA`, notAfter 2041-03-07) DER sha256
  `a6379e7cecc05faa3cbf076013d745e327bbbaa38c0b9af22469d4701d18aabc`.
- TSA signer (`OU=TSA`, serial `C2E986160DA8E9CD`, notAfter 2040-02-02) DER
  sha256 **`32e841a95cc1164101ffde41298ef2fc75c1c4372ef095e88a6bbd47dfb191fc`**
  = config `signer_cert_sha256`. Confirmed to be the actual CMS signer of the
  recorded token below (`tsa_verify` with this pin returns `ok`).

## DigiCert — NOT PINNED

- `http://timestamp.digicert.com` (HTTP only) could not be reached from the
  build box: outbound port 80 times out for every host; HTTPS to the same host
  is refused. No real DigiCert token could be recorded, so the signer
  certificate cannot be taken from a real token, as the pin procedure requires.
- Root material WAS cross-checked and is recorded here only (not committed,
  not trusted by config): `DigiCertTrustedRootG4.crt` DER sha256
  `552f7bdcf1a7af9e6ce672017f4f12abf77240c78e761ac203d1d9d20ac89988`, matched
  across (1) direct `cacerts.digicert.com`, (2) web.archive.org snapshot
  `20260910114405`, (3) the OS trust store (`/etc/ssl/certs/DigiCert_Trusted_Root_G4.pem`).
- Remaining step: from a host with HTTP egress, record one token over the
  fixture digest, take the signer + intermediate from it, chain to Root G4,
  commit `config/anchors/digicert_ca.pem`, pin the signer DER sha256.

## Recorded fixture token (one-off, not capture)

- `tests/fixtures/anchor/tsa_fixture_t127.json`. Synthetic leaf preimage
  `"sportsedge t127 anchor fixture: synthetic leaf, not evidence"` →
  leaf `b82880f6…4384f` → Merkle root
  `bfcccfda9a510b4babe4c26a3fccc099a929bb8545fd7652dbe5163d94ba9d3b`.
- One request (`openssl ts -query -sha256 -cert`, with nonce) posted by hand to
  `https://freetsa.org/tsr` at 2026-10-14T02:48:21Z; genTime 02:48:22Z.
  Request sha256 `1a6678cf…06f30`, token sha256 `56771511…dedbc0`.
- This used the openssl CLI out-of-band, NOT `tsa_stamp` (which still refuses:
  capture off). The digest is synthetic and covers no evidence; it is
  admissible nowhere. Tests verify it fully offline with a fixed verifier clock.
