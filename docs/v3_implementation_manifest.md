# V3 implementation manifest

Issue: #809

Implemented on a feature branch only; nothing in this manifest claims activation on `main`.

- `config/ev_tracker_policy_v3.json` — prospective suspension doctrine, K=3 recovery, anti-gaming inputs, no-authority boundaries.
- `config/ev_tracker_policy_manifest.json` — V3 active *if/when merged to evidence_ref*; V2 moved to superseded with immutable-history language.
- `config/ev_tracker_v3_activation.json` — n=0 activation disposition and no-backfill boundary.
- `config/ev_tracker_v3_quiescence_disposition.json` — recorded RESOLVED un-quiesce disposition, effective only after main activation.
- `config/nfl_confirmation_v3_suspension.json` — prospective NFL suspension eligibility; manual lanes cannot suspend; budget exhaustion is not outage.
- `sportsedge/ev_suspension_v3.py` — machine state/outage/recovery classifier.
- `scripts/ev_credential_health.py` — diagnostic-only pre-window credential health classifier.
- `scripts/ev_tracker_v3_gate.py` — ACTIVE-only evidence admission gate.
- `scripts/ev_tracker_v3_health_patch.py` — zero-credit/dead-key/401 false-green regression rule.
- `scripts/ev_v3_state.py` — append-only transition-boundary record builder.
- `.github/workflows/ev-v3-governance.yml` — hosted test workflow.
- `tests/test_ev_*v3*.py`, `tests/test_ev_credential_health.py`, `tests/test_nfl_confirmation_v3_suspension.py` — policy, outage, recovery, health, immutability and no-authority tests.
- `docs/public_repo_v3_pattern_adoptions.md` — public-repo adoption provenance rule; no third-party code copied in this change.

Remaining merge requirement: hosted checks and existing SportsEdge reconciliation/governance gates must pass on the exact PR head. No bypass.
