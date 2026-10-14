# ERRATUM — Population Definition, CFB_FOUR_FAMILY_EVALUATION_V1 Freeze Package

**Date:** October 14, 2026.
**Prepared by:** the Muse lane (Rocky), for the owner's ruling.
**Status: DRAFT ERRATUM FOR OWNER RULING. Nothing in this document
ratifies, amends, or freezes anything by itself.** The frozen package
(`FREEZE_PACKAGE.md`, file SHA-256
`354452903b8c679becf38482a7b01170e133cfe3b7c00d8ae096400706355f0d`)
and every frozen file remain byte-untouched. Attempt 1 remains **HELD and
unspent**; the dry-run manifest still reads `run_state: NOT_RUN`,
`attempts_consumed: 0`, `freeze_sha: null`.
**Origin:** owner finding on PR #2258 (Oct 14) — the freeze package's
§3.4 population sentence contradicts the dataset the package itself
counts. This erratum prepares the decision; the ruling is the owner's
(§7, left blank).

---

## 1. The contradiction, stated exactly

FREEZE_PACKAGE.md §3.4 ("Fold protocol (RULED)"), population bullet,
verbatim:

> - **Population:** FBS regular-season games in which **both** teams are
>   FBS programs under season-effective membership (§4/R2). Postseason
>   games (bowls, conference championships, playoff) are a separate
>   population and are **never pooled**. Games vs FCS opponents are
>   excluded (`POPULATION_NON_FBS_OPPONENT`), counted. Illinois-excluded
>   fixtures are removed **before** population counting
>   (`BLOCKED_PREPRICING_IL_COLLEGE_EXCLUDED`) — never in the production
>   population. Unbindable team identity fails closed
>   (`BLOCK_TEAMS_UNRESOLVED`).

The counted fact, established by the independent recount
(`RECOUNT_R3.md`, same folder; 144/144 checks, corpus hashes verified
before counting, lines-side figures re-derived from the pinned raw
archive rows game by game):

- The population the frozen classifier actually constructs is **9,536**
  games, of which **503 carry `season_type` "3" (postseason)** in the
  bound results snapshot: **294 in burn-in** (36/37/39/40/38/38/39/27
  across 2013–2020) and **209 in the five folds** (40/41/40/44/44
  across 2021–2025). The remaining population is 9,032 games of
  `season_type` "2" (regular season) and 1 game with an empty
  season-type field (2013 Penn State–Purdue, week 12 — a regular-season
  game whose type field is empty in the source; it is in the
  population under both paths below).
- The classifier applies **no season-type filter at all** (see the
  census, §2). The §3.4 sentence describes a regular-season population
  that was never constructed.

**The counts are correct; the eligibility definition is wrong.** Both
cannot be ratified as they stand: R3's ratification text is "the bound
dataset, exactly as counted," and §3.4's sentence is part of the
preregistration text the freeze would file. Silently editing the
wording would hide that the definition and the dataset disagreed;
this erratum exists so the reconciliation is a recorded owner act.

Two paths reconcile them — **Path A** (formally include postseason;
correct the text to the dataset) and **Path B** (exclude postseason;
regenerate the dataset to the text). Both are fully costed below.

---

## 2. Census of population definitions

Every site where the population is defined or described, quoted
verbatim, with its consistency against the counted dataset.

