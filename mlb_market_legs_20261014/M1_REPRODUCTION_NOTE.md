# M1 Reproduction Note — verification precondition for M2/M4

The M2 and M4 specs (§1 of each) require, before any new number is
reported, proof that the Lane A means produced by
`artifacts/free_models.py` at this lane's pin
(`2a713380c7d49733577c238a126f487382634040`) are the same means the M1
moneyline evaluation measured at its pin
(`655715907d101052bfc7cb3357f1442db82d8d8b`). The file changed between
the two pins — outside the Lane A path, per the diff — but the lane
treats the reproduction, not the diff, as the proof.

**Method:** `scripts/eval_mlb_lane_a_vs_close.py` (copied verbatim
from branch `research/mlb-lane-a-evaluation-20261013` @ `a5f605309`)
was executed from this branch's tree, so it loaded this tree's
`artifacts/free_models.py`, against the manifested corpus
(SHA-256 `3f952fd0…`, see `DATASET_MANIFEST.md`).

**Result: exact reproduction.** Every published M1 number matched to
full float precision, except `generated_at`:

| Quantity | M1 published | Re-run on this pin |
|---|---|---|
| matched n | 10,237 | 10,237 |
| Brier model | 0.247856 | 0.247856 (identical float) |
| Brier market | 0.236332 | 0.236332 (identical float) |
| Log loss model | 0.688863 | 0.688863 (identical float) |
| Log loss market | 0.663222 | 0.663222 (identical float) |
| ΔBrier | +0.011523 [+0.007548, +0.016433] | identical |
| ΔLogLoss | +0.025641 [+0.015651, +0.038144] | identical |
| Exclusion counts / book usage | as published | identical |

The re-run's full output is filed as `M1_REPRODUCTION_RESULTS.json`
in this folder. (That JSON's embedded `model_identity.main_commit`
string names the original M1 pin because the evaluator script is
verbatim; the execution tree for the re-run was this branch's pin,
`2a713380c`, as recorded here.)
