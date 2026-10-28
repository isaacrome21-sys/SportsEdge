# AMENDMENT 1 — EVALUATOR PIN — NFL Team Totals Forward Test V1

New file. No frozen text is edited. This amendment supersedes by
reference only, under preregistration §11 ("Frozen text is never
edited; amendments supersede by reference").

**Status: DRAFT — prepared for independent review. This amendment
takes effect only at the merge of the pull request that carries
it.** The sequencing is the freeze's own (the lesson of the NBA
props V2 quarantine, recorded in the FREEZE_RECORD): independent
review closes on the carrying PR's exact head BEFORE the merge
records the pin. Before that merge, the evaluator pin remains
PENDING, the §6 metric bar below stands in full, and the
preregistration's §4 no-interim-looks rule binds. This amendment
executes no freeze act, starts no clock, and computes no §6 metric.

## Authority

The FREEZE_RECORD (`FREEZE_RECORD.md`, sha256
`18036772e0d468ecd4757899163e7de4476c37f647eba2cc2f545fc8c3c23393`)
closed its pins table with one open item:

> **Evaluator pin: PENDING.** No §6 metric may be computed until
> the family evaluator is pinned by amendment; the
> preregistration's §4 no-interim-looks rule binds in the
> meantime. The run records carry every input a pinned evaluator
> needs, so pinning it later rewrites nothing.

Preregistration §11 fixes "the engine, runner, history-store pins,
pick rule, and evaluator" by sha256. This amendment supplies the
evaluator pin — the one §11 item the freeze act left open — and
changes nothing else.

## The pin

- **Evaluator:** the settlement code path of the frozen runner —
  `evaluate_close` in `sportsedge/nfl_team_total_runner.py`
  (`NFL_TEAM_TOTAL_RUNNER_V1`), together with the module
  constants it executes under (`CLOSE_WINDOW_S = 3600`,
  `CLOSE_PAIR_SPAN_S = 150`) and the disposition vocabulary it
  emits (`CLOSE_DISPOSITIONS`).
- **Path:** `sportsedge/nfl_team_total_runner.py`
- **sha256:**
  `076da740f5ac0517bbe2f52b28decf77d9923226c51a8228ff5e57b4b14f323e`

These are the same bytes the FREEZE_RECORD already pins as the
runner. This amendment pins them a second time, under the
evaluator heading of preregistration §11, because the two roles
are distinct in the frozen text: the runner pin binds the pricing
instrument (§11–§12 hard gate); this pin binds the evaluation
instrument. No code is moved, extracted, copied, or restructured
by this amendment — the evaluator is pinned where the freeze act
built it.

What the pinned evaluator does (preregistration §7, §8, §3):
given a committed entry record and every paired capture for its
team-game after ENTRY, `evaluate_close` attaches the valid close
(the last paired capture before kickoff whose earliest side quote
is no more than 60:00 before kickoff), assigns exactly one
disposition per row — `READABLE`, `LINE_MOVED` (with the NFL
props v1.1 favorable/adverse direction), `NO_CLOSE_ROW`,
`CLOSE_SINGLE_SIDED`, `CLOSE_NOT_PREKICKOFF`, `CLOSE_STALE`,
`PAIR_SPAN_EXCEEDED` — and records the settlement state (`VOID`,
`RESULT_UNAVAILABLE`, `GRADED`, push). Every §6 leg's row set is
wholly determined by these dispositions: a row whose close fails
validity is excluded from §6a–§6d before any moved classification
(§6, §7), and the moved-row rules read the `LINE_MOVED`
dispositions and their directions. Pinning this code path pins
the substrate every §6 number is computed over.

## Identification record (how the evaluator was identified)

- The preregistration names **no separate evaluator file**. §11
  lists the evaluator among the sha256-fixed items without a
  path; the FREEZE_RECORD's PENDING note names none either.
- **No separate evaluator module exists on main.** There is no
  `eval_nfl_team_totals*` file in `sportsedge/` or in this
  package; the only evaluation-side code path in the frozen
  package is `evaluate_close` and its module.
- The generic framework evaluator
  (`sportsedge/forward_validation/core.py`) is **not** this
  family's evaluator: the frozen framework config's own
  `capture_note` states the verdict test is the preregistration's
  four-leg test "not the framework's CLV-only default", and
  `core.py` implements that different architecture (no §6a/§6b
  ΔMAE legs, no moved-row sign test, no §9 seeded interval at
  1 − α/k). Pinning it would silently substitute a different
  test — a frozen-term change this amendment does not make.
