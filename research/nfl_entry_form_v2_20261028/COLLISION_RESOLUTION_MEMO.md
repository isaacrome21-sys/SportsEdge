# COLLISION RESOLUTION MEMO — NFL_ENTRY_FORM_V2 freeze act registry gate

**Status: ANALYSIS + RECOMMENDATION ONLY.** This memo authorizes
nothing, freezes nothing, installs no config, and changes no existing
config's status. It resolves, on paper, the REGISTRY GATE item that
`FREEZE_ACT_CHECKLIST.md` (PR #2884) recorded as blocking for the
NFL_ENTRY_FORM_V2 freeze act. Evidence state: every factual claim
below was re-derived by the memo's author on main `c04e55052`
(Oct 28, 2026) — file bytes, repo-wide reference search, git history
via the GitHub API, and live probes of the audit code. Nothing rests
on the freeze package's own say-so alone.

## 1. The blocker, precisely

The forward-validation registry admits exactly one config per
(sport, market). The enforcement is
`scripts/audit_cross_sport_accuracy_readiness.py::accuracy_readiness()`:
it globs `sportsedge/forward_validation/configs/*.json`, derives each
config's state from its `status` string, and raises
`AuditRefusal("DUPLICATE_FORWARD_MARKET_CONFIG:{sport}:{market}")`
when a second config claims a key already claimed. (NFL, SPREAD) and
(NFL, TOTAL) are claimed by the FREE_MODELS_GAME draft registrations
`sportsedge/forward_validation/configs/nfl_spread.json` and
`sportsedge/forward_validation/configs/nfl_total.json`, so the EFV2
config (markets SPREAD + TOTAL) cannot be installed beside them.

## 2. What the incumbent configs actually are — the evidence

**They are un-frozen drafts with no counted history, no frozen
terms, and no live consumers.** Each element, with its source:

1. **Status on their face.** Both carry
   `status: "DRAFT — NOT FROZEN"`, `engine_id: "FREE_MODELS_GAME"`,
   `model_version: "FREE_MODELS_GAME:LANE_A_INDEPENDENT"`, and a
   `prereg_draft` pointer (no `prereg` / `prereg_sha256` — the
   audit's DRAFT branch forbids a draft from claiming a frozen pin).
   sha256 on current main: `nfl_spread.json` =
   `0e25ee74c4b3b56d469b5d01ec965c829be7cd39a9c785576dfa6fc234707b66`;
   `nfl_total.json` =
   `bd18c77ff1c4854e9c7adaebd787529860d764cf04ea0b4de36ce71bf09da425`.
2. **Never modified since creation.** The GitHub API commit history
   for each file contains exactly one commit — `11d168ddd`
   (Oct 20, 2026, "Forward-validation program: evaluator framework +
   35 draft preregistrations + program map"). The bytes on main
   today are the original draft bytes; no status flip, no gate
   change, no freeze act was ever recorded against them.
3. **By their own terms, zero rows can have counted.** Their draft
   preregistrations (`research/forward_validation_program_20261020/
   drafts/PREREG_NFL_SPREAD_FORWARD_V1_DRAFT.md` and the TOTAL twin)
   open: "Status: DRAFT — NOT FROZEN, NOT IN FORCE… Freezing is the
   owner's act, per family. **No game, row, or slate counts toward
   this test before its freeze.**" Each config's `capture_note`
   repeats it: "Rows can accumulate from the first slate priced
   **after this preregistration is frozen**." No freeze ever
   occurred (no freeze record exists in the program directory —
   it holds only `PROGRAM.md` and `drafts/`), so the countable-row
   count under these registrations is zero by construction, not
   merely by observation.
4. **The program map says so, and contemplated exactly this.**
   `research/forward_validation_program_20261020/PROGRAM.md` §2:
   all 35 drafts are "DRAFT — NOT FROZEN, NOT IN FORCE. Freezing is
   the owner's act, per family; no game counts before its freeze."
   §1's list of frozen tests already in force does not include them.
   §4.2 records for the NFL free_models TOTAL draft that "the owner
   may legitimately leave it unfrozen and let LEVEL v2 be the
   totals path," and for MONEYLINE/SPREAD simply "owner freeze,
   then rows" — rows that never began.
5. **No run or verdict record cites them.** A repo-wide search for
   the config paths, the family name, and the model-version string
   finds exactly four kinds of reference: (a) the readiness audit's
   census (code, §3 below); (b) the dated snapshot
   `research/cross_sport_accuracy_readiness_20261021.json`, which
   lists both with `state: "DRAFT_NOT_FROZEN"`,
   `independent_model_accuracy_verdict:
   "NOT_EVALUATED_BY_THIS_AUDIT"`, `play_authority_from_config:
   false`; (c) their own draft documents; (d) the EFV2 freeze
   package naming them as this blocker. The framework evaluator
   stamps every verdict record with its config's sha256
   (`sportsedge/forward_validation/core.py::evaluate_family`); no
   record in the repo carries either sha256 from item 1.
6. **No code loads them.** `core.py` loads a single config by
   explicit path (`load_config`) and scores a caller-supplied
   config object (`evaluate_family`); nothing enumerates the
   configs directory to score drafts, and nothing references these
   two filenames outside item 5. The configs are evaluator
   *registrations*, not pricing inputs.
7. **Lane A is not a consumer.** `FREE_MODELS_GAME:LANE_A_INDEPENDENT`
   is Lane A's version string; Lane A prices from
   `artifacts/free_models.py`, which never reads these configs.
   Retiring the registrations cannot move card pricing, the frozen
   NFL team-totals §6b Lane A baseline (which pins the Lane A
   *files* by sha256, untouched here), or any other family's test.
   What the registrations governed was only a hypothetical future
   framework evaluation of Lane A rows under these drafts — an
   evaluation that, per item 3, could never have accrued a counted
   row while unfrozen.
8. **Scope is surgical.** FREE_MODELS_GAME holds eight other draft
   registrations (NFL moneyline; CFB moneyline/spread/total; MLB
   moneyline/run line/team totals/totals). Only the two NFL
   (SPREAD) and (TOTAL) registrations collide with EFV2. Nothing in
   this memo proposes touching the other eight, their drafts, or
   the FREE_MODELS_GAME engine.

## 3. How the uniqueness law works — and the probes

Three properties of the code as written decide which resolutions
are lawful:

- **Status vocabulary is closed.** `_status()` recognizes exactly
  three forms — `DRAFT … NOT FROZEN` (requires `prereg_draft`,
  forbids frozen pins), `FINAL-CANDIDATE … NOT FROZEN` (requires a
  pinned prereg), and `FROZEN …` (requires `prereg` +
  `prereg_sha256`) — and raises `UNKNOWN_CONFIG_STATUS:<file>` for
  anything else. There is **no RETIRED/WITHDRAWN status the audit
  accepts**: an in-place status flip to a tombstone string breaks
  every audit run (fail-closed) and both audit test suites
  (`tests/test_cross_sport_accuracy_readiness.py`,
  `tests/test_nba_v2_accuracy_readiness_bridge_20261026.py`). No CI
  workflow invokes the audit; those suites are its enforcement
  surface, and the freeze checklist already requires them green on
  the act's exact head.
- **The sole overlap exception cannot cover EFV2.** The
  duplicate check excuses only the NBA V2 source amendment: an
  `*_v2.json` twin of a FROZEN prior, in four named NBA player
  markets, with an *identical contract* outside
  status/prereg/pin/capture-note fields. EFV2 is a different
  engine, model version, family, and gate set — `same_contract`
  is unsatisfiable, by design ("No different engine, model,
  market, gate or threshold can hide behind a status change").
- **Removal is the registry's own deregistration mechanism.** The
  audit registers what the directory glob returns; a file that is
  not in the directory claims nothing, and `_status()` imposes no
  requirement on absent files (its prereg-existence checks bind
  only configs that are present). Deleting a never-frozen draft
  registration, with the deletion and its evidence recorded in a
  governed record, is therefore lawful under the code exactly as
  written — no loader or audit edit is needed.

**Probes run by the memo's author on main `c04e55052`** (audit
imported directly; working tree restored byte-identical after each
step, verified clean):

| Probe | Result |
|---|---|
| Baseline (47 configs) | PASS — NFL: 16 DRAFT + 1 FROZEN; canonical pointers spread → `nfl_spread.json`, total → `nfl_total.json`, both `RESEARCH_PRICED_NOT_VALIDATED` |
| + EFV2 config as-is (DRAFT status) | REFUSAL `DUPLICATE_FORWARD_MARKET_CONFIG:NFL:SPREAD` |
| + EFV2 config in freeze-act form (FROZEN status, `prereg` + `prereg_sha256`) | REFUSAL — identical; the collision is status-independent |
| − the two incumbents, + EFV2 in act form | **PASS** — 46 configs; NFL FROZEN 1 → 2; canonical pointers spread/total → `nfl_entry_form_v2.json`; readiness unchanged (`RESEARCH_PRICED_NOT_VALIDATED`); moneyline pointer untouched |

The act-form probe also re-verified the checklist's prereg pin
against live bytes: sha256 of `PREREG_FINAL.md` =
`cfc7047caa898e624c737d3fbf4fd35e2abe8dca638c7b312c4f193f53e098ea`,
matching `FREEZE_ACT_CHECKLIST.md` exactly.

## 4. Options

**Option A — Retire the two draft registrations inside the freeze
act's own PR, before the config flip (RECOMMENDED).** The act PR
first records the retirement (evidence + both config sha256s, in
the act's `FREEZE_RECORD.md` or a companion retirement record in
this directory) and deletes the two files; the same PR then
performs the checklist's config flip. Lawful per §3 (removal is
deregistration; the retired objects are drafts whose own terms
record zero countable rows, §2). Atomic: no state of main ever
holds both registrations or neither.

**Option B — Retire in a separate governed PR before the act.**
Equally lawful, and the fallback if reviewers want the retirement
reviewed on its own head. Costs: an extra merge cycle, and an
interval on main where (NFL, SPREAD) and (NFL, TOTAL) have **no**
forward-test registration (the readiness audit would report
`NO_FORWARD_TEST_CONFIG` for two priced canonical markets) — a
state Option A never creates. The checklist's own wording ("The
act must resolve the collision lawfully **before the flip**") is
satisfied by both; A satisfies it inside the act.

**Option C — Amend the audit to authorize a second overlap class.**
REJECTED. It contradicts the audit's stated design (the NBA V2
amendment is "the ONLY authorized overlapping registration"), it
is the "weakening the audit" route the checklist prohibits, and it
creates the exact hazard the one-config law exists to prevent:
`family_by_market` resolves a market to its *first* claimant, so
two live registrations for one key leave the canonical
forward-test pointer dependent on file-glob order — a silent
re-point risk for whichever family is named second. It also
requires code + test changes under their own governance for zero
benefit over A.

**Option D — Register EFV2 under dodged market keys.** REJECTED
outright: the checklist prohibits it by name, and it would falsify
the registration — EFV2's markets *are* SPREAD and TOTAL.

**Option E — Tombstone the incumbents in place (status flip to a
RETIRED string, markets stripped, or file emptied).** NOT LAWFUL
under the code as written: §3's closed status vocabulary refuses
any such file with `UNKNOWN_CONFIG_STATUS`, and a markets-stripped
or emptied file fails the audit's identity checks
(`CONFIG_IDENTITY_INVALID`). A tombstone that the registry can
read requires an audit code change — i.e., it collapses into
Option C. The governed *record* (Option A's retirement record)
carries the tombstone's information lawfully; the file itself
cannot.

**The counterfactual that bounds the recommendation.** Option A/B
lawfulness rests entirely on §2's evidence. Had the incumbents
carried counted rows or frozen terms, retiring them would orphan
a live verdict path, and neither option would be available: the
act would have to wait for that test's verdict/closure, or seek
an owner-ruled audit amendment (Option C) with the re-point
hazard accepted knowingly. That is not the case here — but the
act's retirement record must restate §2's evidence so the
precondition is auditable from the record itself.

## 5. Recommended path — the exact act sequence

Folded into the freeze act as the discharge of its REGISTRY GATE
item, in this order, all inside the act's one PR:

1. **Retirement step (first).** Add the retirement record to the
   act's `FREEZE_RECORD.md` (or a companion
   `REGISTRY_RETIREMENT_RECORD.md` in this directory): the §2
   evidence restated, both incumbent sha256s (item 1 of §2), and
   the statement that the two draft preregistrations remain in
   `research/forward_validation_program_20261020/drafts/` as
   historical drafts, byte-untouched — the record, not an edit to
   the drafts, carries the supersession. Delete
   `sportsedge/forward_validation/configs/nfl_spread.json` and
   `sportsedge/forward_validation/configs/nfl_total.json`.
2. **Config flip (checklist, unchanged).** Install
   `sportsedge/forward_validation/configs/nfl_entry_form_v2.json`
   from this package's `CONFIG_DRAFT.json` with exactly the two
   checklist changes (FROZEN status string; `prereg` +
   `prereg_sha256` = the `cfc7047c…` pin re-verified on the act's
   head); `model_version` and every gate value byte-identical.
3. **Registry verification on the act's exact head.** Run the
   readiness audit and both audit test suites: the audit must
   PASS with 46 configs and NFL FROZEN = 2; the canonical
   pointers for (NFL, spread) and (NFL, total) must name
   `nfl_entry_form_v2.json`, and (NFL, moneyline) must still name
   `nfl_moneyline.json`. (The §3 probes prove this outcome on
   today's bytes; the act re-proves it on its own head.) Then the
   checklist's remaining gates as written: family suites, full
   suite, dependency parity, ruff.
4. **Freeze-coverage gate on the act's full diff** (repo matcher,
   `scripts/reconcile_freeze_deltas.py::_covered_change` over
   `config/freeze_reconciliation_registry_v1.json`). This memo's
   pre-check (§6) finds every candidate path NOT GOVERNED; the
   act re-runs it regardless, per standing law.
5. **Review, then merge (checklist, unchanged).** Independent
   review closes on the act's exact head before the merge records
   the freeze; landing verified on the remote. k is unaffected by
   the retirement — the drafts were never clocks and appear
   nowhere in the checklist's k = 12 table — and the act recomputes
   k as the checklist already requires.

**Risks, named.** (i) The readiness audit's `forward_test_config`
pointer for (NFL, SPREAD)/(NFL, TOTAL) re-points from the
FREE_MODELS_GAME drafts to the EFV2 config — this is the intended
effect of the act, it is verified by probe in §3, and step 3 makes
the act re-verify it rather than discover it later; readiness
labels and play authority do not change (`RESEARCH_PRICED_NOT_VALIDATED`,
`play_authority_from_config: false` throughout). (ii) While
EFV2's clock runs, the one-config law bars a future FREE_MODELS_GAME
NFL spread/total draft registration; reviving that test later
requires EFV2's clock to have closed and a fresh draft — the
owner accepts this by adopting the act, and PROGRAM.md §4.2
already framed these drafts as freezable-or-not at the owner's
election. (iii) The dated Oct 21 readiness snapshot is a historical
artifact and is **not** regenerated or edited by the act; it
continues to describe Oct 21 state truthfully. (iv) Nothing in the
retirement touches Lane A pricing, the NFL team-totals clock, or
any frozen family's terms (§2, item 7).

## 6. Freeze-coverage pre-check (this memo, on main `c04e55052`)

Repo matcher over all bundles in
`config/freeze_reconciliation_registry_v1.json`:

| Path | Coverage |
|---|---|
| `sportsedge/forward_validation/configs/nfl_spread.json` | NOT GOVERNED |
| `sportsedge/forward_validation/configs/nfl_total.json` | NOT GOVERNED |
| `sportsedge/forward_validation/configs/nfl_entry_form_v2.json` | NOT GOVERNED |
| `scripts/audit_cross_sport_accuracy_readiness.py` (Option C only) | NOT GOVERNED |
| `tests/test_cross_sport_accuracy_readiness.py` (Option C only) | NOT GOVERNED |
| `tests/test_nba_v2_accuracy_readiness_bridge_20261026.py` (Option C only) | NOT GOVERNED |
| `research/forward_validation_program_20261020/drafts/PREREG_NFL_SPREAD_FORWARD_V1_DRAFT.md` | NOT GOVERNED |
| `research/forward_validation_program_20261020/drafts/PREREG_NFL_TOTAL_FORWARD_V1_DRAFT.md` | NOT GOVERNED |
| `research/forward_validation_program_20261020/PROGRAM.md` | NOT GOVERNED |
| `research/nfl_entry_form_v2_20261028/COLLISION_RESOLUTION_MEMO.md` (this memo) | NOT GOVERNED |
| `research/nfl_entry_form_v2_20261028/FREEZE_RECORD.md` (act) | NOT GOVERNED |
| `research/nfl_entry_form_v2_20261028/PREREG_FINAL.md` | NOT GOVERNED |

NOT GOVERNED is a pre-check result, not a clearance: the act
re-runs the gate on its own diff before its clearance, as the
checklist requires.

## 7. What this memo does not do

It does not execute the freeze act, install any config into
`sportsedge/forward_validation/configs/`, delete or edit either
incumbent config, change any config's status, or amend the audit.
The freeze remains a separate prospective act under
`FREEZE_ACT_CHECKLIST.md`, with owner authorization and independent
exact-head review in the checklist's sequence. If this memo's
recommendation is not adopted, the REGISTRY GATE item stays open
and the act stays blocked — the collision does not resolve itself.

*Prepared Oct 28, 2026. Sources: the two incumbent configs and
their draft preregistrations; `research/forward_validation_program_
20261020/PROGRAM.md`; `scripts/audit_cross_sport_accuracy_readiness.py`;
`sportsedge/forward_validation/core.py`;
`research/cross_sport_accuracy_readiness_20261021.json`;
`research/nfl_entry_form_v2_20261028/` (CONFIG_DRAFT.json,
FREEZE_ACT_CHECKLIST.md, PREREG_FINAL.md); GitHub API file history
for both incumbent paths; author's audit probes on main
`c04e55052` (table in §3).*