| # | Site | Definition / description (verbatim) | vs counts |
|---|---|---|---|
| 1 | `FREEZE_PACKAGE.md` §3.4, population bullet | "FBS regular-season games in which **both** teams are FBS programs under season-effective membership (§4/R2). Postseason games (bowls, conference championships, playoff) are a separate population and are **never pooled**." | **CONTRADICTS** — counted population pools 503 postseason games |
| 2 | `PREREGISTRATION_DRAFT.md` §4.1 (origin of the sentence; the draft is a pinned source — SHA-256 `57f1d81b…` — named in FREEZE_PACKAGE's evidence base and in the harness config's `spec` field) | "**Population (proposed):** FBS regular-season games in which **both** teams are FBS programs. Postseason games (bowls, conference championships, playoff) are a separate population and are **never pooled** (the NFL design's rule)." | **CONTRADICTS** — same sentence, inherited into §3.4 when the rulings were filled in |
| 3 | `PREREGISTRATION_DRAFT.md` §4.1, fold-minimum rationale | "an FBS regular season runs ~850 games, so 500 tolerates exclusions without licensing a gutted fold" | Premised on the regular-season frame; the floor (500) itself is reading-independent and clears under both paths (§4) |
| 4 | `FREEZE_PACKAGE.md` §1.2 (what the freeze pins) | "the ruled configuration: CAND_2, both-FBS population, folds 2021–2025 with burn-in 2013–2020, CFBD DESCRIPTIVE_ONLY…" | Consistent with counts — no season-type element |
| 5 | `FREEZE_PACKAGE.md` Owner Summary, R3 | "**R3 — The bound dataset, exactly as counted.** Population 9,536; pooled matched moneyline 3,335 / spread 3,773 / total 3,773 / team_total 0…" | Consistent with counts — it is the as-counted dataset |
| 6 | `FREEZE_PACKAGE.md` §2 verification table; §3.4 restated-counts table; §4/R3 | Population 9,536 (burn-in 5,754); folds 739/747/757/765/774; exclusions 511 Illinois / 1,446 non-FBS / 2 unresolved | Consistent with counts (all are the as-counted numbers, independently recounted 144/144) |
| 7 | Frozen harness config, `config/research/cfb_four_family_evaluation_v1.json` @ `bfba59f3f` | `"population_rule": "EXCLUDE_FCS_OPPONENTS"` (in `ruling_recommendations_from_draft`; the shipped `rulings.population_rule` is `"UNRULED"`). No `season_type`, postseason, or regular-season key exists anywhere in the file | Consistent with counts — the encoded rule has no season-type element |
| 8 | Frozen bindings config, `config/research/cfb_four_family_bindings_v1.json` @ `bfba59f3f` | `"population_rule": "EXCLUDE_FCS_OPPONENTS"` (recorded RULED). No season-type element anywhere in the file | Consistent with counts |
| 9 | Harness module, `sportsedge/research/cfb_four_family_evaluation_v1.py` @ `bfba59f3f`, `classify_population` (lines 782–826) | Applies exactly four filters, in order: Illinois (`BLOCKED_PREPRICING_IL_COLLEGE_EXCLUDED`) → unresolved (`BLOCK_TEAMS_UNRESOLVED`) → no-contest → non-FBS (`POPULATION_NON_FBS_OPPONENT`). The strings `season_type`, `postseason`, and `regular` **do not appear anywhere in the module**; the `GameRecord` dataclass (lines 402–416) has **no `season_type` field** | Consistent with counts — and structurally incapable of a season-type filter today (load-bearing for Path B costing, §4) |
| 10 | Bindings module, `sportsedge/research/cfb_four_family_bindings_v1.py` @ `bfba59f3f` | Carries `season_type` through into the results snapshot record (`"season_type": str(row.get("season_type") or "")`, line ~621) as **data**; never tests it. `BINDINGS.md` describes the population only as "both-FBS (`EXCLUDE_FCS_OPPONENTS`)" and prints the dry-run counts | Consistent with counts — the field exists in the snapshot precisely so the counted composition is auditable (it is how the recount found the 503) |
| 11 | `HARNESS.md` | No regular-season/postseason population language; §4.1 row describes folds/burn-in and "population/IL/FCS/no-contest exclusions" only | Silent — consistent with counts |

**Dependence check (does anything else in the protocol turn on the
regular-season reading?):**

- **Fold construction:** folds are defined by season alone
  (`evaluation_seasons` 2021–2025; training = all seasons strictly
  before; burn-in = seasons 2013–2020). No season-type dependence.
- **Within-fold walk-forward / ratings state:** the harness walks the
  *population* chronologically and folds each game's result into the
  ratings state after predicting it (harness run, lines ~1512–1525).
  Postseason games are each season's last games, so under the
  as-counted population they are scored with the most complete
  within-season state and their results enter the state carried into
  later seasons. This is a mechanical consequence of the counted
  population, under either path's ruling (§§3–4 state what changes).