- The driver (`sportsedge/nfl_team_total_driver.py`, PR #2879)
  is not part of the freeze pin set, computes no §6 metric, and
  is not pinned here; it reaches the evaluator only by calling
  the pinned module's `evaluate_close`.

If a future §6 computation artifact is ever built as a separate
module, it is a new artifact: it enters this test only by a
further amendment pinning its own sha256 before any metric it
emits may count. This amendment neither builds nor pre-approves
one.

## No frozen term changes

This amendment changes **no** frozen term, threshold, rule, or
byte. Re-verified against the FREEZE_RECORD pins at preparation
(main `d7a8b1938`), every value identical:

| Artifact | sha256 |
|---|---|
| Engine `sportsedge/nfl_team_total_dist.py` | `50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27` |
| Runner / evaluator `sportsedge/nfl_team_total_runner.py` | `076da740f5ac0517bbe2f52b28decf77d9923226c51a8228ff5e57b4b14f323e` |
| Framework config `sportsedge/forward_validation/configs/nfl_team_total.json` | `4c5d7afbfe97d0c5f48644b7fe36c2f7666fba6caf10421f16e3a516485aa3d7` |
| Preregistration (frozen) | `83f25f0e92c3ea39c8b18e194ce5743ceff6b595dc7dcb342175a57e46743581` |
| FREEZE_RECORD | `18036772e0d468ecd4757899163e7de4476c37f647eba2cc2f545fc8c3c23393` |
| Engine tests `tests/test_nfl_team_total_dist.py` | `6a23308516832507cccce36cc056e75fc9ebaca66af313e14d723e189fb4c91a` |
| Runner tests `tests/test_nfl_team_total_runner.py` | `e3dd97d83c381d513bbec25e5f5ebf506207f97f5818efedb954b91496aed922` |
| Lane A `artifacts/free_models.py` | `a8abf4606acafd2405ec037ea3bf69f1a6a5168baa4750631cc0fbebcece1fa3` |
| Lane A root shim `free_models.py` | `9160bbd3fd02147875942a709d2793e001281886a0969758acbcfdadf4356f67` |

Unchanged in particular: the §5 pick rule (±2.0), the §4 gates
(≥4 full slates, ≥150 priced rows with valid close pairing, ≥40
distinct games, ≥50 picked rows), the §9 intervals (game-cluster
bootstrap, 10,000 resamples, seed 20261028 binding, k = 11 as
recorded at the freeze, larger k at review governs), the §7 close
rule, and both refusal/disposition vocabularies. The config's
`status` remains FROZEN and its `model_version` pin string is
untouched.

## Effect on the §6 metric bar

The FREEZE_RECORD's bar — "No §6 metric may be computed until
the family evaluator is pinned by amendment" — is lifted **only
by this pin and only once this amendment is itself governed**:
independent review closed on the carrying PR's exact head, then
that PR merged to main. The merge is the recording act, exactly
as the freeze-act merge was. Until then the bar stands.

## Effective scope once the pin is recorded

- §6 metrics may be computed only on **counted rows**: rows in
  run records written by the pinned runner whose records prove
  the frozen hashes (preregistration §11), on or after the first
  counted slate — **the first NFL slate priced by the pinned
  runner after the freeze-act merge**, as instantiated in the
  FREEZE_RECORD. Rows priced before the freeze-act merge never
  count; there is no backfill, and no §6 metric is computed on
  any forward row before the first counted slate.
- The single verdict review is unchanged (§4): one review, at
  the first slate close where all gates are met; no interim
  looks at the primary metrics before that point; operational
  monitoring (capture, refusal, and missing-offer counts) remains
  the only permitted pre-review reporting.
- A verdict under this test changes no registration or
  eligibility by itself and creates no PLAY (§10).

## Pin enforcement

`tests/test_nfl_team_total_evaluator_pin.py` (new, carried by
the same PR) binds this document, the evaluator module's bytes,
the frozen disposition vocabulary and close constants, and the
re-verified frozen hashes above. If the evaluator module's bytes
ever drift from the pinned sha256, the test fails and this pin
is void until re-struck by a further amendment under a new
version — never by editing this file or the frozen text.

*Amendment 1 prepared Oct 28, 2026 (prep only — the pin is
recorded at the merge of the carrying pull request, after
independent exact-head review).*
