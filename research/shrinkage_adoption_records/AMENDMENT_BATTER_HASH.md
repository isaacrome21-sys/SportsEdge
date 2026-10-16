# AMENDMENT — Batter Props Spec-Hash Token (formal amendment for the published record)

- **Filed:** 2026-10-15 (America/Chicago), at repository
  publication of the shrinkage adoption records package
  (`research/shrinkage_adoption_records/`), so that the batter
  family's audit chain verifies end-to-end from identifiable
  records.
- **Companion record:** the Model Fix Lane's own pre-scoring
  amendment, `specs/AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md`
  (included in this package), filed 2026-10-14 before any 2026
  outcome was scored, binned, or inspected for this family.
  This amendment ratifies that record for the published
  package; it does not replace it.

## The defect

The `PREREG_BATTER_PROPS.md` line in `specs/SPEC_HASHES.txt`
carries a **55-character token**. A SHA-256 hex digest is 64
characters. The token is defective as recorded:

Recorded token in specs/SPEC_HASHES.txt (defective, 55 characters): `58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1a65e3b`

## The true hash

True SHA-256 of specs/PREREG_BATTER_PROPS.md (recomputed 2026-10-15): `58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b`

Recomputed at publication with `sha256sum` from the file
bytes as published in this package; it agrees with the value
the lane's evaluator asserted at runtime and with the hash
recorded in
`results/challenger_batter_props_results.json` (`prereg.sha256`).

The defective token equals the true hash with exactly 9
characters deleted at offset 49 (0-based): the true hash is
`true[:49]` + `d8e08e1d1` + `true[58:]`; the recorded token is
`true[:49]` + `true[58:]`. No other characters differ. The
preregistration file itself is intact and byte-unchanged —
only the lock-file token was mangled.

## What the lane did (pre-scoring, on the record)

The lane caught the defect **before scoring**, filed
`specs/AMENDMENT_BATTER_PROPS_SPEC_HASH_RECORD.md`, left
`SPEC_HASHES.txt` unedited, and locked the batter evaluator
on the true computed hash (asserted at runtime against the
file bytes). The results JSON records the chain explicitly
(`prereg.spec_hashes_record`): the recorded token, its length
(55), `record_matches_true_sha256: false`, and the amendment
pointer.

## Effect of this amendment

- For verification of the batter preregistration **going
  forward**, the true SHA-256 above governs. Any verifier
  checking `specs/PREREG_BATTER_PROPS.md` against
  `specs/SPEC_HASHES.txt` must apply this amendment (and the
  lane's) to the batter line; the other four lines verify
  directly.
- **History is not rewritten.** `SPEC_HASHES.txt` ships in
  this package byte-identical to the lane's locked record,
  defective token included. This amendment supersedes the
  token *for verification purposes only*; it does not edit,
  repair, or re-issue the lock file.
- **Scope:** verification bookkeeping only. No preregistered
  construction, constant, split, metric, or gate is changed
  by this amendment, and none was changed by the lane's.

Executable check: `tests/test_shrinkage_adoption_records.py`
recomputes every hash in this package and asserts this exact
amendment chain (token length, deletion identity, true hash,
results-JSON record).
