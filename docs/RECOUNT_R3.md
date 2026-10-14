# CFB Four-Family Evaluation — Independent R3 Recount

**Directive:** issue #2218 M2 (Oct 14, 2026) — independently re-derive the
freeze's R3 population counts. **This is a verification recount only.** No
model was scored, no evaluation was run, no attempt was consumed, nothing
was re-frozen, and no frozen file was edited. Attempt 1 remains HELD and
unspent (the dry-run manifest still reads `run_state: NOT_RUN`,
`probabilities_computed: false`, `attempts_consumed: 0`, `freeze_sha:
null` — all re-verified below).

**Method / independence.** Two fresh, stdlib-only scripts were written
for this recount —
[recount_r3.py](sandbox://workspace/sportsedge/cfb_four_family_evaluation_20261013/recount_r3.py)
(snapshot-level recount) and
[recount_r3_raw.py](sandbox://workspace/sportsedge/cfb_four_family_evaluation_20261013/recount_r3_raw.py)
(raw-source re-derivation), same folder. Neither imports **anything**
from the SportsEdge repo — in particular neither imports or calls the
bindings module (`cfb_four_family_bindings_v1.py`) or the harness
module (`cfb_four_family_evaluation_v1.py`). They re-implement the
counting rules as documented in FREEZE_PACKAGE.md §3.4/§4 and
BINDINGS.md. Two frozen inputs were read as *data* (their role is
identical to a preregistration table): the 13-entry override table
from the frozen bindings config at `bfba59f3f`
(`git show bfba59f3f:config/research/cfb_four_family_bindings_v1.json`),
and the 13-id Illinois registry transcribed from the harness module's
cited constant (frozen on main by PR #2148).

**Result: 144 of 144 checks MATCH, 0 mismatches** (112 snapshot-level +
32 raw-source). Every R3 number in the frozen record reproduces
exactly — the lines-side numbers are re-derived from the pinned raw
archive rows themselves, game by game (§2). One substantive
definitional finding about the freeze *text* (not the counts) is in
§4, with both readings stated; descriptive imprecisions and the
remaining verification limits are in §5–§6.

---

## 1. Corpus identity — hashes verified before counting

| File | Frozen identity (FREEZE_PACKAGE §1.1/§2 = SNAPSHOT_MANIFEST) | Recount SHA-256 | Verdict |
|---|---|---|---|
| `results_snapshot.json` | `830ebe5a0262…` (4,515,975 B) | `830ebe5a0262b26b8ebc62b6075a7bf70eb814c99025b1ea94ab9596ae586389` | MATCH |
| `lines_snapshot.json` | `72c4476f78f7…` (1,921,452 B) | `72c4476f78f7b1b82919df97a1c02f781260969f334ab5f7185c8b0e42e0c578` | MATCH |
| `directory_snapshot.json` | `503d29b60e05…` (179,129 B) | `503d29b60e05ff73fb0997eba83b8dcd908a510415737674bb621d2e93b9a3b6` | MATCH |
| `DRY_RUN_MANIFEST.json` | `d6a1e30a1cd6…` | `d6a1e30a1cd6c4780833ccafd35cb2ace15da73ecd4b5c913f024861f4c2bb6d` | MATCH |

Snapshot ids embedded in the files match the recorded ids
(results `151774e8…`, lines `9cc966b5…`, directory `764a32c8…`). The lines
snapshot's internal source block carries the same upstream pin as the
frozen config (archive SHA-256 `7ae899d903…`, commit `f5a05dc8…`,
blob SHA-1 `fe568cf1…`).

**Raw sources.** The bindings build's staging directory
(`~/workspace/tmp/cfbbind/sources/`) retains the pinned raw sources,
and every one was hash-verified against the frozen config's pins
before use: all **13 schedule CSVs** (each SHA-256 equals its config
pin), the **lines archive** (SHA-256 `7ae899d903…`, 7,047,701 bytes —
exact pin match), and the **team-info parquet** (SHA-256 `503549b9…`,
133,323 bytes — exact pin match). The phase-2 recount therefore
re-derives the dataset from the same raw bytes the bindings consumed,
not merely from the bindings' outputs. (The parquet's row content was
not re-parsed — no parquet reader is installed in this environment;
the directory snapshot itself is hash-frozen per the table above, and
its source file's hash matches the pin. See §6.)

## 2. R3 counts — frozen claim vs independent recount

Population funnel, applied in the documented order (Illinois removed
before population counting → unresolved → no-contest → non-FBS), with
season-effective FBS membership recomputed from the directory snapshot's
classifications plus the override table (never from the results file's
stored flags — those were used only as a cross-check, and my
recomputation agrees with all 22,990 stored home/away FBS flags, 0
disagreements):

| Item | Frozen claim | Recount | Verdict |
|---|---|---|---|
| Results snapshot games | 11,495 | 11,495 (0 duplicate ids; 0 undecided/null-score games). Phase 2 rebuilt the corpus from the 13 raw schedule CSVs: identical game-id set, and **all 11,495 games agree field-by-field** (season, week, season_type, both team ids, both team names, both scores, status, neutral site, kickoff — 0 mismatches) | MATCH |
| − Illinois fixtures | 511 | 511 | MATCH |
| − unresolved-team games | 2 | 2 | MATCH |
| − no-contest games | 0 (implied) | 0 | MATCH |
| − non-FBS-opponent games | 1,446 | 1,446 | MATCH |
| **= Population** | **9,536** | **9,536** (11,495 − 511 − 2 − 0 − 1,446) | MATCH |
| Burn-in population 2013–2020 | 5,754 | 5,754 (128 distinct teams; eval teams without burn-in evidence: 6) | MATCH |
| Fold populations 2021/22/23/24/25 | 739 / 747 / 757 / 765 / 774 (Σ 3,782) | 739 / 747 / 757 / 765 / 774 (Σ 3,782) | MATCH |
| Pooled matched — moneyline | 3,335 | 3,335 (per fold 646/633/691/682/683) | MATCH |
| Pooled matched — spread | 3,773 | 3,773 (per fold 735/743/757/764/774) | MATCH |
| Pooled matched — total | 3,773 | 3,773 (per fold 735/743/757/764/774) | MATCH |
| Pooled matched — team_total | 0 | 0 (no team-total lines anywhere in the corpus) | MATCH |
| Per-fold "with any lines record" | 735 / 743 / 757 / 764 / 774 | identical | MATCH |

Exclusion classes on the lines side — **all re-derived from the raw
archive rows in phase 2**, not read off the snapshot's labels. The
recount rebuilt every Bovada game (2021–2025) from the archive,
assigned moneyline/spread sides by school identity using the archive's
own per-game naming (`game_desc` "Away@Home" — the directory parquet's
school strings differ for some programs, e.g. "App State" vs
"Appalachian State", "UTSA" vs "UT San Antonio", and do **not**
reproduce the frozen outcomes), and applied the documented cross-check
as a per-side sign rule: the spread favorite's moneyline must be
negative and the spread underdog's positive; a pick'em spread (0.0)
offers no sign to check against. The rebuilt outcomes agree with the
frozen record **for every one of the 4,325 games individually** (0
per-game outcome disagreements; 0 moneyline, spread, total, or
date_time value disagreements):

| Item | Frozen claim | Recount (from raw rows) | Verdict |
|---|---|---|---|
| Bovada ML quarantines | 220 | 220 | MATCH |
| — sign-inconsistent (`ML_SPREAD_SIGN_INCONSISTENT`) | 214 | 214 (incl. both-negative pairs whose underdog side carries a negative moneyline, and flipped pairs) | MATCH |
| — uncheckable (`ML_CROSSCHECK_UNAVAILABLE`) | 6 | 6 (all six are pick'em-spread games, spread exactly 0.0) | MATCH |
| Orphan line records (`LINE_RECORD_WITHOUT_RESULTS_GAME`) | 58 | 58 — the rebuilt orphan set (Bovada game ids absent from the rebuilt results corpus) is **set-identical** to the frozen flag list | MATCH |
| Post-kickoff line records (`POST_KICKOFF_LINE_TIMESTAMP`) | 3 | 3 — the rebuilt set (archive `date_time` strictly after the schedule kickoff) is **set-identical** to the frozen flag list (ids 401520150, 401532395, 401752685; deltas in §5) | MATCH |
| Bovada games with any market | 4,325 | 4,325 distinct archive games, set-identical to the snapshot's games dict (composition: 4,267 joined to results + the 58 orphans, which the snapshot retains as records with empty team ids) | MATCH |
| Bovada ML ok / spread ok / total ok | 3,588 / 4,324 / 4,323 | 3,588 / 4,324 / 4,323 (plus 517 games with no complete ML pair; 3,588 + 220 + 517 = 4,325; zero team-total market rows exist in the archive) | MATCH |

Provider-coverage table (FREEZE_PACKAGE §4/R1) cross-checked against the
snapshot's `provider_coverage` for all four named books — Bovada
(4,325 / ML ok 3,588 / quar 220 / spread 4,324 / total 4,323), ESPN Bet
(3,541 / 1,524 / 68 / 3,529 / 3,532), William Hill NJ (3,105 / 0 / 0 /
3,105 / 3,103), DraftKings (2,379 / 2,128 / 122 / 2,370 / 2,259):
**all MATCH.**

Funnel-order note (arithmetic hygiene): the exclusion classes overlap
in principle — 70 games are both Illinois fixtures and non-FBS games,
and the 2 unresolved games also involve non-FBS-classified opposition.
The frozen totals correspond exactly to the documented sequential order
(Illinois first). Counted independently of order, the same 9,536 games
remain: the final population is order-invariant here; only the class
attribution of 72 games depends on the order, and it follows the
documented one.

## 3. R1 and R2 checks

- **R1 — Bovada.** `designated_provider: "Bovada"` confirmed in all
  three records (frozen config, lines snapshot payload, dry-run
  manifest), with status `BINDINGS_DEFAULT_NOT_OWNER_RULED` in the
  config — i.e., still a bindings default until the freeze act ratifies
  it, exactly as the package states. MATCH.
- **R2 — override table.** The frozen config's
  `FBS_MEMBERSHIP_OVERRIDES_V1` contains **exactly 13 entries**; the
  directory snapshot's embedded copy is identical (all 13 ids, schools,
  classifications, season lists). Against the FREEZE_PACKAGE §4 table:
  team ids, table classifications, and deviating seasons match for
  **13 of 13**; the builder's guard (each override id's directory
  classification equals its table classification) holds for 13 of 13.
  **One name-form difference:** the package's R2 table prints
  "Sam Houston"; the config and the directory snapshot both carry the
  school as **"Sam Houston State"** (id 2534, FCS 2013–2022 in both).
  Same program, same id, same seasons — a prose abbreviation in the
  package, not an identity difference. All other 12 names match
  character-for-character.

## 4. Substantive finding — the counted population includes postseason games; the freeze text says it doesn't

FREEZE_PACKAGE §3.4 describes the population as *"FBS regular-season
games"* and states *"Postseason games (bowls, conference championships,
playoff) are a separate population and are never pooled."* The counted
population does not match that description. The classifier (per the
documented funnel, which my recount re-implements) applies **no
season-type filter**, and the results snapshot's own `season_type`
field shows the population contains:

- 9,032 games with `season_type` "2" (regular season),
- **503 games with `season_type` "3" (postseason — bowls/playoff;**
  samples verified by matchup: Colorado State–Washington State,
  USC–Fresno State, San Diego State–Buffalo, Louisiana–Tulane, all
  2013 bowl games), per season 36/37/39/40/38/38/39/27 in burn-in and
  **40/41/40/44/44 in folds 2021–2025**,
- 1 game with `season_type` "" (2013 Penn State–Purdue, week 12 — a
  regular-season game whose type field is empty in the source).

Both readings, stated rather than resolved:

| | Reading A — as counted (frozen classifier semantics) | Reading B — §3.4 prose (regular-season only) |
|---|---|---|
| Population | **9,536** (= the frozen claim) | 9,033 (9,536 − 503 postseason) |
| Burn-in | 5,754 | 5,460 |
| Folds 2021–2025 | 739 / 747 / 757 / 765 / 774 | 699 / 706 / 717 / 721 / 730 |
| Pooled matched ML / spread / total | 3,335 / 3,773 / 3,773 (= the frozen claim) | 3,210 / 3,567 / 3,567 |

The R3 ratification text is *"the bound dataset, exactly as counted"* —
and exactly-as-counted is what this recount verifies (§2). The defect
is in the §3.4 prose: it describes a regular-season population that the
frozen counting never constructed. This does not change any R3 number,
but it is material to any future execution ruling: a scored run under
this freeze as counted would pool 209 postseason games into the five
folds. Before execution, the owner should either amend the §3.4 text
to describe the as-counted population or rule the population
regular-season-only (which changes the dataset and therefore, under
the freeze mechanics, the candidate identity). The recount takes no
position on which; it establishes that the two are different datasets.

## 5. Descriptive imprecisions (no count turns on either)

1. **Post-kickoff timing range.** BINDINGS.md / FREEZE_PACKAGE §4
   describe the 3 post-kickoff records as the archive `date_time`
   running "62 min–2 h" after the schedule kickoff. Measured from the
   raw archive against the raw schedules, the deltas are **62, 120,
   and 180 minutes** (401752685: +62; 401532395: +120; 401520150:
   +180) — the range is 62 min–3 h. The count (3) and the disposition
   are unaffected.
2. **"Flagged records never reach the emitted lines."** They do reach
   the snapshot file. The 3 post-kickoff records **are retained** in
   `lines_snapshot.json`'s games dict with full market data, and so
   are **all 58 orphan records** (as records with empty team ids —
   the archive itself carries no team ids for them; one orphan,
   401767476 Nicholls–Incarnate Word, even carries a quarantined
   moneyline, cross-checked via its `game_desc` naming). The flags
   live in the two manifests' `load_flags` lists, and the exclusion
   is effected at join/load time, not by absence from the file. No
   count turns on this: the post-kickoff games are FBS-vs-FCS
   (Arkansas–Western Carolina, Ohio–Long Island, Georgia–Austin
   Peay), hence non-population, and the orphans by definition join
   no results game, so neither class enters any matched count — but
   the sentence in BINDINGS.md overstates what the snapshot file
   itself does.
3. **"8 unresolved directory ids."** The frozen list decomposes as:
   **2 ids absent from the directory** (125290, 125291 — "Team
   Gaither" / "Team Robinson"; their 2 games are exactly the
   `BLOCK_TEAMS_UNRESOLVED` exclusions), plus **6 ids present in the
   directory with school names but empty classification** (3144 SOUTH,
   3145 NORTH, 3146 East, 3147 West, 3193 American, 3194 National —
   the all-star entities). The 6 present-but-unclassified ids touch 28
   games, all excluded as `POPULATION_NON_FBS_OPPONENT` inside the
   1,446. FREEZE_PACKAGE R3's own wording ("8 unresolved directory
   ids… their 2 affected games") is consistent with this once read
   this way; the label "unresolved" for the 6 is loose, the counts
   are exact under both readings.

## 6. Verification limits (what this recount could not re-derive)

- The **team-info parquet → directory snapshot mapping** was not
  re-derived row-by-row: no parquet reader is installed in this
  environment. Identity is instead pinned at both ends by hash — the
  parquet file on disk matches the frozen config's pin
  (`503549b9…`, 133,323 bytes) and the directory snapshot file matches
  its recorded hash (§1) — and the directory's content was exercised
  hard by the recount (1,840 teams; the override guard holds 13/13;
  my from-directory FBS recomputation reproduced all 22,990 stored
  FBS flags and the exact frozen funnel). A row-level parquet audit
  remains possible future work; nothing in R3's counts is sensitive
  to it beyond what those checks already cover.
- The staging copies under `~/workspace/tmp/cfbbind/` are build
  workspace copies, not a governed archive location. Their authority
  here rests entirely on the hash-pin match — the same identity
  standard the freeze itself uses (§3.8 kill criterion 1) — not on
  their location.
- No claim in this report extends beyond the frozen files listed in §1
  and the hash-verified raw sources in the staging directory.

## 7. PIT / timestamp disclosure — confirmed, not softened

- Results snapshot, verbatim: *"per-record timestamps: ABSENT — the
  source release carries retrieval timestamps per file, never per
  game; PIT discipline for results is the harness walk-forward
  chronology over kickoff_utc."*
- Lines snapshot limitations, verbatim in the file:
  `per_row_pit_certified: false`, `close_time_certified: false`,
  `decision_time_certified: false`,
  `paired_two_sided_quote_certified: false`,
  `retrospective_archive: true`; and the standing label *"CFBD closing
  lines carry no per-row timestamps; this comparison is descriptive
  only and supports no claim of market outperformance, no CLV
  statement, and no promotion input."*
- FREEZE_PACKAGE §3.2/§3.5 carry the same disclosure in the same terms.
  The recount **confirms** the package's non-PIT disclosure is present
  in, and consistent across, the config, both manifests, and both
  relevant snapshots. Nothing in the frozen record overstates the
  corpus's timestamp properties; nothing here softens that.

## 8. Bottom line

**Yes — the R3 dataset stands exactly as counted.** Population 9,536;
exclusions 511 Illinois / 1,446 non-FBS / 2 unresolved / 0 no-contest;
220 Bovada moneyline quarantines (214 sign-inconsistent, 6
uncheckable); 58 orphans; 3 post-kickoff; pooled matched
3,335 / 3,773 / 3,773 / 0 — every figure independently reproduced,
144/144 checks, with the corpus hashes verified first and the
lines-side figures re-derived from the pinned raw archive rows game
by game (0 disagreements in 4,325 games).

The one material caveat is §4: the frozen §3.4 prose describes a
regular-season-only population, but the dataset as counted pools 503
postseason games (209 in the folds). The counts are right; the
sentence is wrong. That conflict — not any R3 number — is what a
future freeze or execution act needs to resolve.

*Recount performed Oct 14, 2026, by the Muse lane under issue #2218
M2. Scripts:
[recount_r3.py](sandbox://workspace/sportsedge/cfb_four_family_evaluation_20261013/recount_r3.py)
(snapshot-level) and
[recount_r3_raw.py](sandbox://workspace/sportsedge/cfb_four_family_evaluation_20261013/recount_r3_raw.py)
(raw-source re-derivation).
Nothing pushed; no frozen file modified; Attempt 1 HELD and unspent.*
