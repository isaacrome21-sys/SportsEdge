# MLB pitcher-K Statcast skill source v1

Status: **source observation only; not a model input; not deployed for pricing**.

The existing daily Statcast collector already persists immutable 30-day pitcher
snapshots to the `data` branch before downstream use. This change adds
additive pitcher observations needed by the preregistered pitcher-K candidate:

- whiffs and swings, with `whiff_rate = whiffs / swings`;
- out-of-zone pitches and chases, with `chase_rate = chases / out-of-zone pitches`;
- observed pitcher throwing hand when the window is internally consistent.

Swing descriptions are frozen to the Statcast descriptions enumerated in
`sportsedge/statcast_daily_source.py`. Whiffs are swinging strikes,
swinging-strike blocks, and missed bunts. Out-of-zone pitches are Statcast zone
codes 11–14. A chase is a swing on one of those out-of-zone pitches.

These fields are appended to the same strict-prior 30-day source snapshot. They
do not create or modify Model_P, do not choose any weight or probability
formula, and do not promote a card row. The composite pitcher-K candidate stays
evaluation-closed until these observations are durably captured and bound under
an untouched PIT evaluation protocol.


## Forward-evidence provenance guard

Durable Statcast evidence is eligible for the later untouched evaluation only
when the persisted run contains `provenance.json` proving
`ref = refs/heads/main`, `head_branch = main`, and
`eligible_for_forward_evaluation = true`.

Run `37449141740` is explicitly **ineligible** for evaluation evidence. It was
triggered by a push to `research/mlb-pitcher-k-statcast-skill-source-v1` at
head `84e33e7ae1f1ea9f970f7458e9a974eb5eafd7ec` before the source change was
merged. The immutable data-branch snapshot is not deleted or rewritten; it is
simply excluded. A post-merge main run must create the first eligible skill
snapshot.
