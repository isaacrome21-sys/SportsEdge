# Shrinkage Adoption Records — 10/3/1 Challengers

**State, plainly:** the 14 challengers recorded here (batter
×10, pitcher ×3, CFB QB ×1) are **RESEARCH challengers only**.
They are **NOT production** models. They were **NOT
market-scored** — no sportsbook price appears as a scored arm
in any evaluation in this package; every results JSON carries
the label *"NOT a market verdict, NOT validation, NOT a
promotion input."* Owner ruling (Oct 15, 2026): the 10/3/1
parameters are adopted as research challengers; **adoption
into production and any promotion are HELD** pending owner
certification from these identifiable records. Evaluation
code is not a substitute for measured results — the measured
results are the JSONs in `results/`, and this package exists
so they can be certified, reproduced, and audited as records.

## Contents

- `RECORDS.md` — the adoption records package: all 14
  challengers, constructions, preregistration hashes, results,
  gate outcomes (all PASS as recorded against FROZEN + B1 +
  B2), and the discrepancy register D1–D5. **D2 is RESOLVED**
  (see below).
- `D2_RECONCILIATION.md` — the D2 reconciliation: pitcher B2
  Outs CRPS **2.1705 is correct** under the preregistered B2
  definition, reproduced three independent ways; the parallel
  figure 2.0267 is unattributable to any persisted
  computation and is treated as withdrawn-by-unverifiability.
- `AMENDMENT_BATTER_HASH.md` — formal amendment governing the
  defective batter token (D1) in `SPEC_HASHES.txt`.
- `REPORT.md` — the Model Fix Lane's own report (Oct 14,
  2026), the prose source the records were audited against.
- `specs/` — the lane's preregistration lock context, copied
  **byte-identical and unedited**: all five preregistrations
  (batter, pitcher, CFB QB, plus F5 and first-inning — present
  because `SPEC_HASHES.txt` locks all five and ships as-is),
  the lane's two amendments, and `SPEC_HASHES.txt` itself.
- `results/` — the measured results for the three adoption
  families: batter results + parity + verification JSONs,
  pitcher results + verification JSON, CFB QB results, and
  the boxscore acquisition summary.
- `scripts/` — the three family evaluators
  (`eval_challenger_batter_props.py`,
  `eval_challenger_pitcher_undercard.py`,
  `eval_challenger_cfb_qb.py`) plus the acquisition/derivation
  scripts their records depend on. Source lane:
  `~/workspace/sportsedge/model_fix_20261014/` (Oct 14, 2026).

Scoping note: F5 and first-inning challengers failed their
gates (KEEP FROZEN) and are not adoption items; their specs
ship here only as part of the `SPEC_HASHES.txt` lock context.
Their evaluators and full results remain in the lane record,
not in this package.

## Known record items (all carried openly in `RECORDS.md` §5)

- **D1** — batter token in `SPEC_HASHES.txt` is a defective
  55-character string (9 chars deleted at offset 49).
  Governed by `AMENDMENT_BATTER_HASH.md`; the file ships
  as-is. Batter family records are therefore RECORD_PARTIAL;
  pitcher ×3 and CFB QB ×1 are RECORD_COMPLETE.
- **D2** — RESOLVED. 2.1705 stands; 2.0267 unattributable.
- **D3** — Total Bases ≡ Hits at the 0.5 line: the batter
  "10" is 9 distinct evaluations + 1 duplicate-form stat.
- **D4** — the CFB verdict rests on 417 of 1,695 candidate
  team-games (70.3% ROLE_NOT_MATERIALIZED).
- **D5** — 2026 B2 baselines are weaker than their 2024–25
  selves; the context travels with the paired CIs.

## Verify

```
python -m pytest tests/test_shrinkage_adoption_records.py
```

The test recomputes every preregistration hash in this
package, verifies the D1 amendment chain, and cross-checks
every number `RECORDS.md` claims for all 14 challengers
(scores, paired deltas, CIs, sample sizes, gate verdicts)
against the `results/` JSONs — reproducibility as an
executable check, not prose.