- **Bootstrap cluster unit** is `"season:week"` (§3.5); postseason
  games carry week values in the snapshot and form their own week
  blocks. No definitional dependence.
- **Floors and gates** (500/fold/family, 75% coverage, 2,500 pooled,
  CI gates) are stated over "scored games" of the population,
  whichever population is ruled; §4 verifies the as-counted gates'
  status under Path B's regenerated counts.
- **Other season types in the corpus:** the results snapshot also
  carries `season_type` "4" (30 games — the all-star entities) and
  "5" (2 games). **None reach the population under either path**
  (they exit via unresolved/non-FBS). A Path B rule must therefore
  target `season_type` "3" exactly — a "not regular-season" rule
  would be a different, broader change.

---

## 3. Path A — formally include postseason; reconcile the text to the dataset

**What changes:** the definition's wording, in the erratum record
only. The dataset, every count, and the candidate identity are
untouched.

**Required reconciliation actions (complete list):**

1. **This erratum**, filed with the freeze package and hash-chained to
   it, recording that FREEZE_PACKAGE §3.4's population bullet is
   corrected to read, in substance: *the population is both-FBS games
   of all season types in the bound results snapshot, postseason
   games included and pooled — 9,536 games, of which 503 are
   postseason (`season_type` "3": 294 burn-in, 209 in the folds).*
2. **A note against PREREGISTRATION_DRAFT §4.1** recording that its
   population sentence is superseded by the erratum. The draft itself
   is **not edited**: its SHA-256 (`57f1d81b…`) is pinned in
   FREEZE_PACKAGE's evidence base and in the harness config's `spec`
   field; editing it would break those pins and falsify the record
   of what was drafted. The draft's §4.1 fold-minimum rationale
   ("~850 games") stands as a rationale approximation; the floor is
   unchanged.
