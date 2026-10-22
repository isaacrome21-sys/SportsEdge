# t130 anchor nonce hardening + #2219 independent verification (2026-10-13)

Base: `grok/t128-anchor-admission-composed-20261013` @ 73c9dcde. capture_active / admission_active stay **false**. No real certificates or tokens were created; all new tests use throwaway openssl TEST CAs in tmp dirs. FreeTSA policy OID (1.2.3.4.1) and TSA-name hash were parsed from the real t127 fixture token already in the repo.

## #2219 findings on 73c9dcde
| Check | Result on 73c9dcde | t130 |
|---|---|---|
| Pin targets the true CMS signer cert | PASS (`cms -verify -signer`, exactly one signer) | kept; signer sha now always returned |
| Chain validates to pinned root at genTime | PASS (`ts -verify -attime -CAfile` provider bundle only) | kept |
| Nonce bound to exact request DER, stored hash | **FAIL**: request DER required by the configured wrapper but never recorded; no request-DER hash, no single-use; a replayed bundle re-admits; `admit_quorum` admits nonce-less tokens | persisted nonce ledger (request sha256 + issued_at), single-use consume, nonce required + echoed, reqPolicy matched |
| Response matches request policy | **GAP**: no policy pin per provider | per-provider policy OID pin (required for `pinned`), TSA-name pin, request policy match |
| Quorum = two independent providers | **FAIL**: counted provider ids only; one signer under two ids admitted | quorum needs distinct providers AND distinct signer certs; config refuses a signer pin shared by two providers |

Reproduced on 73c9dcde with test CAs: alias one-signer/two-ids -> `admitted`; replay same bundle -> `admitted`; nonce-less tokens -> `admitted` (primitive path).

## Registration list (new/changed paths)
- `sportsedge/evidence_anchor.py` (changed)
- `sportsedge/evidence_lock_store.py` (changed)
- `config/anchors/anchor_config_v1.json` (changed: policy_oids, tsa_name_sha256, nonce_ledger, max_response_window_s)
- `tests/test_evidence_anchor_nonce_hardening_20261013.py` (new)
- `tests/test_evidence_anchor_wiring_20261013.py`, `tests/test_evidence_anchor_pinning_20261013.py` (changed: stricter reasons/pins)
- `docs/ANCHOR_NONCE_HARDENING_T130_20261013.md` (new)
- runtime state path (not committed): `state/anchors/tsa_nonce_ledger.jsonl`
