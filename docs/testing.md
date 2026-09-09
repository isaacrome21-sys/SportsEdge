# Local validation

Use Python 3.12 and an isolated environment:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest -q tests
.venv/bin/python scripts/audit_workflow_script_refs.py
```

The suite contains both unittest classes and pytest functions/fixtures; use pytest for full discovery. The control plane launches Python lanes with the interpreter running the control plane so they share its installed dependencies.

Production floor policy and readiness use the same resolver. Eligible candidates resolve a floor before model execution. A completed lane must produce a fresh, readable card; an all-blocked card is reported as blocked even when the process exits successfully. Process execution, priced model rows, and official bets are distinct fields.

Provenance-bearing bundles require retention of both referenced manifest and floor commits, including their trees/blobs, for the lifetime of the bundle. Use the required merge-commit method; do not squash or rebase recorded identities. Branch deletion alone preserves verifiability when retained history still reaches both commits. History pruning, migration, or incomplete checkouts that lose required objects must yield PROVENANCE_UNRESOLVABLE. This retention requirement does not assert that a bundle has passed verification.