3. If the package is ever re-issued, §3.10's differences list gains
   the population-definition correction as an enumerated difference
   from the draft. (No re-issue is required for the freeze act if the
   erratum is filed alongside, per the owner's ruling in §7.)

**What does NOT change under Path A** (verified, not assumed): both
frozen configs already encode the as-counted rule
(`EXCLUDE_FCS_OPPONENTS`, no season-type element — census #7/#8);
the harness classifier already implements exactly the as-counted
population (census #9); the bindings layer, all three snapshots, and
the dry-run manifest are untouched; every published count (§2 table,
§3.4 table, §4/R3) is already the as-counted number. **Candidate
identity `bfba59f3f` survives.**

**Consequences the owner accepts by ruling Path A** (record-supported
composition facts only; computed from the bound snapshots by the
costing script, `pathb_costing.py`, same folder):

- 209 postseason games are **scored** in the folds. Their matched
  coverage differs sharply by family: spread/total 206 of 209
  (98.6%), but moneyline only **125 of 209 (59.8%)**, against
  fold-wide moneyline coverage of 84.7–91.3%. The cause is in the
  record: the moneyline sign-inconsistency quarantine concentrates
  in postseason games — **62 of the 209 postseason population games
  (29.7%) carry a quarantined moneyline**, vs 143 of 3,573 regular
  population fold games (4.0%). The §3.5 coverage presumption is
  computed per family over the whole fold, so no gate trips; but the
  postseason subset's moneyline evidence is materially thinner, and
  any readout under this freeze would carry that composition.
- **479 of the 503 postseason population games (95.2%) are
  neutral-site**, vs 245 of 9,033 regular population games (2.7%).
  Per the recorded production trait (BINDINGS.md), neutral-site
  games keep the designated-home treatment — the frozen engine and
  BASE-1 both apply the static home advantage identically — so the
  trait is symmetric across candidate and baseline; it is disclosed
  here because Path A pools 503 such games rather than none.
- Postseason results feed later seasons' walk-forward ratings state
  (§2 dependence check) — the same treatment regular-season results
  receive; no special handling exists or is proposed.

---

## 4. Path B — exclude postseason; regenerate the dataset to the text

**The regenerated dataset** (computed from the bound snapshots with
the recount's funnel, extended by `pathb_costing.py`; the headline
figures agree exactly with RECOUNT_R3.md §4's independently computed
Reading B — 9,033 / 5,460 / 699/706/717/721/730 /
3,210/3,567/3,567):

| Quantity | As counted (A) | Path B (exclude `season_type` "3") |
|---|---|---|
| Population | 9,536 | **9,033** (9,536 − 503) |
| Burn-in population 2013–2020 | 5,754 | **5,460** (−294) |
| Fold 2021 | 739 | **699** |
| Fold 2022 | 747 | **706** |
| Fold 2023 | 757 | **717** |
| Fold 2024 | 765 | **721** |
| Fold 2025 | 774 | **730** |
| Pooled fold population | 3,782 | **3,573** (−209) |
| Matched ML per fold | 646/633/691/682/683 | **629/617/662/649/653** |
| Matched spread per fold | 735/743/757/764/774 | **698/702/717/720/730** |
| Matched total per fold | 735/743/757/764/774 | **698/702/717/720/730** |
| Pooled matched ML / spread / total / team_total | 3,335 / 3,773 / 3,773 / 0 | **3,210 / 3,567 / 3,567 / 0** |
| ML coverage per fold | 87.4/84.7/91.3/89.2/88.2% | **90.0/87.4/92.3/90.0/89.5%** (rises — the removed games were quarantine-dense) |
| Burn-in distinct teams | 128 | 128 (unchanged) |
| Evaluation teams with no burn-in population evidence | 6 | 6 (unchanged — the same six: Delaware, Jacksonville State, James Madison, Kennesaw State, Missouri State, Sam Houston State) |

**Gate status under Path B's counts** (dry-run sense; thresholds
unchanged): smallest fold matched count = 617 (ML 2022) ≥ 500 floor;
lowest fold coverage = 87.4% (ML 2022) ≥ 75% floor; pooled matched
3,210/3,567/3,567 ≥ 2,500 floor. All three in-scope families still
clear every floor. Team_total remains 0 under both paths.

**Exclusion-class intersections with postseason** (per class, as the
owner's finding requires — classes are record dispositions over the
lines archive / results corpus, computed on the frozen files):

| Class (frozen count) | ∩ postseason | Detail |
|---|---|---|
| ML quarantines (220 records) | **65 of the 219 that join to a results game are `season_type` "3"**; **62 are in the as-counted population** (all 62 `ML_SPREAD_SIGN_INCONSISTENT`; the remaining 3 postseason quarantines touch non-population games) | The class is defined on the archive, not the population: the disposition count **stays 220 under Path B**. What changes is its intersection with the scored population: 205 quarantined population games under A (143 regular + 62 postseason) → **143 under B**. Of the 6 uncheckable (`ML_CROSSCHECK_UNAVAILABLE`): 3 touch regular population games, 3 touch non-population games, 0 are postseason |
| Orphan line records (58) | **Not classifiable** — orphans are defined by the *absence* of a results game, so no `season_type` exists for them in the bound data | Count invariant: **58 under both paths**. (One orphan, 401767476 Nicholls–Incarnate Word, is also the 1 quarantined record that joins no results game — the record-level overlap of the two classes.) Under a Path B rebuild in which postseason games leave the results snapshot (shape B1 below), Bovada line records for removed games would *become* orphans at build time — see the regeneration list |
| Post-kickoff line records (3) | **0** — all three results records are `season_type` "2" (2023, 2023, 2025), and none is in the population under either path (all FBS-vs-FCS) | Count invariant: **3 under both paths** |
| Unresolved-team games (2) | **0 under the "3" definition** — both games (401405374, 401495505; Team Gaither vs Team Robinson, 2021/2022) carry `season_type` **"4"** (all-star), a distinct type that exits via `BLOCK_TEAMS_UNRESOLVED` under both paths | Count invariant: **2 under both paths**. (A carelessly worded "non-regular-season" exclusion would sweep type "4"/"5" too; the ruled target must be "3" exactly) |
| Illinois fixtures (511) / non-FBS (1,446) / no-contest (0) | Funnel classes over results games; the postseason games inside them are already outside the population under both paths | The funnel totals for these classes are population-order artifacts (RECOUNT §2 funnel note); Path B adds one more class (postseason, 503 at the population step) without changing the counted totals of the others as dispositions of the corpus |

**What a Path B ruling forces to regenerate** (complete list):

1. **A new candidate identity.** Any pinned file changing ends the
   candidate (§1.2 of the package: "any change to any pinned file
   ends the cohort"). Under Path B at minimum the bindings config
   and the dry-run manifest change; therefore **`bfba59f3f` is
   superseded** and a new candidate commit must be composed,
   re-verified, and named by a new freeze act. The current candidate
   is not edited in place.
2. **Bindings config** — the `population_rule` record must describe
   the ruled exclusion (a season-type element that does not exist in
   the config today, census #8).
3. **Dry-run manifest** — regenerated with the Path B counts above
   (population, per-fold matched/coverage, floors).
4. **Every published count citing 9,536 or the fold sizes** —
   FREEZE_PACKAGE §2 table, §3.4 restated-counts table and its
   "(Full population including burn-in: 9,536…)" note, Owner Summary
   R3, §4/R3, and BINDINGS.md's dry-run tables — restated to the
   Path B figures. §3.4's population *sentence* needs no change
   under Path B (it becomes true); its numbers do.
5. **Implementation of the exclusion — two shapes, owner's
   implementer to choose, costed here:**
   - **B1, data-level:** the bindings snapshot builder drops
     `season_type` "3" games when building a **new results
     snapshot** (new snapshot id/file hash; corpus total 11,495 →
     10,969, removing all 526 type-"3" results games, 23 of which
     were never in the population). Harness code byte-unchanged.
     Cost: the 503 leave *silently* — no named exclusion counts
     them, in tension with §3.7's discipline ("an excluded game is
     never… a silent drop"), and the results snapshot stops being
     the full bound corpus. Knock-on: lines joined against the
     smaller results corpus reclassify removed games' records as
     orphans at load (the orphan disposition count over the rebuilt
     corpus rises accordingly — the 58 is a property of the pairing,
     not of the archive alone).
   - **B2, rule-level:** `GameRecord` gains a `season_type` field,
     the bindings loader passes it through, `classify_population`
     gains a fifth filter with a named exclusion reason (e.g.
     `POPULATION_POSTSEASON_EXCLUDED`, applied last so exactly 503
     are counted), the harness config's ruled `population_rule`
     gains the new value, and the batteries gain the corresponding
     tests. Snapshots keep their current ids (the data is
     untouched; the rule changes). Cost: the harness module — a
     pinned file — changes, so the harness commit and the whole
     stack above it are recomposed.
   Under **both** shapes the lines and directory snapshot *files*
   are unchanged (the lines file retains all records; flags and
   matched counts are manifest-level). The harness's fold/burn-in
   *structure* is unchanged under both.
6. **The #2258 registration packet** must be re-issued against the
   new candidate identity and regenerated counts (see §5).

---

## 5. DESIGN IMPACT — per the owner's ruling standard

**The owner's standard for this ruling (Isaac, Oct 14):** internal
consistency of the frozen record, reproducible counts, and this
design record — **not maximizing games.** Both paths produce an
internally consistent, reproducible package; they differ in which
population the protocol describes. Element by element:

| Design element | Path A (include postseason) | Path B (exclude postseason) |
|---|---|---|
| Population definition | **Unchanged as implemented** (9,536, both-FBS, all season types); the §3.4 *text* is corrected by erratum to describe it | **Changed in substance** — the implemented definition narrows to regular-season only (9,033), making the existing §3.4 text true |
| Fold counts | Unchanged: 739/747/757/765/774 (Σ 3,782) | Changed: 699/706/717/721/730 (Σ 3,573) |
| Burn-in count | Unchanged: 5,754 | Changed: 5,460 |
| Pooled matched pools (ML / spread / total / team_total) | Unchanged: 3,335 / 3,773 / 3,773 / 0 | Changed: 3,210 / 3,567 / 3,567 / 0 |
| Comparator (BASE-1) + thresholds/gates (§3.5: CI gates, ≥3-of-5 folds, 500 fold floor, 75% coverage presumption, 2,500 pooled floor, calibration band; §3.8 attempt budget) | Unchanged, verbatim | Unchanged, verbatim — and the regenerated counts still clear every floor (§4) |
| Fold protocol structure (5 expanding folds 2021–2025, burn-in 2013–2020, within-fold walk-forward, settlement) | Unchanged | Unchanged in structure; the walk-forward state is built from 503 fewer games (294 of them burn-in) |
| Harness code | Unchanged, byte-identical | Unchanged under shape B1; changed under shape B2 (a named classifier exclusion — the shape consistent with §3.7's counted-exclusion discipline) |
| Bindings / config artifacts | Unchanged — configs already encode the as-counted rule; snapshots and dry-run manifest untouched | Regenerated — bindings config population record, dry-run manifest; results snapshot additionally regenerated under B1 only |
| Candidate identity | **Survives** — `bfba59f3f` remains the candidate; this erratum attaches to the package | **Superseded** — a new candidate must be composed, re-verified, and named; every published count citing 9,536 or the fold sizes is regenerated (§4 list) |
| #2258 registration packet contents | The packet as prepared (freeze package + R1–R3) **plus this erratum**, reconciling §3.4 to the counts; R3 ratified "exactly as counted" with the erratum on record | The packet re-issued against the **new candidate identity** with regenerated counts; the current candidate's registration content is superseded, and R3 is ratified on the regenerated dataset |

**In so many words:**

- **Path A does not change the evaluation design.** It is a text
  erratum only: the definition's wording is brought into line with
  the dataset that was built, counted, independently recounted, and
  proposed for ratification. Candidate identity survives.
- **Path B changes the frozen dataset and therefore the candidate,
  but not the evaluation's structure.** Candidate, baseline,
  metrics, gates, fold structure, and attempt rules are identical;
  the population they operate on is a different, smaller set, and
  under the program's own freeze mechanics the dataset is part of
  the frozen object — so Path B is a **new freeze candidate**, not
  an erratum. Nothing about Path B is a repair of a counting error:
  the counts under both paths are reproducible from the same bound
  corpus (this document, §4; RECOUNT_R3.md).

---

## 6. Publication and reproducibility

This erratum, `RECOUNT_R3.md`, and the recount scripts
(`recount_r3.py`, `recount_r3_raw.py`) plus the Path B costing script
(`pathb_costing.py`) are published on the evidence branch
`freeze/cfb-four-family-evaluation-v1-rederivation-20261014` under
`docs/`, alongside the harness/bindings re-derivation patches already
there, so the owner can verify every number without this workspace.
The scripts read the frozen snapshot corpus and the pinned raw
sources; the raw sources are reproducible from the frozen bindings
config's recorded identities — upstream repository
`sportsdataverse/cfbfastR-data` @ `f5a05dc815951b8dbe18961a824f34cf154dfa61`
(lines archive, SHA-256 `7ae899d903…`) and the SportsDataverse
`espn_cfb_schedules` release (13 schedule CSVs, per-season SHA-256
pins in the config) — and the staging copies used here hash-match
those pins exactly (RECOUNT_R3.md §1). The frozen bindings config the
scripts consume is extracted as
`git show bfba59f3f:config/research/cfb_four_family_bindings_v1.json`.

---

## 7. OWNER RULING

Path chosen (A / B): ______________

If Path B — implementation shape (B1 / B2): ______________

Date: ______________

Owner: ______________

*(Left blank deliberately. This erratum prepares the ruling; it does
not make it. Until the ruling is recorded, the freeze package stands
as prepared, §3.4's sentence stands unreconciled, and Attempt 1
remains HELD and unspent.)*

---

*Prepared Oct 14, 2026, by the Muse lane under issue #2218 M2 / the
PR #2258 finding. Sources: FREEZE_PACKAGE.md, BINDINGS.md,
PREREGISTRATION_DRAFT.md, HARNESS.md; frozen configs and modules at
`bfba59f3f` / `b68114e0f` (read via `git show`); RECOUNT_R3.md
(144/144); computations by `pathb_costing.py` over the hash-verified
frozen snapshot corpus. No frozen file was modified; no evaluation
was run; no game was scored.*
