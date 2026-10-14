# Evidence anchor wiring & capture host config (t124)

2026-10-13 · Branch `grok/t124-anchor-wiring-20261013` · **Design approved, NOT activated**

## Owner decision (recorded)
Oct 13 2026, 8:23 PM CT, Isaac: *"Approve the anchor proposal: RFC 3161 (FreeTSA + DigiCert) plus OpenTimestamps, S3 Object Lock, VPS host."*
Scope: **design approval only.** Capture activation, admission activation, forward validation and eligibility each still need their own ruling. Recorded on #2090 and in `config/anchors/anchor_config_v1.json` → `owner_decision`.

## What this branch does
| Piece | File | State |
|---|---|---|
| Approved anchor IDs loaded only from owner-decision config (ids must be listed in `owner_decision.anchor_ids`) | `sportsedge/evidence_anchor.py`, `config/anchors/anchor_config_v1.json` | `anchor:rfc3161+ots:v1` approved |
| Activation flags `capture_active`, `admission_active` | same config | **false**. Default-path `admit`/`admit_quorum` return `admission_not_activated`; `tsa_stamp` refuses with `capture not activated` even with `allow_network=True` |
| Configurable TSA providers (FreeTSA, DigiCert) | config `tsa_providers` | **unpinned**: no CA bundle or signer pin committed, so `provider_trust` refuses them |
| RFC 3161 verification | `tsa_verify` | signature + chain to pinned CA (timeStamping EKU), signer DER SHA-256 pin, SHA-256 message imprint == batch root, optional request binding (imprint + nonce via `-queryfile`), status Granted, genTime ≤ now+skew, every embedded cert valid at genTime |
| Dual-TSA quorum | `admit_quorum` | ≥2 distinct providers, each verified only against its own CA/pins; two tokens from one TSA count once; quorum<2 refused; LATEST quorum genTime must be ≤ cutoff − margin |
| OpenTimestamps proof verification | `ots_verify` | full proof-tree parse (append/prepend/sha256/sha1/ripemd160/reverse/hexlify, forks), pending + Bitcoin attestations; Bitcoin confirmed only against a caller-supplied 80-byte header whose merkle root equals the commitment. Secondary; never gates admission. `ots_stamp` still unwired |
| S3 Object Lock writer interface | `sportsedge/evidence_lock_store.py` | `ObjectLockWriter` protocol; `S3ObjectLockWriter` (injected boto3-style client, COMPLIANCE only, ≥3650 days, ChecksumSHA256, `IfNoneMatch=*`, VersionId required, bucket lock+versioning check) refuses unless `enabled=True`; `InMemoryLockWriter` test double |

No repo code imports either module; no workflow references them. Tests use throwaway openssl test CAs and synthetic OTS/header bytes only. No live TSA calls, no secrets.

## Host config (VPS, proposed)
- Hetzner CX22 or equivalent; Debian stable; unattended-upgrades; SSH keys only.
- `chrony` with NTS sources (e.g. `time.cloudflare.com nts`, `nts.netnod.se nts`); alert if `chronyc tracking` offset > 1 s. Host clock is advisory: evidence time = TSA genTime; skew vs genTime > `max_clock_skew_s` (30 s) rejects.
- systemd timer per capture lane (≤15 min in pregame windows), runs as an unprivileged user, repo checkout at a pinned SHA.
- Env (from proposal §5): `SE_ANCHOR_ID`, `SE_TSA_URLS`, `SE_TSA_CA_BUNDLE`, `SE_EVIDENCE_BUCKET`, `SE_EVIDENCE_LOCK_MODE=COMPLIANCE`, `SE_EVIDENCE_RETENTION_DAYS=3650`, `SE_CAPTURE_HOST_ID=vps-capture-01`, `SE_CAPTURE_CLOCK_SOURCE=system`, `SE_CAPTURE_MODE=shadow`, `SE_FORWARD_VALIDATION_ACTIVE=0`.
- AWS credentials: IAM user/role limited to `s3:PutObject`, `s3:PutObjectRetention`, `s3:GetObject*`, `s3:GetBucketObjectLockConfiguration`, `s3:GetBucketVersioning` on the one bucket; **no** `s3:DeleteObject*`, `s3:BypassGovernanceRetention`, `s3:PutBucketObjectLockConfiguration`. Stored in the host secret store / systemd `LoadCredential=`, never in the repo.
- GitHub Actions: watchdog only (`17,47 * * * *`), alerts if no anchored batch in window; daily `ots upgrade` job.

## Remaining steps
**Owner (Isaac)**
1. Provision the VPS (above) and give ChatGPT/Grok a deploy path.
2. Open AWS account; create `sportsedge-evidence-locked` with Object Lock enabled at creation + versioning, default retention COMPLIANCE 3650 d (irreversible). Prove a test object cannot be deleted.
3. Create scoped IAM credentials; store as host secrets (and, if CI needs read-only verify, as GitHub Actions secrets). Never commit.
4. Create `SportsEdge-anchors` repo (protected branch, signed commits) if still wanted.
5. Separate rulings later: shadow capture on (`capture_active`), admission on (`admission_active`), forward validation.

**ChatGPT (integration)**
1. Independent review of this branch (quorum semantics, cert-validity check, OTS parser, lock-writer contract).
2. Pin TSA trust: fetch FreeTSA and DigiCert CA bundles + signer certs over two independent networks, commit `config/anchors/{freetsa,digicert}_ca.pem`, record DER SHA-256 pins, set `status: pinned`. Add one recorded real `.tsr` per TSA as a fixture (recorded once off-CI, verified offline).
3. CI wiring: run the anchor tests in hosted CI (requires `openssl` ≥3.0 on runner); no network in tests.
4. Wire `admit_quorum` into the pinned Form 2 loader / QB archive / receipt journal only behind `admission_active` (stays false).
5. Watchdog + `ots-upgrade` workflows (after VPS exists).
6. Register files below and rerun freeze reconciliation.

## Files needing registration (`config/reconciliation_coverage_v1.json` / freeze inventory)
- `sportsedge/evidence_anchor.py` (modified from 02ee0b66)
- `sportsedge/evidence_lock_store.py` (new)
- `config/anchors/anchor_config_v1.json` (new)
- `tests/test_evidence_anchor_20261013.py` (modified)
- `tests/test_evidence_anchor_wiring_20261013.py` (new)
- `docs/ANCHOR_WIRING_AND_HOST_CONFIG_20261013.md` (new)
