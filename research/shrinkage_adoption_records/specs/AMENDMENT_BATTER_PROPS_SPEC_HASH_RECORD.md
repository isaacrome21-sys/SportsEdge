# AMENDMENT — Batter Props: SPEC_HASHES.txt record defect (filed before any scoring)

- **Date:** 2026-10-14 (America/Chicago, evening), filed by the Model
  Fix Lane Child A evaluator BEFORE any 2026 outcome was scored,
  binned, or inspected for this family.
- **What was found:** the `PREREG_BATTER_PROPS.md` line in
  `SPEC_HASHES.txt` carries a 55-character token:
  `58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1a65e3b`.
  A SHA-256 hex digest is 64 characters. The token equals the file's
  true SHA-256 with 9 characters deleted at offset 49
  (true: `...a3b6d1` + `d8e08e1d1` + `a65e3b`; recorded token omits
  the middle segment). The other four lines in SPEC_HASHES.txt are
  full 64-character digests, and the PREREG_PITCHER_UNDERCARD line
  matches its file's computed SHA-256 exactly.
- **True hash of the preregistration as written:**
  `58a7977c6cce4be3bf601f4e9e9574e85c2bc68a8f1a3b6d1d8e08e1d1a65e3b`
  (computed by sha256sum and by the evaluator at runtime).
- **Deviation taken:** the batter evaluator locks on the true
  computed SHA-256 above (asserted at runtime against the file
  bytes) and records the SPEC_HASHES.txt token and its defective
  status in the results JSON, instead of asserting membership in
  SPEC_HASHES.txt (which cannot pass for a 55-char token).
  `SPEC_HASHES.txt` itself is NOT edited by this lane — it is the
  coordinator's locked record; the defect is reported, not repaired
  in place.
- **Scope of the deviation:** verification bookkeeping only. No
  preregistered construction, constant, split, metric, or gate is
  changed. The preregistration file itself is byte-unchanged.
