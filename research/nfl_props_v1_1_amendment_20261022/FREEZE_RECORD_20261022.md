# FREEZE RECORD — NFL props v1.1 moved-line amendment

**Frozen at:** 2026-10-22 21:25:35 CDT (2026-10-23T02:25:35Z), by Rocky (Muse).
**Authority:** Owner ruling #1, 2026-10-22 (Isaac A. Rome), as refined by the owner the
same evening (moved bucket + one-sided sign test at α = 0.05 + LOW_COVERAGE floor).
Owner authorized this freeze on 2026-10-22 after independent re-review cleared the package.
**Deadline met:** freeze precedes Sun 2026-10-25 12:00 CT, per §1 of the amendment.

## Package (sha256 in SPEC_HASHES.txt, beside this record)
- `PREREG_NFL_PROPS_V1_1_MOVED_LINE_AMENDMENT_DRAFT.md` — 024c71dc6670fd1cdec23aa6b6d37cb66ac26890c5826fed7d0a66aac82e9fdf
- `nfl_props_v1_1.py` — 27abccd995eac35cfacf82a539fb0dde526c2182f0813937d81c2438962ac6b5
- `test_nfl_props_v1_1.py` — ad19336ab507ac15a111af4b4af8f9eb9a7677e2ceb2ad328ed70a2d5f701c19

## Provenance
- Cleared by independent re-review at commit `69274a7b9b650abb2ca03c191731eb08b0b64c71`
  (branch `grok/nfl-props-v1-1-moved-line-amendment-20261022`): the reason-ordering
  bypass is closed; adversarial cases (mixed captures, close exactly at kickoff,
  close exactly 60:00 prior, timezone tricks) fail as designed; v1 dirs byte-identical.
- Freeze delta vs the cleared commit (owner-directed minor notes from that review):
  (1) prereg clause — a later non-qualifying close (e.g. one-sided) is ignored for
  direction and does not displace the latest qualifying close;
  (2) an assert in `annotate_moved` rejecting a row labeled LINE_MOVED that also has
  a two-sided close at the entry line (inconsistent record; unmodified v1 cannot
  produce one — guards hand-edited records);
  (3) FROZEN status markers + this record + SPEC_HASHES.txt.
- Verification of the delta (Rocky, at freeze): amendment test suite 29 passed;
  adversarial probe of the new assert — fires on the inconsistent record, and a
  genuine moved row still classifies LINE_MOVED with correct direction.

## Effect
- Governs rows whose kickoff is strictly after the freeze timestamp. First v1.1
  slate: NFL Week 7, Sunday 2026-10-25. The 2026-10-22 slate stays scored under
  v1 exactly as recorded; the v1 documents, pricers and scorers are untouched.
- The merge of this branch follows the standard sequence (it queues behind
  PR #2484, whose branch this package was built on). The freeze fixes the version
  independent of the merge; Sunday's scoring run must execute the pinned module
  above and record its sha256 in the run record as proof.
